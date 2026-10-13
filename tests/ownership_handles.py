#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Separate opaque handle storage loans from aliased interior loans."""

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import command, execute

PROVIDER = """
extern fn allocate(size:usize)->*u8 foreign(allocate)="malloc";
extern fn release(value:*u8)->unit foreign(release)="free";
domain Memory(Arena,Cursor);
record Cell{value:i64;}
resource Arena{cell:*Cell;} opaque drop arena_drop;
record Cursor{cell:*Cell;} opaque scoped;
fn arena_new()->Arena access(reclaim,Memory){
    var cell:*Cell=allocate(sizeof(Cell)) as *Cell;if cell==null(*Cell){trap;}
    cell->value=7i64;return make Arena{cell:cell};
}
fn arena_drop(arena:mut Arena)->unit access(reclaim,Memory){release(arena.cell as *u8);}
fn first(arena:read Arena)->Cursor access(read,Memory){return make Cursor{cell:arena.cell};}
fn set(arena:read Arena,value:i64)->unit access(edit,Memory){arena.cell->value=value;}
fn cursor_value(cursor:read Cursor)->read Cell access(read,Memory) from cursor{return read *cursor.cell;}
fn cursor_edit(cursor:mut Cursor)->mut Cell access(edit,Memory) from cursor{return mut *cursor.cell;}
fn reset(cursor:mut Cursor,arena:read Arena)->unit access(edit,Memory){cursor.cell=arena.cell;}
"""

HELPER = """
fn change(arena:read Arena,cursor:read Cursor)->i64 access(edit,Memory){
    set(read arena,9i64);var cell:read Cell=cursor_value(read cursor);return cell.value;
}
"""


def program(body):
    return (
        "fn main(argc:i32,argv:**u8)->i32{domain Memory{var arena:Arena=arena_new();"
        "edit Memory{var cursor:Cursor=first(read arena);" + body + "}}return 0i32;}"
    )


def rejections():
    return {
        "shared-interior": (
            program(
                "var cell:read Cell=cursor_value(read cursor);set(read arena,8i64);if cell.value!=7i64{trap;}"
            ),
            "active domain loan",
        ),
        "exclusive-interior": (
            program("var cell:mut Cell=cursor_edit(mut cursor);first(read arena);cell.value=8i64;"),
            "active domain loan",
        ),
        "aliased-handles": (
            program(
                "var other:Cursor=first(read arena);var cell:mut Cell=cursor_edit(mut cursor);"
                "var alias:read Cell=cursor_value(read other);cell.value=alias.value;"
            ),
            "active domain loan",
        ),
        "handle-storage": (
            program(
                "var held:read Cursor=read cursor;reset(mut cursor,read arena);cursor_value(read held);"
            ),
            "active",
        ),
        "reclaim": (program("drop arena;cursor_value(read cursor);"), "authority"),
        "escape": (
            "fn bad(arena:read Arena)->Cursor access(reclaim,Memory){"
            "edit Memory{var cursor:Cursor=first(read arena);return move cursor;}}",
            "scoped",
        ),
    }


def check_handles(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    provider = directory / "handle-provider.crs"
    provider.write_text(PROVIDER)
    accepted = HELPER + program(
        "if change(read arena,read cursor)!=9i64{trap;}"
        "{var cell:mut Cell=cursor_edit(mut cursor);cell.value=11i64;}"
        "var cell:read Cell=cursor_value(read cursor);if cell.value!=11i64{trap;}"
    )
    client = directory / "handle-client.crs"
    client.write_text(accepted)
    generated, symbols = client.with_suffix(".c"), client.with_suffix(".rsp")
    command(
        [compiler, "trusted", provider, "--emit", "--symbols", symbols, "-o", generated, client]
    )
    command([build / "crust-ownership-erasure", "trusted", provider, client])
    execute(generated, symbols, directory, "handles", sanitize, b"")
    for name, (source, diagnostic) in rejections().items():
        client.write_text(source)
        result = command(
            [compiler, "trusted", provider, "--library", "--check", client], expected=1
        )
        assert diagnostic in result.stderr.decode(), (name, result.stderr)
    cache = directory / "handle-cache"
    cache.mkdir()
    driver = build / "crust-ownership-import-test"
    helper = directory / "handle-library.crs"
    helper.write_text(HELPER)
    receipt = publish(driver, cache, [helper], "trusted", str(provider))
    helper.unlink()
    provider.unlink()
    output = directory / "handle-import"
    arguments = import_arguments(driver, cache, receipt, client, output, trusted=True)
    client.write_text(accepted.removeprefix(HELPER))
    import_command(arguments)
    command([output])
    for name, (source, diagnostic) in rejections().items():
        client.write_text(source + ("\n" + program("") if name == "escape" else ""))
        result = import_command(arguments, success=False)
        assert diagnostic in result.stderr, (name, result.stderr)
    print(
        "opaque handles: native runtime, erasure, independent imports, 6 rejected lifetime errors"
    )
