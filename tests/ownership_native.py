#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check owned native values independently of their ABI representation."""

import argparse
import os
import tempfile
from pathlib import Path

from ownership_imports import command as import_command
from ownership_imports import import_arguments, unpack
from ownership_support import command, execute, rejected

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "examples/ownership-basics/handles.crs"


def rejects(provider):
    start = "var f:File=open_file();if f.handle == -1i32 {trap;}"
    stream = "var p:*u8=acquire_stream();if p==null(*u8) {return;}"

    def body(text, declarations=""):
        return provider + declarations + "fn bad()->unit {" + text + "}"

    cases = {
        "copy-native": (body(start + "var raw:i32=f.handle;"), "explicit move"),
        "forge-native": (body("var f:File=make File{handle:3i32};"), "acquisition"),
        "forge-empty": (body("var f:File=make File{handle:-1i32};"), "acquisition"),
        "unchecked": (body("var f:File=open_file();query_fd(f.handle);"), "successful acquisition"),
        "unguarded-close": (
            body("var p:i32=acquire_fd(1i32);close_fd(move p);"),
            "successful acquisition",
        ),
        "copy-close": (body(start + "close_fd(f.handle);"), "explicit move"),
        "double-close": (
            body(start + "close_fd(move f.handle);close_fd(move f.handle);"),
            "has been moved",
        ),
        "use-closed": (
            body(start + "close_fd(move f.handle);query_fd(f.handle);"),
            "has been moved",
        ),
        "cast-native": (
            body(start + "var raw:usize=f.handle as usize;"),
            "declared resource effect",
        ),
        "native-arithmetic": (body(start + "var raw:i32=f.handle+0i32;"), "not arithmetic"),
        "native-scalar-call": (body(start + "put(f.handle);"), "declared resource effect"),
        "native-plain-call": (
            body(start + "plain(f.handle);", "fn plain(x:i32)->unit {}"),
            "declared resource effect",
        ),
        "native-return": (
            provider + "fn bad()->i32 {var p:i32=acquire_fd(1i32);return move p;}",
            "declared resource effect",
        ),
        "native-leak": (body("var p:i32=acquire_fd(1i32);"), "before its scope ends"),
        "unused-native": (body("acquire_fd(1i32);"), "unused resource"),
        "overwrite-native": (
            body("var p:i32=acquire_fd(1i32);p=acquire_fd(1i32);"),
            "overwrite a live owner",
        ),
        "borrow-bits": (body(start + "var p:read i32=read f.handle;"), "declared resource effect"),
        "opaque-deref": (body(stream + "var x:u8=*p;"), "declared resource effect"),
        "opaque-cast": (body(stream + "var x:*i32=p as *i32;"), "declared resource effect"),
        "opaque-free": (
            body(stream + "free(p);", 'extern fn free(p:*u8)->unit foreign(release)="free";'),
            "declared resource effect",
        ),
        "borrow-owner-drop": (body(start + "var v:read File=read f;drop f;"), "active"),
        "consume-shared": (
            provider
            + "fn bad(f:read File)->unit {if f.handle != -1i32 {close_fd(move f.handle);}}",
            "shared",
        ),
        "native-owner-branch": (
            body(start + "var q:i32=query_fd(f.handle);if q==0i32 {close_fd(move f.handle);}"),
            "owner consumption",
        ),
        "native-owner-loop": (
            body(start + "var i:i32=0i32;while i<2i32 {close_fd(move f.handle);i=i+1i32;}"),
            "initialized resource fields",
        ),
        "replacement-loop-validity": (
            body(
                start
                + "var i:i32=0i32;while i<2i32 {query_fd(f.handle);drop f;f=open_file();i=i+1i32;}"
            ),
            "successful acquisition",
        ),
        "mutable-call-validity": (
            body(
                start + "edit_file(mut f);query_fd(f.handle);", "fn edit_file(f:mut File)->unit {}"
            ),
            "successful acquisition",
        ),
        "missing-drop-consumption": (
            provider.replace("close_fd(move file.handle)", "query_fd(file.handle)"),
            "consume each owned field",
        ),
        "invalid-sentinel-type": (
            provider.replace("owns(handle = -1i32)", "owns(handle = 0u32)"),
            "field type",
        ),
        "invalid-sentinel-range": (
            provider.replace("owns(handle = -1i32)", "owns(handle = 2147483648i32)"),
            "representable integer",
        ),
        "invalid-sentinel-expression": (
            provider.replace("owns(handle = -1i32)", "owns(handle = 1i32+2i32)"),
            "literal",
        ),
        "effect-type-mismatch": (
            provider + 'extern fn bad()->u32 foreign(acquire File.handle)="bad";',
            "representation",
        ),
        "effect-absent-field": (
            provider + 'extern fn bad()->i32 foreign(acquire File.absent)="bad";',
            "owned value field",
        ),
        "effect-absent-parameter": (
            provider + 'extern fn bad(x:i32)->i32 foreign(read y:File.handle)="bad";',
            "no parameter",
        ),
        "effect-duplicate": (
            provider
            + 'extern fn bad(x:i32)->i32 foreign(read x:File.handle,move x:File.handle)="bad";',
            "duplicate native effect",
        ),
        "effect-result-duplicate": (
            provider
            + 'extern fn bad()->i32 foreign(acquire File.handle,acquire File.handle)="bad";',
            "duplicate native effect",
        ),
        "pointer-without-effect": (
            provider + 'extern fn bad()->*u8 foreign(read x:File.handle)="bad";',
            "no parameter",
        ),
    }
    second = "resource Other {handle:i32;} owns(handle = -1i32) drop other_drop;"
    second += 'extern fn other_close(x:i32)->i32 foreign(move x:Other.handle)="close";'
    second += (
        "fn other_drop(f:mut Other)->unit {if f.handle != -1i32 {other_close(move f.handle);}}"
    )
    cases["wrong-resource-kind"] = (
        body(start + "other_close(move f.handle);", second),
        "wrong resource kind",
    )
    cases["wrong-wrapper-kind"] = (
        body(start + "var other:Other=make Other{handle:move f.handle};", second),
        "resource kind",
    )
    both = (
        'extern fn both(x:i32,y:i32)->unit foreign(read x:File.handle,move y:File.handle)="both";'
    )
    cases["borrow-and-consume"] = (
        body(start + "both(f.handle,move f.handle);", both),
        "active payload loan",
    )
    conflict = both.replace("move y", "mut y")
    cases["overlapping-native-borrows"] = (
        body(start + "both(f.handle,f.handle);", conflict),
        "active payload loan",
    )
    cases["native-consume-invalid"] = (
        body("var p:i32=acquire_fd(-1i32);if p == -1i32 {close_fd(move p);}"),
        "successful acquisition",
    )
    cases["mutate-shared-native"] = (
        provider
        + "fn bad(s:read Stream)->unit {if s.handle != null(*u8) {put_stream(65i32,s.handle);}}",
        "shared loan",
    )
    cases["mutable-loop-validity"] = (
        body(
            start + "var i:i32=0i32;while i<2i32 {query_fd(f.handle);edit_file(mut f);i=i+1i32;}",
            "fn edit_file(f:mut File)->unit {}",
        ),
        "resource validity",
    )
    cases["opaque-after-consume"] = (
        body(stream + "close_stream(move p);var stale:bool=p==null(*u8);"),
        "has been moved",
    )
    cursor = provider.split("fn open_file(", 1)[0]
    cursor = "domain D(File);" + cursor.replace(
        "owns(handle = -1i32) drop", "owns(handle = -1i32) domain(D) drop"
    )
    cursor = cursor.replace(
        "fn file_drop(file: mut File) -> unit {",
        "fn file_drop(file: mut File) -> unit access(reclaim,D) {",
    )
    cursor += conflict + "fn bad(a:*File,b:*File)->unit access(edit,D) {"
    cursor += "if a!=null(*File) && b!=null(*File) && (*a).handle != -1i32 && (*b).handle != -1i32 {both((*a).handle,(*b).handle);}}"
    cases["aliasing-cursor-native-borrows"] = (cursor, "active payload loan")
    return cases


