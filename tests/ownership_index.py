#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check one-way retention, retirement, source-free imports, and native reuse."""

import argparse
import tempfile
from pathlib import Path

from ownership_imports import import_arguments, publish, unpack
from ownership_runtime import check_runtime
from ownership_support import ROOT, command, execute

TUTORIAL = ROOT / "examples/ownership-index"
SETUP = (
    "var index:Index=index_new();index_insert(mut index,1i64,41i64);"
    "index_alias(mut index,10i64,1i64);"
)
SELECT = "var selected:Selection=index_select(read index,10i64);"
REMOVE = "index_remove(mut index,1i64);"
FORWARD = (
    "fn remove(index:mut Index)->unit access(reclaim,Symbols) {" "index_remove(mut index,1i64);}"
)


def body(text):
    return "fn main(argc:i32,argv:**u8)->i32 {domain Symbols {" + text + "}return 0i32;}"


def rejects():
    return {
        "remove-during-read": (
            body(SETUP + "read Symbols {" + SELECT + REMOVE + "}"),
            "stronger domain authority",
        ),
        "remove-during-edit": (
            body(SETUP + "edit Symbols {" + SELECT + REMOVE + "}"),
            "stronger domain authority",
        ),
        "forwarded-remove-during-read": (
            FORWARD + body(SETUP + "read Symbols {remove(mut index);}"),
            "stronger domain authority",
        ),
        "selection-escape-and-reuse": (
            body(
                SETUP
                + "var saved:Selection=uninit;read Symbols {"
                + SELECT
                + "saved=move selected;}"
                + REMOVE
                + "index_insert(mut index,1i64,99i64);"
            ),
            "outlive its access",
        ),
        "payload-escape": (
            "record View {value:read i64;}"
            + body(
                SETUP
                + "var saved:View=uninit;read Symbols {"
                + SELECT
                + "var value:read i64=selection_value(read selected);"
                + "saved=make View{value:read value};}"
                + REMOVE
            ),
            "outlive",
        ),
        "index-cleanup-during-read": (
            body(SETUP + "read Symbols {drop index;}"),
            "stronger domain authority",
        ),
        "implicit-index-cleanup": (
            body(SETUP + "read Symbols {var moved:Index=move index;if argc>0i32 {return 0i32;}}"),
            "stronger domain authority",
        ),
        "payload-versus-rebind": (
            body(
                SETUP
                + "edit Symbols {"
                + SELECT
                + "var value:read i64=selection_value(read selected);"
                + "index_bind(mut index,10i64,1i64);}"
            ),
            "active domain loan",
        ),
        "private-target": (
            body(SETUP + "read Symbols {" + SELECT + "var pointer:*Symbol=selected.target;}"),
            "private",
        ),
        "raw-result": (
            body(SETUP + "var pointer:*Symbol=symbol_find(read index,1i64);"),
            "pointer results require",
        ),
        "copy-index": (body(SETUP + "var copy:Index=index;"), "explicit move"),
        "unreported-observer": ("record Observer {target:*Symbol;}", "persistent pointers"),
        "drop-borrowed-handle": (
            "fn bad(index:mut Index)->unit access(reclaim,Symbols) {drop index;}",
            "cannot drop a borrowed value",
        ),
        "retire-borrowed-handle": (
            "fn bad(index:mut Index)->unit access(reclaim,Symbols) {index_drop(mut index);}",
            "destructor",
        ),
        "direct-destructor": (body(SETUP + "index_drop(mut index);"), "destructor"),
        "deferred-destructor": (body(SETUP + "defer index_drop(mut index);"), "destructor"),
        "double-mutable-handle": (
            body(SETUP + "var first:mut Index=mut index;var second:mut Index=mut index;"),
            "active",
        ),
        "drop-with-handle-loan": (
            body(SETUP + "var borrowed:read Index=read index;drop index;"),
            "active",
        ),
    }


def payload_rejects():
    payload = "var value:read i64=index_payload(read index);"
    return {
        "payload-from-owner": (
            body(
                SETUP + "var other:Index=index_new();" + payload + "index_remove(mut other,1i64);"
            ),
            "active domain loan",
        ),
        "payload-from-borrowed-owner": (
            "fn bad(index:read Index,other:mut Index)->unit access(reclaim,Symbols) {"
            + payload
            + "index_remove(mut other,1i64);}",
            "active domain loan",
        ),
        "opaque-interior-owner": (
            body(SETUP + "var view:mut Index=index_view(mut index);remove(mut view);"),
            "active domain loan",
        ),
        "deferred-remove-with-payload": (
            body(SETUP + payload + "defer remove(mut index);"),
            "active",
        ),
    }


