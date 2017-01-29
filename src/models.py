import collections


User = collections.namedtuple("User",
    ["login", "username"])

Problem = collections.namedtuple("Problem",
    ["id", "name", "path", "time_limit", "memory_limit", "checker", "mask_in", "mask_out"])

Contest = collections.namedtuple("Contest",
    ["id", "is_school"])

ProblemInContest = collections.namedtuple("ProblemInContest",
    ["problem", "contest", "number"])

Compiler = collections.namedtuple("Compiler",
    ["name", "codename", "runner_codename"])

Attempt = collections.namedtuple("Attempt",
    ["id", "pic", "user", "source", "compiler"])
