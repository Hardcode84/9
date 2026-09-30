#!/usr/bin/env python3
"""Save compact evidence from completed frontend measurements.

Raw traces stay in the cache. The output contains their hashes and summaries.
The measureme 12.0.3 summarize binary must already be built.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import statistics
import subprocess

from clang_trace import analyze_trace


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def seconds(value):
    return value["secs"] + value["nanos"] / 1e9


def validate_collection(records, environment, label):
    expected = {(case, index) for case in environment["commands"]
                for index in range(environment["repeats"])}
    actual = [(r["case"], r["repetition"]) for r in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError(f"Invalid {label} coverage: "
                         f"missing={sorted(expected - set(actual))}, "
                         f"extra={sorted(set(actual) - expected)}, "
                         f"duplicates={len(actual) - len(set(actual))}")


def gcc_rows(text):
    result = {}
    for line in text.splitlines():
        match = re.match(r"^\s+([^:]+):\s+(.*)$", line)
        if match:
            fields = re.sub(r"\([^)]*\)", "", match[2]).split()
            result[match[1].strip()] = dict(zip(
                ("user_s", "system_s", "wall_s"), map(float, fields[:3])))
    if "TOTAL" not in result:
        raise ValueError("Missing GCC total")
    return result


def perf_rows(text):
    if "# Total Lost Samples: 0" not in text:
        raise ValueError("The perf report must establish zero lost samples")
    result = []
    for line in text.splitlines():
        columns = [item.strip() for item in line.split(";")]
        if len(columns) > 1 and columns[0].endswith("%"):
            result.append({
                "reported_pct": float(columns[0][:-1]),
                "samples": int(columns[1]), "period": int(columns[2]),
                "comm": columns[3], "dso": columns[4], "symbol": columns[5],
            })
    if not result:
        raise ValueError("The perf report contains no samples")
    return result


def bootstrap_pairs(records, first, second):
    rows = {name: {r["repetition"]: r["wall_s"] for r in records if r["case"] == name}
            for name in (first, second)}
    if rows[first].keys() != rows[second].keys():
        raise ValueError("Paired cases do not have the same repetitions")
    pairs = [(rows[first][i], rows[second][i]) for i in sorted(rows[first])]
    rng = random.Random(20260930)
    delta, ratio = [], []
    for _ in range(10000):
        sample = rng.choices(pairs, k=len(pairs))
        a = statistics.median(p[0] for p in sample)
        b = statistics.median(p[1] for p in sample)
        delta.append(a - b)
        ratio.append(b / a)
    delta.sort()
    ratio.sort()
    a = statistics.median(p[0] for p in pairs)
    b = statistics.median(p[1] for p in pairs)
    return {"first": first, "second": second, "median_difference_s": a - b,
            "second_over_first": b / a,
            "difference_percentile_95_ci_s": [delta[250], delta[9749]],
            "ratio_percentile_95_ci": [ratio[250], ratio[9749]],
            "bootstrap_draws": 10000, "seed": 20260930}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path(".profile-cache"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "reports").mkdir()
    baseline = args.cache / "check-runs"
    phases = args.cache / "phase-runs"
    samples = args.cache / "samples"
    records = read(baseline / "measurements.json")
    validate_collection(records, read(baseline / "environment.json"), "timing")
    phase_measurements = read(phases / "measurements.json")
    validate_collection(phase_measurements, read(phases / "environment.json"), "phase")
    save(args.output / "timings.json", [
        {k: v for k, v in row.items() if k not in ("command", "stderr")}
        for row in records])
    for source, target in [(baseline / "summary.json", "timing-summary.json"),
                           (baseline / "environment.json", "environment.json")]:
        shutil.copyfile(source, args.output / target)
    tool_root = args.cache / "tools/measureme"
    revision = subprocess.check_output(
        ["git", "-C", str(tool_root), "rev-parse", "HEAD"], text=True).strip()
    if revision != "5ac839c602b59eee9c908b3b35b6d6c0cd1c42f7":
        raise ValueError(f"Unexpected measureme revision: {revision}")
    tool = tool_root / "target/release/summarize"
    save(args.output / "measureme.json", {
        "source_url": "https://github.com/rust-lang/measureme",
        "source_revision": revision, "version": "12.0.3",
        "cargo_lock_sha256": hashlib.sha256((tool_root / "Cargo.lock").read_bytes()).hexdigest(),
        "summarize_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(),
        "command": [str(tool), "summarize", "--json", "PROFILE.mm_profdata"],
    })
    controls = [bootstrap_pairs(records, first, second) for first, second in (
        ("json-client-clang++-20", "json-include-clang++-20"),
        ("json-client-g++", "json-include-g++"),
        ("regex-default-rustc", "regex-std-rustc"))]
    save(args.output / "controlled-variants.json", controls)

    summaries = []
    manifests = []
    for row in phase_measurements:
        entry = {k: v for k, v in row.items() if k != "stderr"}
        stderr = phases / Path(row["stderr"]).name
        text = stderr.read_text()
        if row["case"].endswith("rustc"):
            entry["phase_timers"] = [json.loads(line[6:]) for line in text.splitlines()
                                     if line.startswith("time: ")]
            if len(entry["phase_timers"]) != len(text.splitlines()):
                raise ValueError(f"Unexpected Rust diagnostic in {stderr}")
            self_dir = stderr.with_suffix(".self")
            raw_profiles = list(self_dir.glob("*.mm_profdata"))
            if len(raw_profiles) != 1:
                raise ValueError(f"Expected one self profile in {self_dir}")
            raw = raw_profiles[0]
            analyzer = args.cache / "tools/measureme/target/release/summarize"
            subprocess.run([str(analyzer), "summarize", "--json", str(raw)], check=True,
                           capture_output=True, text=True)
            summary = read(raw.with_suffix(".json"))
            entry["query_self_times"] = sorted([
                {"label": r["label"], "self_s": seconds(r["self_time"]),
                 "inclusive_s": seconds(r["time"]), "count": r["invocation_count"]}
                for r in summary["query_data"]], key=lambda r: -r["self_s"])
            entry["self_profile_thread_span_s"] = seconds(summary["total_time"])
            manifests.append(raw)
        elif "clang" in row["case"]:
            if text:
                raise ValueError(f"Unexpected Clang diagnostic in {stderr}")
            raw = stderr.with_suffix(".trace.json")
            entry["trace"] = analyze_trace(raw)
            manifests.append(raw)
        else:
            entry["gcc_timers"] = gcc_rows(text)
        if text:
            shutil.copyfile(stderr, args.output / "reports" / stderr.name)
        summaries.append(entry)
    save(args.output / "phase-profiles.json", summaries)

    sampled = []
    for run in read(samples / "runs.json"):
        text = (samples / f"{run['case']}.report.txt").read_text()
        rows = perf_rows(text)
        run.update(rows=rows, samples=sum(r["samples"] for r in rows),
                   total_period=sum(r["period"] for r in rows), lost_samples=0)
        sampled.append(run)
        manifests.append(samples / f"{run['case']}.data")
    save(args.output / "sampling-profiles.json", sampled)
    save(args.output / "raw-profile-hashes.json", [
        {"path": str(path), "bytes": path.stat().st_size,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in manifests])
    print(f"Saved {len(records)} timing runs, {len(summaries)} phase profiles, "
          f"and {len(sampled)} sampling profiles to {args.output}")


if __name__ == "__main__":
    main()
