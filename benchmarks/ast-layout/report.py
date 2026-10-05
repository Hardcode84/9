# SPDX-License-Identifier: Apache-2.0
"""Describe node bytes and test the stage boundary of a captured prototype."""

import json
import re
import subprocess

from layout import COMMON

ENUMS = {
    "CrustTypeSyntax": ("CrustTypeKind", "CRUST_T_"),
    "CrustExpr": ("CrustExprKind", "CRUST_E_"),
    "CrustStmt": ("CrustStmtKind", "CRUST_S_"),
    "CrustDecl": ("CrustDeclKind", "CRUST_D_"),
}


def describe(histograms, header):
    source = re.sub(r"/\*.*?\*/", "", header.read_text(), flags=re.S)
    result = {}
    for workload, versions in histograms.items():
        result[workload] = {}
        for version, histogram in versions.items():
            families = {}
            for family, (enum, prefix) in ENUMS.items():
                body = re.search(r"typedef enum \{([^{}]*)\} " + enum + ";", source)[1]
                names = [
                    name for name in re.findall(prefix + r"\w+", body) if not name.endswith("_END")
                ]
                data = histogram[family]
                if len(names) != len(data["counts"]):
                    raise ValueError(f"kind histogram differs from header: {family}")
                families[family] = {
                    name: {"count": count, "bytes": count * data["node_bytes"]}
                    for name, count in zip(names, data["counts"], strict=True)
                }
            total = sum(kind["bytes"] for family in families.values() for kind in family.values())
            result[workload][version] = {
                "families": families,
                "four_family_bytes": total,
                "arena_bytes_outside_four_families": histogram["check_arena_bytes"] - total,
            }
    return result


def migration_probe(directory, baseline, candidate, paths):
    directory.mkdir()
    generated = subprocess.run(
        ["python3", "tools/api.py"], cwd=candidate, capture_output=True, timeout=30
    )
    (directory / "generator.txt").write_bytes(generated.stdout + generated.stderr)
    # A seed record with the candidate's header and payload size exposes the
    # source-level field boundary even if the generator learns union layouts.
    source = paths[0].read_text()
    match = re.search(r"record CrustExpr \{(.*?)\n\}", source, re.S)
    members = {
        field.split(":", 1)[0].strip(): field.strip() + ";"
        for field in match[1].split(";")
        if field.strip()
    }
    common = "\n".join(members[name] for name in COMMON)
    replacement = (
        f"record CrustPackedExprHeader {{\n{common}\n}}\n"
        "record CrustExpr {header:CrustPackedExprHeader;payload:[usize;4];}"
    )
    changed = directory / "nested-api.crs"
    changed.write_text(source[: match.start()] + replacement + source[match.end() :])
    args = [str(baseline), str(changed), *map(str, paths[1:])]
    client = subprocess.run(args, capture_output=True, timeout=30)
    (directory / "client.txt").write_bytes(client.stdout + client.stderr)
    result = {
        "generator_exit": generated.returncode,
        "client_exit": client.returncode,
        "client_command": args,
        "passed": generated.returncode == 0 and client.returncode == 0,
    }
    (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
