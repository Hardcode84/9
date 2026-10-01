"""Check an external C body emitter and its failure contract."""

import argparse
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
    with tempfile.TemporaryDirectory(prefix="rmd-c-body-") as directory:
        work = Path(directory)
        harness = work / "harness"
        output = work / "program"
        library = work / "ordinary-backend.so"
        shutil.copyfile(build / "rmd-c-library.so", library)
        sources = ["api/rmd0.rmd", "api/rmd0_stage.rmd", "stages/c/model.rmd",
                   "stages/c/api.rmd", "stages/c/extension.rmd", "tests/c_body.rmd"]
        subprocess.run([str(build / "rmd-c"), "-o", str(harness), *sources,
                        *("--cflag=" + flag for flag in shlex.split(args.cflags)),
                        "--ldflag=" + str(library),
                        "--ldflag=" + str(build / "librmd0.a"),
                        "--ldflag=" + str(build / "librmd0_host.a"),
                        *("--ldflag=" + flag for flag in shlex.split(args.ldflags))],
                       cwd=ROOT, check=True)
        subprocess.run([str(harness), str(output)], cwd=ROOT, check=True)
        result = subprocess.run([str(output)], cwd=ROOT, check=False)
        if result.returncode != 42:
            raise RuntimeError(f"external body returned {result.returncode}, expected 42")
    print("C body extension: native result, absent seed bodies, and three failure paths passed")


if __name__ == "__main__":
    main()
