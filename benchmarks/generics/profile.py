#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Profile a captured ownership generics driver with named Crust functions."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from generics_cost import run  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    args = parser.parse_args()
    prepared = args.prepared.resolve()
    work = args.work.resolve()
    if work.exists() or not work.is_relative_to(ROOT / "build"):
        parser.error("select a new directory under build/")
    work.mkdir(parents=True)
    preparation = json.loads((prepared / "preparation.json").read_text())
    command = preparation["commands"][1].copy()
    command[0] = str(prepared / "snapshot" / Path(command[0]).relative_to(ROOT))
    command[command.index("-o") + 1] = str(work / "compiler")
    exports = []
    for index, argument in enumerate(command):
        path = Path(argument)
        if argument.endswith(".crs"):
            source = prepared / "snapshot" / path.relative_to(ROOT)
            command[index] = str(source)
            exports += re.findall(r"^fn (\w+)\(", source.read_text(), re.MULTILINE)
        elif path.is_absolute() and argument.endswith(".a"):
            command[index] = str(prepared / "snapshot" / path.relative_to(ROOT))
    for name in exports:
        if name != "main":
            command += ["--export", name]
    run(command)
    inputs = [
        prepared / "inputs" / f"{name}.crs"
        for name in ("provider", "checked", "payloads", "program")
    ]
    profile = [
        "valgrind",
        "--tool=callgrind",
        "--collect-atstart=no",
        "--toggle-collect=ogc_generic",
        f"--callgrind-out-file={work}/callgrind.out",
        str(work / "compiler"),
        "generic",
        "measured",
        str(work / "generic.c"),
        str(work / "generic.rsp"),
        *map(str, inputs),
    ]
    result = run(profile)
    (work / "stdout.txt").write_text(result.stdout)
    (work / "stderr.txt").write_text(result.stderr)
    for name, options in (("inclusive", ["--inclusive=yes"]), ("self", [])):
        with (work / f"{name}.txt").open("w") as output:
            subprocess.run(
                ["callgrind_annotate", *options, "--threshold=99", str(work / "callgrind.out")],
                stdout=output,
                check=True,
            )
    (work / "commands.json").write_text(
        json.dumps({"compile": command, "profile": profile}, indent=2) + "\n"
    )
    print(work)


if __name__ == "__main__":
    main()