def native(build, directory, source, output, sanitize, environment):
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    import_command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source],
        env=environment,
    )
    import_command([build / "crust-ownership-erasure", source], env=environment)
    execute(generated, symbols, directory, source.stem, sanitize, output)


def bodyless(build, directory, source, environment):
    provider, main = source.read_text().split("fn main(", 1)
    library, client = directory / "provider.crs", directory / "client.crs"
    library.write_text(provider)
    client.write_text("fn main(" + main)
    driver = build / "crust-ownership-import-test"
    cache = directory / "cache"
    cache.mkdir()
    result = import_command([driver, "publish", cache, library], env=environment)
    artifact, digest = result.stdout.splitlines()
    receipt = Path(artifact), digest
    _, _, interface = unpack(receipt[0].read_bytes())
    assert "owns(handle = -1i32)" in interface
    assert "foreign(read fd: File.handle, acquire File.handle)" in interface
    assert "var " not in interface and "return " not in interface
    library.unlink()
    output = directory / "client"
    import_command(import_arguments(driver, cache, receipt, client, output), env=environment)
    assert command([output]).stdout == b"OK\nSFF"
    client.write_text(
        "fn main(argc:i32,argv:**u8)->i32 {var f:File=open_file();var forged:i32=f.handle;return 0i32;}"
    )
    result = import_command(
        import_arguments(driver, cache, receipt, client, output), env=environment, success=False
    )
    assert "explicit move" in result.stderr, result.stderr


