import pathlib
import yaml


def resolve_dirs(dirs):
    for key in ("problems", "compilers", "runners", "checkers"):
        path = dirs[key]
        if not path:
            raise KeyError(key)
        path = pathlib.Path(path).expanduser().resolve()
        if not path.is_dir():
            raise FileNotFoundError(path)
        dirs[key] = path


def collect_executables(path) -> { str: str }:
    """
    Searches the given path for executable files.
    Raises FileExistsError if there are more than one file with the same name.
    """

    registry = { }
    for entry in path.iterdir():
        if entry.is_file() and entry.stat().st_mode & 0b001001001:
            if entry.stem not in registry:
                registry[entry.stem] = str(entry.resolve())
            else:
                raise FileExistsError("Cannot have both '%s' and '%s' in '%s'" % (
                    pathlib.Path(registry[entry.stem]).name, entry.name, path,
                ))

    if not registry:
        raise FileNotFoundError("No executables found in '%s'" % path)
    return registry


def read(filename):
    with open(filename, encoding="utf-8-sig") as f:
        cnf = yaml.safe_load(f)
    resolve_dirs(cnf["dirs"])
    cnf["exec"] = {
        key: collect_executables(cnf["dirs"][key]) for key in ("compilers", "runners", "checkers")
    }
    return cnf
