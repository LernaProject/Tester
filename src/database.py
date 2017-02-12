import postgresql.exceptions
import models


class Connection:
    def __init__(self, locator):
        self._db = postgresql.open(locator)

        self._create_tester_status = self._db.prepare("""
            INSERT INTO checker_statuses (updated_at)
            VALUES (NOW())
            RETURNING id
        """)

        self.update_tester_status = self._db.prepare("""
            UPDATE checker_statuses
            SET updated_at = NOW()
            WHERE id = $1
        """)

        self.delete_tester_status = self._db.prepare("""
            DELETE FROM checker_statuses
            WHERE id = $1
        """)

        self._get_untested_attempt = self._db.prepare("""
            SELECT
                a.id, a.source,                                               -- 0:2
                pic.problem_id, p.name, p.path, p.time_limit, p.memory_limit, -- 2:7
                p.checker, p.mask_in, p.mask_out,                             -- 7:10
                pic.contest_id, c.is_school,                                  -- 10:12
                pic.number,                                                   -- 12:13
                u.login, u.username,                                          -- 13:15
                comp.name, comp.codename, comp.runner_codename                -- 15:18
            FROM attempts a
            JOIN compilers comp ON comp.id = a.compiler_id
            JOIN users u ON u.id = a.user_id
            JOIN problem_in_contests pic ON pic.id = a.problem_in_contest_id
            JOIN problems p ON p.id = pic.problem_id
            JOIN contests c ON c.id = pic.contest_id
            WHERE (a.result IS NULL OR a.result = '') -- TODO: Drop `a.result IS NULL`.
            AND   comp.codename = ANY($1)
            AND   comp.runner_codename = ANY($2)
            ORDER BY a.time
            LIMIT 1
        """)

        self._acquire_attempt = self._db.prepare("""
            UPDATE attempts
            SET tester_name = $2,
                result = $3,
                error_message = NULL,
                checker_comment = '',
                used_time = NULL,
                used_memory = NULL,
                score = NULL,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.update_attempt_result = self._db.prepare("""
            UPDATE attempts
            SET result = $2,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.update_attempt_result_and_error_message = self._db.prepare("""
            UPDATE attempts
            SET result = $2,
                error_message = $3,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.update_attempt_result_and_stats = self._db.prepare("""
            UPDATE attempts
            SET result = $2,
                used_time = $3,
                used_memory = $4,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.update_attempt_result_and_stats_with_score = self._db.prepare("""
            UPDATE attempts
            SET result = $2,
                used_time = $3,
                used_memory = $4,
                score = $5,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.update_attempt_result_and_stats_with_comment = self._db.prepare("""
            UPDATE attempts
            SET result = $2,
                used_time = $3,
                used_memory = $4,
                checker_comment = $5,
                updated_at = NOW()
            WHERE id = $1
        """)

        self.create_test_info = self._db.prepare("""
            INSERT INTO test_infos
                (attempt_id, test_number, result, used_time, used_memory, checker_comment)
            VALUES ($1, $2, $3, $4, $5, $6)
        """)

    def close(self):
        self._db.close()

    def create_tester_status(self):
        return self._create_tester_status.first()

    def acquire_untested_attempt(self, tester_name, result, available_compilers, available_runners):
        while True:
            try:
                with self._db.xact("SERIALIZABLE"):
                    res = self._get_untested_attempt.first(available_compilers, available_runners)
                    if res is None:
                        return None
                    self._acquire_attempt(res[0], tester_name, result)
            except postgresql.exceptions.SerializationError:
                pass
            else:
                problem = models.Problem(*res[2:10])
                contest = models.Contest(*res[10:12])
                pic = models.ProblemInContest(problem, contest, res[12])
                user = models.User(*res[13:15])
                compiler = models.Compiler(*res[15:18])
                return models.Attempt(res[0], pic, user, res[1], compiler)
