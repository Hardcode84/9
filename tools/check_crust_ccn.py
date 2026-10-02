# SPDX-License-Identifier: Apache-2.0

"""Build the Crust CCN checker and check implementation and test sources."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    try:
        built = subprocess.run(
            ["make", "--no-print-directory", "-s", "BUILD=build", "ccn-stage"], cwd=ROOT
        )
        if built.returncode:
            return built.returncode
        sources = sorted(
            str(path.relative_to(ROOT))
            for directory in ("api", "stages", "tests")
            for path in (ROOT / directory).rglob("*.crs")
        )
        return subprocess.run(
            ["build/crust-ccn", "-w", "--CCN", "15", "--", *sources], cwd=ROOT
        ).returncode
    except OSError as error:
        print(f"Crust CCN check: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