def check_rejections(build, directory, provider, cases):
    for name, (source, diagnostic) in cases.items():
        path = directory / f"{name}.crs"
        path.write_text(source)
        result = command(
            [build / "crust-ownership-test", "trusted", provider, "--library", "--check", path],
            expected=1,
        )
        assert diagnostic in result.stderr.decode(), (name, result.stderr)


def bodyless(build, directory):
    trusted = directory / "provider.crs"
    trusted.write_bytes((TUTORIAL / "provider.crs").read_bytes())
    helpers, main = (TUTORIAL / "program.crs").read_text().split("fn main(", 1)
    library, client = directory / "helpers.crs", directory / "client.crs"
    library.write_text(helpers)
    client.write_text("fn main(" + main)
    driver = build / "crust-ownership-import-test"
    cache = directory / "cache"
    cache.mkdir()
    receipt = publish(driver, cache, [library], "trusted", str(trusted))
    _, _, interface = unpack(receipt[0].read_bytes())
    assert "access(reclaim, Symbols)" in interface and "from selection" in interface
    assert "scoped" in interface and "opaque" in interface
    assert "while " not in interface and "return " not in interface
    trusted.unlink()
    library.unlink()
    binary = directory / "imported"
    args = import_arguments(driver, cache, receipt, client, binary, trusted=True)
    command(args)
    assert command([binary]).stdout == b"OK\n"
    for text, diagnostic in (
        ("read Symbols {remove_required(mut index,1i64);}", b"stronger domain authority"),
        ("index_drop(mut index);", b"destructor"),
        ("defer index_drop(mut index);", b"destructor"),
    ):
        client.write_text(body(SETUP + text))
        result = command(args, expected=1)
        assert diagnostic in result.stderr, result.stderr


def check_forwarding(build, directory, sanitize):
    source = directory / "forwarding.crs"
    source.write_text(
        FORWARD
        + body(
            SETUP
            + "{var handle:mut Index=mut index;remove(mut handle);}"
            + "index_insert(mut index,1i64,42i64);{defer remove(mut index);}"
            + "read Symbols {"
            + SELECT
            + "var present:bool=selection_present(read selected);if present {trap;}}"
        )
    )
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [
            build / "crust-ownership-test",
            "trusted",
            TUTORIAL / "provider.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            source,
        ]
    )
    command([build / "crust-ownership-erasure", "trusted", TUTORIAL / "provider.crs", source])
    execute(generated, symbols, directory, "forwarding", sanitize, b"")


def run(build, directory, sanitize):
    provider, source = TUTORIAL / "provider.crs", TUTORIAL / "program.crs"
    generated, symbols = directory / "index.c", directory / "index.rsp"
    command(
        [
            build / "crust",
            TUTORIAL / "main.crs",
            "--emit-c",
            "--symbols",
            symbols,
            "-o",
            generated,
            source,
        ]
    )
    command([build / "crust-ownership-erasure", "trusted", provider, source])
    execute(generated, symbols, directory, "index", sanitize, b"OK\n")
    check_runtime(build, directory, ROOT, sanitize, source_path=provider, client_path=source)
    bodyless(build, directory)
    check_forwarding(build, directory, sanitize)
    cases = rejects()
    check_rejections(build, directory, provider, cases)
    projected = directory / "projected.crs"
    projected.write_text(
        provider.read_text()
        + FORWARD
        + "fn index_payload(index:read Index)->read i64 access(read,Symbols) from index {"
        "if index.symbols==null(*Symbol) {trap;}return read (*index.symbols).value;}"
        "fn index_view(index:mut Index)->mut Index access(edit,Symbols) from index {return mut index;}"
    )
    check_rejections(build, directory, projected, payload_rejects())
    print(
        f"one-way index: O0/O2, erasure, address reuse, source-free import, {len(cases) + len(payload_rejects()) + 3} rejections"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-index-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary), args.sanitize)


if __name__ == "__main__":
    main()
