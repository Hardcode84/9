#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check owner identity at calls, deferred calls, and loop boundaries."""

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish
from ownership_support import command, execute, rejected

PROVIDER = """
domain Cells(Cell, CellOwner);
extern fn allocate(size:usize)->*u8 foreign(allocate)="malloc";
extern fn release(pointer:*u8)->unit foreign(release)="free";
record Cell {value:i64;}
resource CellOwner {cell:*Cell;} owns(cell:storage) drop cell_drop;
fn cell_new(value:i64)->CellOwner access(reclaim,Cells) {
    var cell:*Cell=allocate(sizeof(Cell)) as *Cell;
    if cell!=null(*Cell) {cell.value=value;}
    return make CellOwner{cell:move cell};
}
fn cell_drop(owner:mut CellOwner)->unit access(reclaim,Cells) {
    var cell:*Cell=move owner.cell;
    if cell!=null(*Cell) {release(cell as *u8);}
}
fn consume(owner:CellOwner)->unit access(reclaim,Cells) {}
fn identity(owner:CellOwner)->CellOwner access(edit,Cells) {return move owner;}
fn unchanged(owner:mut CellOwner)->unit access(edit,Cells) {}
fn preserves(owner:mut CellOwner)->unit access(edit,Cells) modifies() {}
fn extract(owner:mut CellOwner)->CellOwner access(edit,Cells) {
    var cell:*Cell=move owner.cell;
    owner.cell=null(*Cell);
    return make CellOwner{cell:move cell};
}
fn cell_view(owner:mut CellOwner)->read Cell access(edit,Cells) from owner.cell {
    if owner.cell==null(*Cell) {trap;}
    return read *owner.cell;
}
"""

START = (
    "var owner:CellOwner=cell_new(7i64);"
    "if owner.cell==null(*Cell) {return 0i32;}var raw:*Cell=owner.cell;"
)


def main(body):
    return "fn main(argc:i32,argv:**u8)->i32 access(reclaim,Cells){" + body + "return 0i32;}"


def good_cases():
    return {
        "returned-owner": START + "var returned:CellOwner=identity(move owner);"
        "if returned.cell!=null(*Cell) {if returned.cell.value!=7i64 {trap;}}",
        "refreshed-owner": START + "unchanged(mut owner);"
        "if owner.cell!=null(*Cell) {if owner.cell.value!=7i64 {trap;}}",
        "preserved-owner": START + "preserves(mut owner);if raw.value!=7i64 {trap;}",
        "expired-address-loan": START + "{var view:read CellOwner=read owner;"
        "var address:*CellOwner=&view;drop view;}var next:CellOwner=move owner;",
        "returned-view": START
        + "var view:read Cell=cell_view(mut owner);if view.value!=7i64 {trap;}",
        "deferred-owner": START + "{defer consume(move owner);if raw.value!=7i64 {trap;}}",
        "loop-owner": START
        + "var i:i32=0i32;while i<argc {drop owner;owner=cell_new(7i64);i=i+1i32;}"
        "if owner.cell!=null(*Cell) {if owner.cell.value!=7i64 {trap;}}",
        "null-owner": "var owner:CellOwner=make CellOwner{cell:null(*Cell)};"
        "var returned:CellOwner=identity(move owner);if returned.cell!=null(*Cell) {trap;}",
    }


def bad_cases():
    changes = {
        "consumed-owner": "consume(move owner);",
        "extracted-owner": "var extracted:CellOwner=extract(mut owner);drop extracted;",
        "returned-old-alias": "var returned:CellOwner=identity(move owner);",
        "mutable-old-alias": "unchanged(mut owner);",
        "deferred-consumption": "{defer consume(move owner);}",
        "deferred-mutation": "{defer unchanged(mut owner);}",
        "loop-old-alias": "var i:i32=0i32;"
        "while i<argc {drop owner;owner=cell_new(7i64);i=i+1i32;}",
    }
    cases = {
        name: (main(START + change + "var stale:i64=raw.value;"), "live non-null storage")
        for name, change in changes.items()
    }
    cases["addressed-owner-move"] = (
        main(START + "var address:*CellOwner=&owner;var next:CellOwner=move owner;"),
        "address-stable",
    )
    cases["addressed-inline-owner-move"] = (
        "record Part {value:i64;}resource Wrapper {part:Part;} drop wrapper_drop;"
        "fn wrapper_drop(wrapper:mut Wrapper)->unit {}"
        + main(
            "var wrapper:Wrapper=make Wrapper{part:make Part{value:7i64}};"
            "var address:*Part=&wrapper.part;var next:Wrapper=move wrapper;"
        ),
        "address-stable",
    )
    return cases


def check_argument_alias(build, directory):
    source = (
        "resource Value {n:i64;} drop dispose;fn dispose(v:mut Value)->unit {}"
        "fn use(v:Value,alias:read Value)->unit {drop v;if alias.n!=7i64 {trap;}}"
        "fn main(argc:i32,argv:**u8)->i32 {var value:Value=make Value{n:7i64};"
        "var raw:*Value=&value;use(move value,read *raw);return 0i32;}"
    )
    rejected(
        build / "crust-ownership-test",
        directory,
        {"boundary-argument-alias": (source, "address-stable")},
    )


def check_imports(build, directory):
    provider = directory / "boundary-provider.crs"
    provider.write_text(PROVIDER)
    cache = directory / "boundary-cache"
    cache.mkdir()
    driver = build / "crust-ownership-import-test"
    receipt = publish(driver, cache, [provider])
    provider.unlink()
    client = directory / "boundary-client.crs"
    output = directory / "boundary-client"
    arguments = import_arguments(driver, cache, receipt, client, output)
    for body in good_cases().values():
        client.write_text(main(body))
        import_command(arguments)
        command([output])
    for source, diagnostic in bad_cases().values():
        client.write_text(source)
        result = import_command(arguments, success=False)
        assert diagnostic in result.stderr, result.stderr


def check_boundaries(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    for name, body in good_cases().items():
        source = directory / f"boundary-{name}.crs"
        source.write_text(PROVIDER + main(body))
        generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
        command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
        command([build / "crust-ownership-erasure", source])
        execute(generated, symbols, directory, f"boundary-{name}", sanitize, b"")
    rejected(
        compiler,
        directory,
        {
            f"boundary-{name}": (PROVIDER + source, diagnostic)
            for name, (source, diagnostic) in bad_cases().items()
        },
    )
    check_imports(build, directory)
    check_argument_alias(build, directory)
    print("ownership boundaries: 8 positives, 10 rejections, O0/O2, erasure, source-free imports")
