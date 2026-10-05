# SPDX-License-Identifier: Apache-2.0
"""Build an isolated common-header and overlapping-payload expression layout."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMMON = ("loc", "type", "kind", "place", "writable")
SLOTS = (
    ("bytes", "right", "symbol", "syntax_type", "literal_type"),
    ("byte_count", "inits", "integer", "left", "name"),
    ("args", "field_name", "op"),
    ("arg_count", "field"),
)
# Fields that can coexist in each seed expression kind, in enum order.
KINDS = (
    ("NAME", "name symbol"),
    ("INTEGER", "integer literal_type"),
    ("BOOL", "integer"),
    ("STRING", "bytes byte_count"),
    ("GROUP", "left"),
    ("UNARY", "left op"),
    ("BINARY", "left right op"),
    ("CALL", "left args arg_count"),
    ("INDEX", "left right"),
    ("FIELD", "left field_name field"),
    ("CAST", "left syntax_type"),
    ("RECORD", "syntax_type inits"),
    ("ARRAY", "syntax_type args arg_count"),
    ("NULL", "syntax_type"),
    ("SIZEOF", "syntax_type integer"),
    ("ALIGNOF", "syntax_type integer"),
    ("OFFSETOF", "syntax_type field_name field integer"),
)


def command(arguments, cwd=None):
    result = subprocess.run(arguments, cwd=cwd, capture_output=True, timeout=180)
    if result.returncode:
        raise RuntimeError(
            f"{arguments}: status {result.returncode}\n{result.stdout.decode()}{result.stderr.decode()}"
        )
    return result.stdout


def nodes(tree):
    yield tree
    for child in tree.get("inner", []):
        yield from nodes(child)


def member_paths():
    paths = {name: f"header.{name}" for name in COMMON}
    for index, fields in enumerate(SLOTS):
        for name in fields:
            paths[name] = f"payload.slot{index}.{name}"
    for kind, fields in KINDS:
        slots = [paths[name].rsplit(".", 1)[0] for name in fields.split()]
        if len(slots) != len(set(slots)):
            raise ValueError(f"overlapping live fields in {kind}")
    return paths


def rewrite_members(source, include, clang, paths):
    tree = json.loads(
        command(
            [
                clang,
                "-std=c99",
                "-I",
                str(include),
                "-Xclang",
                "-ast-dump=json",
                "-fsyntax-only",
                str(source),
            ]
        )
    )
    fields = {}
    for node in nodes(tree):
        if node.get("kind") == "RecordDecl" and node.get("name") == "CrustExpr":
            fields.update(
                {
                    field["id"]: field["name"]
                    for field in node.get("inner", [])
                    if field["kind"] == "FieldDecl"
                }
            )
    text = source.read_text()
    edits = {}
    for node in nodes(tree):
        if node.get("kind") != "MemberExpr" or node.get("referencedMemberDecl") not in fields:
            continue
        name = fields[node["referencedMemberDecl"]]
        location = node["range"]["end"]
        if "offset" not in location or "includedFrom" in location:
            raise ValueError(f"nonlocal or macro member reference in {source}: {node}")
        start = location["offset"]
        end = start + location["tokLen"]
        if text[start:end] != name:
            raise ValueError(f"member location mismatch in {source}: {name}")
        edits[start] = (end, paths[name])
    for start, (end, replacement) in sorted(edits.items(), reverse=True):
        text = text[:start] + replacement + text[end:]
    return text, len(edits)


def compact_header(header, paths):
    source = header.read_text()
    match = re.search(r"struct CrustExpr \{(.*?)\n\};", source, re.S)
    declarations = {}
    for declaration in match[1].split(";"):
        declaration = declaration.strip()
        if declaration:
            name = re.search(r"(\w+)$", declaration)[1]
            declarations[name] = declaration + ";"
    if declarations.keys() != paths.keys():
        raise ValueError("CrustExpr fields changed; review payload membership")
    enum = re.search(r"typedef enum \{([^{}]*CRUST_E_NAME.*?)\} CrustExprKind;", source, re.S)[1]
    names = re.findall(r"CRUST_E_(\w+)", enum)
    if names != [kind for kind, _fields in KINDS] + ["END"]:
        raise ValueError("expression kinds changed; review payload membership")
    common = "\n".join("    " + declarations[name] for name in COMMON)
    slots = []
    for index, fields in enumerate(SLOTS):
        members = "\n".join("        " + declarations[name] for name in fields)
        slots.append(f"    union {{\n{members}\n    }} slot{index};")
    replacement = (
        f"typedef struct {{\n{common}\n}} ExperimentExprHeader;\n\n"
        + "typedef struct {\n"
        + "\n".join(slots)
        + "\n} ExperimentExprPayload;\n\n"
        + "struct CrustExpr {\n    ExperimentExprHeader header;\n    ExperimentExprPayload payload;\n};"
    )
    return source[: match.start()] + replacement + source[match.end() :]


def prototype(snapshot, clang):
    paths = member_paths()
    header = snapshot / "include/crust0.h"
    pending = {}
    counts = {}
    for name in ("src/core.c", "src/read.c", "src/check.c", "driver.c"):
        path = snapshot / name
        pending[path], counts[name] = rewrite_members(path, header.parent, clang, paths)
    new_header = compact_header(header, paths)
    for path, contents in pending.items():
        path.write_text(contents)
    header.write_text(new_header)
    command(["python3", "tools/amalgamate.py"], cwd=snapshot)
    return counts
