#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check the documented block boundaries through each complete stage pipeline."""

import argparse
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build"))
    args = parser.parse_args()
    work = args.build / "nesting-tests"
    work.mkdir(parents=True, exist_ok=True)
    checks = 0
    for driver, return_limit, assignment_limit in (
        ("crust0", 253, 252),
        ("crust-c", 253, 252),
        ("crust-resource", 250, 249),
        ("crust-overload", 253, 252),
        ("crust-overload-resource", 250, 249),
    ):
        for kind, limit, inner, suffix in (
            ("return", return_limit, "return 0i32;", ""),
            ("assignment", assignment_limit, "argc=argc+1i32;", "return 0i32;"),
        ):
            for depth in (limit, limit + 1):
                source = work / f"{driver}-{kind}-{depth}.crs"
                source.write_text(
                    "fn main(argc:i32,argv:**u8)->i32{"
                    + "{" * depth
                    + inner
                    + "}" * depth
                    + suffix
                    + "}\n"
                )
                result = subprocess.run(
                    [args.build / driver, "--check", source], capture_output=True, timeout=30
                )
                assert result.returncode == int(depth > limit), (source, result)
                assert not result.stdout, (source, result.stdout)
                if depth == limit:
                    assert not result.stderr, (source, result.stderr)
                else:
                    assert str(source).encode() in result.stderr, (source, result.stderr)
                    assert any(
                        text in result.stderr
                        for text in (b"nesting limit of 256", b"traversal depth limit of 256")
                    ), (source, result.stderr)
                checks += 1
    print(f"Stage nesting: {checks} accepted/rejected boundary checks passed")


if __name__ == "__main__":
    main()
