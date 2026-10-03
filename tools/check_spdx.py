# SPDX-License-Identifier: Apache-2.0

"""Check the first comment in source, configuration, and documentation files."""

import sys
from pathlib import Path

IDENTIFIER = "SPDX-License-Identifier: Apache-2.0"


def expected_header(path):
    if path.suffix in {".c", ".h", ".cc", ".cpp", ".hpp"}:
        return f"/* {IDENTIFIER} */"
    if path.suffix in {".crs", ".rs", ".js", ".cjs", ".mjs"}:
        return f"// {IDENTIFIER}"
    if path.suffix == ".md":
        return f"<!-- {IDENTIFIER} -->"
    if path.suffix in {".py", ".sh", ".yaml", ".yml", ".toml"} or path.name in {
        "Makefile",
        ".clang-format",
        ".gitignore",
    }:
        return f"# {IDENTIFIER}"
    raise ValueError("unsupported SPDX comment syntax")


def main():
    failed = False
    for name in sys.argv[1:]:
        path = Path(name)
        try:
            expected = expected_header(path)
            with path.open("rb") as source:
                actual = source.readline()
                if actual.startswith(b"#!"):
                    actual = source.readline()
            if actual.rstrip(b"\r\n") != expected.encode("ascii"):
                raise ValueError(f"expected {expected!r} at the start, after any shebang")
        except (OSError, ValueError) as error:
            print(f"{name}: {error}", file=sys.stderr)
            failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
