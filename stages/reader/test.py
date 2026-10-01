"""Build the RMD reader and compare its syntax with the seed reader."""

import argparse
import ast
import re
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
READER = [ROOT / "stages/reader" / name for name in ("model.rmd", "lex.rmd", "parse.rmd")]


def run(arguments, **kwargs):
    subprocess.run([str(argument) for argument in arguments], check=True, cwd=ROOT, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--work", type=Path, default=ROOT / ".profile-cache/reader-tests")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--backend", choices=("seed", "c"), default="seed")
    parser.add_argument("--cflag", action="append", default=[])
    args = parser.parse_args()
    build = args.build.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    sources = [ROOT / "api/rmd0.rmd", ROOT / "api/rmd0_host.rmd", ROOT / "api/rmd0_eval.rmd",
               *READER, ROOT / "stages/reader/test.rmd"]
    run([build / "rmd0", "--check", *sources])
    if args.backend == "seed":
        run([build / "rmd0", "-S", "-o", work / "reader-test.s", *sources])
        run(["as", "--64", work / "reader-test.s", "-o", work / "reader-test.o"])
    else:
        run([build / "rmd-c", "--object", "-o", work / "reader-test.o",
             *("--cflag=" + flag for flag in args.cflag), *sources])
    run([*shlex.split(args.cc), "-no-pie", work / "reader-test.o", build / "librmd0_run.a",
         build / "librmd0.a", build / "librmd0_host.a", "-lffi", "-ldl",
         *shlex.split(args.ldflags), "-o", work / "reader-test"])

    literal = r'"(?:\\.|[^"\\])*"'
    cases = re.findall(r'SYNTAX\(\s*(' + literal + r')\s*,\s*((?:' + literal + r'\s*)+),\s*(true|false)\s*\)',
                       (ROOT / "tests/read_test.c").read_text())
    assert len(cases) >= 100, "the seed corpus extraction is incomplete"
    paths = []
    for index, (_, strings, _) in enumerate(cases):
        data = b"".join(ast.literal_eval("b" + part) for part in re.findall(literal, strings))
        path = work / f"syntax-{index:03}.rmd"
        path.write_bytes(data)
        paths.append(path)
    for depth in (1, 30, 120, 250, 256, 260, 500):
        for name, data in (
            ("types", b"record R { x:" + b"*" * depth + b"u8; }"),
            ("groups", b"fn f()->unit{" + b"(" * depth + b"1u8" + b")" * depth + b";}"),
            ("blocks", b"fn f()->unit{" + b"{" * depth + b"}" * depth + b"}"),
        ):
            path = work / f"depth-{name}-{depth}.rmd"
            path.write_bytes(data)
            paths.append(path)
    symbol = "".join(f"\\x{byte:02x}" for byte in range(1, 128))
    extra = {
        "native-all-ascii": f'extern fn f()->unit="{symbol}";'.encode(),
        "large-string": b'const value:*u8="' + b"x" * 70000 + b'";',
        "large-name": b"fn " + b"n" * 70000 + b"()->unit{}",
        "all-string-bytes": b'const value:*u8="' + b"".join(f"\\x{byte:02x}".encode() for byte in range(256)) + b'";',
    }
    for name, data in extra.items():
        path = work / (name + ".rmd")
        path.write_bytes(data)
        paths.append(path)
    production = [*sorted((ROOT / "api").glob("*.rmd")),
                  *sorted((ROOT / "stages/c").glob("*.rmd")),
                  *READER, ROOT / "stages/reader/test.rmd", ROOT / "tests/runtime.rmd",
                  ROOT / "examples/intrusive/program.rmd", ROOT / "examples/custom-stage/stage.rmd"]
    run([work / "reader-test", *paths, *production])
    print(f"RMD reader: {len(cases)} seed cases, {len(paths)-len(cases)} boundary cases, "
          f"{len(production)} production files; exact AST/diagnostic comparisons passed")
    print("RMD hooks: four production hooks, five contract errors, token limit, "
          "allocation failure, and two source ranges passed")


if __name__ == "__main__":
    main()
