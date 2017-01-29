import datetime
import itertools
import logging
import os.path
import pathlib
import shlex
import shutil
import subprocess
import textwrap
import time

import database
import ejudge
from   verdict import Verdict


needs_restarting = False


class RecoverableError(Exception):
    """
    An error which does not affect the ability to continue testing other solutions.
    """


def clean_dir(path):
    """
    Removes every file and directory at the given path.
    """

    for entry in path.iterdir():
        if entry.is_file() or entry.is_symlink():
            entry.unlink()
        else:
            shutil.rmtree(str(entry))


def iterpattern(pattern, start=0):
    """
    Yields index-annotated file names that match the given pattern.
    """

    for i in itertools.count(start):
        file_name = pattern % i
        if not os.path.isfile(file_name):
            break
        yield i, file_name


def compile_source(cnf, source, compiler_codename) -> (bytes, bytes):
    proc = subprocess.run(
        [cnf["exec"]["compilers"][compiler_codename]],
        input=source.encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout if proc.returncode == 0 else None, proc.stderr


def locate_checker(cnf, checker_cmd, probable_path) -> [str]:
    args = shlex.split(checker_cmd)
    if not args:
        raise RecoverableError("Checker is empty")

    if not os.path.isabs(args[0]):
        args[0] = cnf["exec"]["checkers"].get(args[0], str(probable_path / args[0]))

    if not os.path.isfile(args[0]):
        raise RecoverableError("Checker is not found")

    return args


def execute_program(cnf, args, data):
    proc = subprocess.run(args, input=data, stdout=subprocess.PIPE)
    with open(cnf["files"]["ejudge_log"], "wb") as f:
        f.write(proc.stdout)
    try:
        return ejudge.Protocol(proc.stdout)
    except ValueError as e:
        raise RecoverableError(*e.args)


def check_output(args, input_file, output_file, answer_file, cwd) -> (Verdict, bytes):
    extra_args = [input_file, output_file, answer_file] # Assume the checker is testlib-compatible.
    # Command line may look like "/usr/bin/java check", so we need to chdir.
    proc = subprocess.run(args + extra_args, stderr=subprocess.PIPE, cwd=cwd)
    return Verdict.from_testlib_returncode(proc.returncode), proc.stderr


def run_tests(db, cnf, cwd, attempt, logger_info, data):
    problem = attempt.pic.problem
    is_school = attempt.pic.contest.is_school
    runner_args = [
        cnf["exec"]["runners"][attempt.compiler.runner_codename],
        cnf["files"]["stdin"],
        cnf["files"]["stdout"],
        cnf["files"]["stderr"],
        str(int(problem.time_limit / cnf["behaviour"]["time_multiplier"] + .5)),
        str(problem.memory_limit),
    ]
    tests_path = cnf["dirs"]["problems"] / problem.path
    checker_args = locate_checker(cnf, problem.checker, tests_path)
    checker_comment_max_len = cnf["behaviour"]["checker_comment_max_len"]
    assert checker_comment_max_len >= 3

    max_time     = 1 # ms
    max_memory   = 125 # KB
    passed_tests = 0

    print(tests_path, '*', sep=os.sep)
    for test_number, test_file in iterpattern(str(tests_path / problem.mask_in), 1):
        print(problem.mask_in % test_number)

        db.update_attempt_result_and_stats(
            attempt.id, "Testing... %d" % test_number, max_time / 1000, max_memory)

        shutil.copyfile(test_file, cnf["files"]["stdin"])
        protocol = execute_program(cnf, runner_args, data)
        protocol.cpu_time = int(protocol.cpu_time * cnf["behaviour"]["time_multiplier"] + .5)
        protocol.real_time = int(protocol.real_time * cnf["behaviour"]["time_multiplier"] + .5)
        max_time = max(max_time, protocol.cpu_time)
        max_memory = max(max_memory, protocol.vm_size >> 10)
        if protocol.verdict is Verdict.TL:
            # ejudge-execute cannot tell TL apart from IL.
            if protocol.cpu_time < problem.time_limit and protocol.real_time >= problem.time_limit:
                protocol.verdict = Verdict.IL
        elif protocol.verdict is Verdict.OK:
            protocol.verdict, checker_comment = check_output(
                checker_args,
                test_file,
                str(cwd / cnf["files"]["stdout"]),
                problem.mask_out % test_number if problem.mask_out else os.devnull,
                cwd=str(tests_path),
            )
            checker_comment = checker_comment.decode(errors="replace")
            print(end=checker_comment)
            if len(checker_comment) > checker_comment_max_len:
                checker_comment = checker_comment[:checker_comment_max_len - 3] + "..."

        if is_school:
            db.create_test_info(
                attempt.id,
                test_number,
                protocol.verdict.value,
                max(protocol.cpu_time, 1) / 1000,
                max(protocol.vm_size >> 10, 125),
                checker_comment,
            )
            if protocol.verdict is Verdict.OK:
                passed_tests += 1

        if protocol.verdict is Verdict.SE:
            print("System error")
            logging.error("Checker failed on test %d" % test_number, extra=logger_info)
            db.update_attempt_result_and_stats_with_comment(
                attempt.id,
                "System error on test %d" % test_number,
                max_time / 1000,
                max_memory,
                checker_comment,
            )
            return
        elif not is_school and protocol.verdict is not Verdict.OK:
            result = "%s on test %d" % (protocol.verdict.value, test_number)
            db.update_attempt_result_and_stats_with_comment(
                attempt.id,
                result,
                max_time / 1000,
                max_memory,
                checker_comment,
            )
            break
    else:
        # All the tests have been run.
        if is_school:
            score = passed_tests / test_number
            db.update_attempt_result_and_stats_with_score(
                attempt.id,
                "Tested",
                max_time / 1000,
                max_memory,
                score * 100,
            )
        else:
            result = "Accepted"
            db.update_attempt_result_and_stats(attempt.id, result, max_time / 1000, max_memory)

    max_time /= 1000
    max_memory /= 1024
    if is_school:
        print("Score: {:.1%} ({:.3f} sec / {:.1f} MB)".format(score, max_time, max_memory))
        result = "{:.1%}".format(score)
    else:
        print(result, "({:.3f} sec / {:.1f} MB)".format(max_time, max_memory))
    logging.info(result, extra=logger_info)


def process_attempt(db, cnf, cwd, attempt, logger_info):
    start_time = time.perf_counter()
    problem = attempt.pic.problem
    if problem.time_limit % 1000 == 0:
        time_limit = problem.time_limit // 1000
    else:
        time_limit = problem.time_limit / 1000
    print(textwrap.dedent("""
        {asctime}
        [{a.id:05}/{p.id:03}] {contest.id:03}#{pic.number}: "{p.name}" by {u.username} ({u.login})
        {compiler.name} / {time_limit} sec / {p.memory_limit} MB / {p.checker}
    """).strip().format(
        asctime=datetime.datetime.now().strftime("%d.%m.%y %H:%M:%S"),
        a=attempt,
        p=problem,
        contest=attempt.pic.contest,
        pic=attempt.pic,
        u=attempt.user,
        compiler=attempt.compiler,
        time_limit=time_limit,
    ))

    clean_dir(pathlib.Path())

    print("Compiling...")
    db.update_attempt_result(attempt.id, "Compiling...")
    data, errors = compile_source(cnf, attempt.source, attempt.compiler.codename)
    if errors:
        with open(cnf["files"]["compiler_log"], "wb") as f:
            f.write(errors)
    if data is None:
        print("Compilation error")
        logging.info("Compilation error", extra=logger_info)
        db.update_attempt_result_and_error_message(
            attempt.id, "Compilation error", errors.decode(errors="replace"))
    else:
        run_tests(db, cnf, cwd, attempt, logger_info, data)

        print("Completed in %.1f seconds." % (time.perf_counter() - start_time))


def run(cnf, cwd, name, sleep):
    print("Started in", cwd)
    print()
    db = database.Connection(cnf["db"]["locator"])
    try:
        status = db.create_tester_status()
        try:
            while not needs_restarting:
                attempt = db.acquire_untested_attempt(
                    name, "Queued",
                    cnf["exec"]["compilers"],
                    cnf["exec"]["runners"],
                )
                if attempt is None:
                    sleep(cnf["behaviour"]["interval"])
                else:
                    try:
                        try:
                            logger_info = {
                                "pic": attempt.pic,
                                "problem": attempt.pic.problem,
                                "contest": attempt.pic.contest,
                                "compiler": attempt.compiler,
                                "user": attempt.user,
                            }
                            process_attempt(db, cnf, cwd, attempt, logger_info)
                        except:
                            print("System error")
                            db.update_attempt_result(attempt.id, "System error")
                            raise
                    except RecoverableError as e:
                        logging.error(e.args[0], extra=logger_info)
                    except SystemExit:
                        logging.error("Interrupted", extra=logger_info)
                        raise
                    except:
                        logging.exception("System error", extra=logger_info)
                        raise
                    finally:
                        print()
                db.update_tester_status(status)
        finally:
            db.delete_tester_status(status)
    finally:
        db.close()
