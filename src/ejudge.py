import verdict


class Protocol:
    def __init__(self, binary_str):
        self.verdict = None
        self.cpu_time = self.real_time = self.vm_size = 0
        for line in binary_str.splitlines():
            key, _, value = line.partition(b": ")
            if key == b"Status":
                if value not in { b"OK", b"TL", b"ML", b"RT", b"SV" }:
                    raise ValueError("ejudge-execute returned unknown Status:", value)
                self.verdict = verdict.Verdict[value.decode()]
            elif key in { b"CPUTime", b"RealTime", b"VMSize" }:
                try:
                    value = int(value)
                except ValueError:
                    raise ValueError(
                        "ejudge-execute returned malformed %s: %s" % (key.decode(), value))
                else:
                    if key == b"CPUTime":
                        self.cpu_time = value
                    elif key == b"RealTime":
                        self.real_time = value
                    else:
                        self.vm_size = value

        if self.verdict is None:
            raise ValueError("ejudge-execute returned no Status")
