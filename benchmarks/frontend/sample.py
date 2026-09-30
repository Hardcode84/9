#!/usr/bin/env python3
"""Sample repeated, uninstrumented frontend commands with Linux perf.

Run from the repository root. A failed command stops the run.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from profile import cases, environment, run_process, verify_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", nargs="+", required=True)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    selected = {name: cases()[name] for name in args.cases}
    if args.repeats < 1:
        parser.error("A positive repeat count is required")
    if args.worker:
        for command in selected.values():
            for _ in range(args.repeats):
                run_process(command, env=environment(),
                            stdout=subprocess.DEVNULL).check_returncode()
        return
    if args.output is None:
        parser.error("An output directory is required")
    verify_inputs()
    args.output.mkdir(parents=True, exist_ok=False)
    records = []
    for name in selected:
        data = args.output / f"{name}.data"
        command = ["perf", "record", "--quiet", "-e", "cycles:u", "-F", "997",
                   "-o", str(data), "--", "taskset", "-c", str(args.cpu),
                   sys.executable, __file__, "--worker", "--cases", name,
                   "--repeats", str(args.repeats)]
        start = time.perf_counter()
        with (args.output / f"{name}.record.txt").open("w") as stderr:
            subprocess.run(command, check=True, stderr=stderr, env=environment())
        wall_s = time.perf_counter() - start
        report = ["perf", "report", "--stdio", "--stdio-color=never",
                  "--no-children", "--show-nr-samples", "--show-total-period",
                  "--percent-limit", "0", "--sort", "comm,dso,symbol",
                  "--field-separator", ";", "-i", str(data)]
        with (args.output / f"{name}.report.txt").open("w") as output:
            subprocess.run(report, check=True, stdout=output, env=environment())
        records.append({"case": name, "repeats": args.repeats,
                        "wall_s": wall_s, "command": selected[name],
                        "event": "cycles:u", "frequency_hz": 997,
                        "pinned_cpu": args.cpu, "report_command": report})
        (args.output / "runs.json").write_text(json.dumps(records, indent=2) + "\n")
        print(f"Sampled {name}: {wall_s:.3f}s for {args.repeats} checks", flush=True)


if __name__ == "__main__":
    main()
