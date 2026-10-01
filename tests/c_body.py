"""Check an external C body emitter and its failure contract."""

import argparse
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    build = args.build.resolve()
    with tempfile.TemporaryDirectory(prefix="crust-c-body-") as directory:
        work = Path(directory)
        harness = work / "harness"
        output = work / "program"
        library = work / "ordinary-backend.so"
        shutil.copyfile(build / "crust-c-library.so", library)
        sources = [
            "api/crust0.crs",
            "api/crust0_stage.crs",
            "stages/c/model.crs",
            "stages/c/api.crs",
            "stages/c/extension.crs",
            "tests/c_body.crs",
        ]
        subprocess.run(
            [
                str(build / "crust-c"),
                "-o",
                str(harness),
                *sources,
                *("--cflag=" + flag for flag in shlex.split(args.cflags)),
                "--ldflag=" + str(library),
                "--ldflag=" + str(build / "libcrust0.a"),
                "--ldflag=" + str(build / "libcrust0_host.a"),
                *("--ldflag=" + flag for flag in shlex.split(args.ldflags)),
            ],
            cwd=ROOT,
            check=True,
        )
        subprocess.run([str(harness), str(output)], cwd=ROOT, check=True)
        result = subprocess.run([str(output)], cwd=ROOT, check=False)
        if result.returncode != 42:
            raise RuntimeError(f"external body returned {result.returncode}, expected 42")
        symbols = subprocess.run(
            ["nm", "--defined-only", str(output)], check=True, capture_output=True
        ).stdout
        if not re.search(rb"\bt r_g[0-9]+\b", symbols) or not re.search(
            rb"\br r_g[0-9]+\b", symbols
        ):
            raise RuntimeError(f"private function and constant symbols are missing: {symbols!r}")
        public = subprocess.run(
            ["nm", "-g", "--defined-only", str(output)], check=True, capture_output=True
        ).stdout
        if re.search(rb"\br_g[0-9]+\b", public) or b"body_entry" not in public:
            raise RuntimeError(f"private symbols escaped native visibility: {public!r}")
    print(
        "C body extension: native result, absent seed bodies, private linkage, and four failure paths passed"
    )


if __name__ == "__main__":
    main()