def run(build, directory, sanitize):
    environment = dict(os.environ)
    source = directory / "handles.crs"
    source.write_text(SOURCE.read_text())
    native(build, directory, source, b"OK\nSFF", sanitize, environment)
    bodyless(build, directory, source, environment)
    provider = source.read_text().split("fn main(", 1)[0]
    loop = directory / "loop.crs"
    loop.write_text(
        provider
        + "fn main(argc:i32,argv:**u8)->i32 {var i:i32=0i32;while i<3i32 {var f:File=open_file();if f.handle==-1i32 {trap;}i=i+1i32;}return 0i32;}"
    )
    native(build, directory, loop, b"FFF", sanitize, environment)
    loop.write_text(
        provider + "fn main(argc:i32,argv:**u8)->i32 {var f:File=open_file();var i:i32=0i32;"
        "while i<3i32 {drop f;f=open_file();if f.handle==-1i32 {trap;}i=i+1i32;}return 0i32;}"
    )
    native(build, directory, loop, b"FFFF", sanitize, environment)
    failed = directory / "failed.crs"
    failed.write_text(
        provider
        + "fn main(argc:i32,argv:**u8)->i32 {var raw:i32=acquire_fd(-1i32);if raw != -1i32 {close_fd(move raw);}return 0i32;}"
    )
    native(build, directory, failed, b"", sanitize, environment)
    composite = directory / "composite.crs"
    composite.write_text(
        provider + "record Pair {stream:Stream;file:File;} "
        "fn main(argc:i32,argv:**u8)->i32 {var f:File=open_file();if f.handle==-1i32 {trap;}"
        "var p:*u8=acquire_stream();if p==null(*u8) {trap;}"
        "var s:Stream=make Stream{handle:move p};var pair:Pair=make Pair{stream:move s,file:move f};"
        "var next:Pair=move pair;return 0i32;}"
    )
    native(build, directory, composite, b"FS", sanitize, environment)
    embedded = directory / "embedded.crs"
    embedded.write_text(
        provider + "domain D(Holder);resource Holder {file:File;} domain(D) drop holder_drop;"
        "fn holder_drop(h:mut Holder)->unit access(reclaim,D) {}"
        "fn main(argc:i32,argv:**u8)->i32 access(reclaim,D) {var f:File=open_file();if f.handle==-1i32 {trap;}"
        "var h:Holder=make Holder{file:move f};return 0i32;}"
    )
    native(build, directory, embedded, b"F", sanitize, environment)
    scalar_contracts(build, directory, environment)
    cases = rejects(provider)
    rejected(build / "crust-ownership-test", directory, cases)
    print(f"native resources: O0/O2, erasure, bodyless import, no solver, {len(cases)} rejections")


def scalar_contracts(build, directory, environment):
    # Test the same lifecycle on each scalar ABI type, without inventing native bodies.
    for kind in ("i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "isize", "usize"):
        source = directory / f"scalar-{kind}.crs"
        source.write_text(
            f"resource Key {{value:{kind};}} owns(value=0{kind}) drop destroy;"
            f'extern fn create()->{kind} foreign(acquire Key.value)="create";'
            f'extern fn consume(value:{kind})->unit foreign(move value:Key.value)="consume";'
            f"fn destroy(key:mut Key)->unit {{if key.value!=0{kind} {{consume(move key.value);}}}}"
            f"fn obtain()->Key {{var value:{kind}=create();return make Key{{value:move value}};}}"
        )
        import_command(
            [build / "crust-ownership-test", "--library", "--check", source], env=environment
        )
    text = source.read_text().replace("owns(value=0usize)", "owns(value)")
    source.write_text(
        text.replace("if key.value!=0usize {consume(move key.value);}", "consume(move key.value);")
    )
    import_command(
        [build / "crust-ownership-test", "--library", "--check", source], env=environment
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ownership-native-", dir=args.build) as temporary:
        run(args.build.resolve(), Path(temporary).resolve(), args.sanitize)


if __name__ == "__main__":
    main()
