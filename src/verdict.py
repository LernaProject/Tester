import enum


class Verdict(enum.Enum):
    OK = "OK"
    TL = "Time limit exceeded"
    IL = "Idleness limit exceeded"
    ML = "Memory limit exceeded"
    RT = "Run-time error"
    SV = "Security violation"
    WA = "Wrong answer"
    PE = "Presentation error"
    SE = "System error"

    @classmethod
    def from_testlib_returncode(cls, code):
        return { 0: cls.OK, 1: cls.WA, 2: cls.PE }.get(code, cls.SE)
