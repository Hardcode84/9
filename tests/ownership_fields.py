#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check embedded cleanup, heap value destruction, and payload projection."""

import argparse
import tempfile
from pathlib import Path

from memory import command
from ownership import rejected, replace
from ownership_runtime import check_runtime
from resource_memory import execute

ROOT = Path(__file__).resolve().parents[1]
TUTORIAL = ROOT / "examples/intrusive"


def rejection_cases(source):
    return {
        "missing-value-destruction": replace(source, "drop *node;", ""),
        "double-value-destruction": replace(source, "drop *node;", "drop *node; drop *node;"),
        "read-destroyed-value": replace(
            source, "drop *node;", "drop *node; emit((*node).value as i32);"
        ),
        "partially-initialized-value": replace(source, "(*node).second=payload_new(66i64);", ""),
        "still-linked-value": replace(source, "unlink(&(*node).ready);", ""),
        "copied-field-owner": replace(
            source, "drop owner;", "var copy:Payload=(*owner.node).first; drop owner;"
        ),
        "partial-field-drop": replace(
            source, "drop owner;", "drop (*owner.node).first; drop owner;"
        ),
        "field-overwrite": replace(
            source, "drop owner;", "(*owner.node).first=payload_new(67i64); drop owner;"
        ),
        "borrowed-field-drop": replace(
            source, "drop owner;", "var held:read Payload=read (*owner.node).first; drop owner;"
        ),
        "borrowed-scalar-drop": replace(
            source, "drop owner;", "var held:read i64=read (*owner.node).value; drop owner;"
        ),
        "projected-field-move": replace(
            source,
            "if (*node).first.data!=null(*Data)",
            "var stolen:*Data=move (*node).first.data; if (*node).first.data!=null(*Data)",
        ),
        "projected-field-write": replace(
            source,
            "if (*(*node).first.data).value!=65i64",
            "(*(*node).first.data).value=7i64; if (*(*node).first.data).value!=65i64",
        ),
        "projected-field-loan-alias": replace(
            source.replace("read Graph {", "edit Graph {"),
            "var node:*Node=parent(Node.ready,cursor);",
            "var node:*Node=parent(Node.ready,cursor); var held:read Payload=read (*node).first; edit Graph {(*(*owner.node).first.data).value=7i64;}",
        ),
        "conditional-destruction": replace(
            source, "drop *node;", "if (*node).value==7i64 {drop *node;}"
        ),
        "partial-construction-overwrite": replace(
            source,
            "(*node).first=payload_new(65i64);",
            "(*node).first.data=null(*Data); (*node).first=payload_new(65i64);",
        ),
    }


def run(build, directory, sanitize):
    links, source = TUTORIAL / "links.crs", TUTORIAL / "fields.crs"
    compiler = build / "crust-ownership-test"
    generated, symbols = directory / "fields.c", directory / "fields.rsp"
    command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, links, source])
    execute(generated, symbols, directory, "fields", sanitize, b"BABAOK\n")
    command([build / "crust-ownership-erasure", "--check", links, source])
    command([build / "crust", TUTORIAL / "fields-main.crs", "--check", links, source])
    check_runtime(
        build,
        directory,
        ROOT,
        sanitize,
        source,
        (b"BABAOK\n", b"", b"B", b"A", b"BA", b"BAB", b"BAA"),
    )
    count = rejected(compiler, directory, rejection_cases(source.read_text()), "fields", [links])
    print(
        f"embedded ownership: native cleanup order, erasure, root, 6 allocation failures, and {count} rejections passed"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-fields-", dir=args.build) as directory:
        run(args.build.resolve(), Path(directory).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
