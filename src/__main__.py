#!/usr/bin/env python3

"""
Polls the database for attempts and tests them at the specified path.

Usage:
  ./lerna-tester -c <config> [-f] [-l <log-dir>] [-n <name>] [--] <cwd>

Options:
  -c, --config <file>   Path to a YAML configuration file.
  -f, --force           Do not prompt if the working directory is not empty.
  -l, --log-dir <path>  Directory to put the logs in [default: ./].
  -n, --name <name>     Specify a name to differentiate this tester from others.
"""

import docopt
import logging.config
import os
import pathlib
import signal
import sys

import config
import tester


terminating = False


def gracefully_restart(*args):
    tester.needs_restarting = True


def gracefully_shutdown(*args):
    global terminating
    if not terminating:
        print("Shutting down", flush=True)
        terminating = tester.needs_restarting = True
    else:
        print("Terminating", flush=True)
        sys.exit()


def sleep(duration):
    signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGHUP, signal.SIGINT, signal.SIGTERM])
    try:
        acquired = signal.sigtimedwait([signal.SIGHUP, signal.SIGINT, signal.SIGTERM], duration)
        if acquired is not None:
            if acquired.si_signo == signal.SIGHUP:
                gracefully_restart()
            else:
                gracefully_shutdown()
    finally:
        signal.pthread_sigmask(signal.SIG_UNBLOCK, [signal.SIGHUP, signal.SIGINT, signal.SIGTERM])


def main():
    args = docopt.docopt(__doc__)
    log_dir = pathlib.Path(args["--log-dir"])
    cwd = pathlib.Path(args["<cwd>"])

    try:
        cwd.mkdir(parents=True)
    except FileExistsError:
        if not args["--force"] and next(cwd.iterdir(), None) is not None:
            print("Working directory is not empty. All files inside it will be deleted.")
            answer = input("Are you sure you want to proceed? [y/N] ")
            if answer.strip().lower() not in ("y", "yes", "yessir", "yeah"):
                sys.exit("Aborted")

    cwd = cwd.resolve()
    cwd.chmod(0o777) # Cannot be set in .mkdir due to umask.
    initial_dir = os.getcwd()
    while not terminating:
        os.chdir(initial_dir)
        tester.needs_restarting = False
        cnf = config.read(args["--config"])

        log_dir.mkdir(parents=True, exist_ok=True)
        os.chdir(str(log_dir)) # Log file paths are either absolute or relative to log_dir.
        logging.config.dictConfig(cnf["logging"])

        os.chdir(str(cwd))
        tester.run(cnf, cwd, args["--name"] or "", sleep)


if __name__ == "__main__":
    signal.signal(signal.SIGQUIT, lambda signum, frame: sys.exit("SIGQUIT received"))
    signal.signal(signal.SIGTERM, gracefully_shutdown)
    signal.signal(signal.SIGINT,  gracefully_shutdown)
    signal.signal(signal.SIGHUP,  gracefully_restart)

    main()
