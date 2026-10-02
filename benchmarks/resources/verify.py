#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build and verify the frozen direct and callback SQLite baselines."""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPECTED_SQLITE = {
    "sqlite3.c": "e3f5d6901e7492af4a1fc8c4d745cae84c264942524c3fbfc02b82a5ca8818c8",
    "sqlite3.h": "abd1514e0351f79393d1be882830afdb40a8099e8257f311f0bfdf8486f11bea",
}
STRICT = [
    "-std=c99",
    "-pedantic-errors",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Wstrict-prototypes",
    "-Wmissing-prototypes",
    "-Wshadow",
    "-Wvla",
]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=Path(".profile-cache/resources-baseline"))
    parser.add_argument("--sqlite", type=Path, default=Path(".profile-cache/sources"))
    parser.add_argument(
        "--output", type=Path, default=Path("build/benchmarks/resources/baseline.json")
    )
    args = parser.parse_args()
    os.chdir(ROOT)
    args.work.mkdir(parents=True, exist_ok=True)
    for name, expected in EXPECTED_SQLITE.items():
        actual = sha(args.sqlite / name)
        if actual != expected:
            raise SystemExit(f"SQLite source hash mismatch: {name}: {actual}")
    report = {
        "schema_version": 1,
        "performance_samples": False,
        "sqlite_version": "3.50.4",
        "sqlite_archive_url": "https://sqlite.org/2025/sqlite-amalgamation-3500400.zip",
        "sqlite_archive_sha256": "1d3049dd0f830a025a53105fc79fd2ab9431aea99e137809d064d8ee8356b032",
        "sqlite_source_sha256": EXPECTED_SQLITE,
        "compiler": subprocess.check_output(["gcc", "--version"], text=True).splitlines()[0],
        "commands": [],
        "cases": [],
    }

    def command(argv, expected=0, stdout=subprocess.PIPE):
        argv = list(map(str, argv))
        result = subprocess.run(argv, stdout=stdout, stderr=subprocess.PIPE, timeout=120)
        record = {
            "command": argv,
            "status": result.returncode,
            "stdout": (result.stdout or b"").decode(),
            "stderr": result.stderr.decode(),
        }
        report["commands"].append(record)
        if result.returncode != expected:
            raise AssertionError(record)
        return result

    obj = args.work / "sqlite3.o"
    command(["gcc", "-O2", "-g0", "-c", args.sqlite / "sqlite3.c", "-o", obj])
    for name in ("direct", "callbacks", "contracts"):
        command(
            [
                "gcc",
                *STRICT,
                "-O2",
                "-g0",
                "-I" + str(args.sqlite),
                Path("benchmarks/resources") / (name + ".c"),
                obj,
                "-ldl",
                "-lm",
                "-pthread",
                "-o",
                args.work / name,
            ]
        )

    def database(name, script, values=()):
        path = args.work / (name + ".db")
        path.unlink(missing_ok=True)
        with sqlite3.connect(path) as connection:
            connection.executescript(script)
            if values:
                connection.executemany("INSERT INTO input(seq,value) VALUES (?,?)", values)
        return path

    values = [
        (1, b"\0\xff"),
        (2, "Hi\0x"),
        (3, None),
        (4, b""),
        (5, ""),
        (6, 42),
        (7, 1.5),
        (8, "\u00e9"),
    ]
    normal = database("normal", "CREATE TABLE input(seq INTEGER PRIMARY KEY,value);", values)
    empty = database("empty", "CREATE TABLE input(seq INTEGER PRIMARY KEY,value);")
    missing_table = database("missing-table", "CREATE TABLE other(value);")
    step_failure = database(
        "step-failure", "CREATE VIEW input AS SELECT 1 AS seq, abs(-9223372036854775808) AS value;"
    )
    missing_path = args.work / "missing-parent" / "input.db"
    if missing_path.exists():
        raise SystemExit("The missing-path fixture unexpectedly exists.")
    expected_output = b"B 00ff\nT 48690078\nN\nB \nT \nI 3432\nR 312e35\nT c3a9\nrows 8\n"
    cases = [
        ("values", [normal], 0, expected_output, b""),
        ("empty-table", [empty], 0, b"rows 0\n", b""),
        ("open-failure", [missing_path], 1, b"", b"error 14 0 0\n"),
        ("prepare-failure", [missing_table], 1, b"", b"error 1 0 0\n"),
        ("step-and-finalize-failure", [step_failure], 1, b"", b"error 1 1 0\n"),
        ("usage", [], 2, b"", b"usage: sqlite-reader DATABASE\n"),
    ]
    for name, arguments, status, output, error in cases:
        for implementation in ("direct", "callbacks"):
            result = command([args.work / implementation, *arguments], expected=status)
            assert result.stdout == output and result.stderr == error, (
                name,
                implementation,
                result,
            )
        report["cases"].append(
            {
                "name": name,
                "status": status,
                "stdout": output.decode(),
                "stderr": error.decode(),
                "implementations": ["direct", "callbacks"],
            }
        )
    for implementation in ("direct", "callbacks"):
        with open("/dev/full", "wb") as full:
            result = command([args.work / implementation, normal], expected=1, stdout=full)
        assert result.stderr == b"error 10 0 0\n", result
    report["cases"].append(
        {
            "name": "output-failure",
            "status": 1,
            "stdout_device": "/dev/full",
            "stderr": "error 10 0 0\n",
            "implementations": ["direct", "callbacks"],
        }
    )
    contracts = command([args.work / "contracts", missing_path])
    assert contracts.stderr == b"", contracts.stderr
    report["contract_result"] = contracts.stdout.decode().strip()
    report["application_process_checks"] = 2 * (len(cases) + 1)
    report["source_sha256"] = {
        str(path): sha(path)
        for path in sorted(Path("benchmarks/resources").glob("*"))
        if path.suffix in (".c", ".h", ".py")
    }
    report["binary_sha256"] = {
        str(args.work / name): sha(args.work / name)
        for name in ("direct", "callbacks", "contracts", "sqlite3.o")
    }
    report["complete"] = True
    text = json.dumps(report, indent=2) + "\n"
    text = text.replace(str(ROOT), "@REPO@")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"SQLite baselines: {report['application_process_checks']} process checks passed")
    print(report["contract_result"])
    print(args.output)


if __name__ == "__main__":
    main()
