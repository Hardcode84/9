# SPDX-License-Identifier: Apache-2.0
"""Run evaluator contracts and require fatal failures to terminate child processes."""

import argparse
import signal
from pathlib import Path

from host import ROOT, WINDOWS, disable_core_dumps, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    tool = args.build.resolve() / "eval_test"
    disable_core_dumps()
    run([tool], cwd=ROOT, check=True, timeout=120)
    cases = [
        ["--trap", expression]
        for expression in (
            "trap",
            "1u8/0u8",
            "1i64%0i64",
            "-128i8/-1i8",
            "-128i8%-1i8",
            "-9223372036854775808i64/-1i64",
            "-9223372036854775808i64%-1i64",
            "1u8<<8u8",
            "1u64>>64u64",
            "1i16<<-1i16",
        )
    ]
    cases.append(["--callback-failure"])
    for arguments in cases:
        result = run([tool, *arguments], cwd=ROOT, capture_output=True, timeout=30)
        assert result.returncode in ((3, 0xC0000409) if WINDOWS else (-signal.SIGABRT,)), (
            arguments,
            result,
        )
        assert not result.stdout, result
        if arguments[0] == "--trap":
            assert (
                b"eval-test:2:" in result.stderr and b"required execution trap" in result.stderr
            ), result
        else:
            assert b"allocation" in result.stderr, result
    print(f"evaluator: {len(cases)} fatal trap/callback contracts passed")


if __name__ == "__main__":
    main()
