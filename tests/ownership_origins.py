#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check finite returned origins at definitions, calls, and library boundaries."""

from ownership_imports import command as import_command
from ownership_imports import import_arguments, publish, unpack
from ownership_support import ROOT, command, execute, rejected

PICK = """
fn pick(a:read i64,b:read i64,first:bool)->read i64 from a,b {
    if first {return read a;}return read b;
}
fn choose(a:mut i64,b:mut i64,first:bool)->mut i64 from a,b {
    if first {return mut a;}return mut b;
}
"""
RECORDS = """
record Pair {left:i64;right:i64;}
fn pairs(a:read Pair,b:read Pair,first:bool)->read Pair from a,b {
    if first {return read a;}return read b;
}
fn field(a:read Pair,b:read Pair,first:bool)->read i64 from a.left,b.left {
    var pair:read Pair=pairs(read a,read b,first);return read pair.left;
}
record View {value:read i64;}
fn views(a:read View,b:read View,first:bool)->read View from a,b {
    if first {return read a;}return read b;
}
fn stored(a:read View,b:read View,first:bool)->read i64 from a.value,b.value {
    var view:read View=views(read a,read b,first);return read view.value;
}
"""


def main(body):
    return "fn main(argc:i32,argv:**u8)->i32 {" + body + "return 0i32;}"


def cases():
    start = "var a:i64=1i64;var b:i64=2i64;var x:read i64=pick(read a,read b,false);"
    records = (
        "var a:Pair=make Pair{left:1i64,right:2i64};" "var b:Pair=make Pair{left:3i64,right:4i64};"
    )
    result = {
        "narrow-forward": (
            PICK
            + "fn bad(a:read i64,b:read i64)->read i64 from a{return pick(read a,read b,true);}",
            "declared source",
        ),
        "narrow-projection": (
            RECORDS + "fn bad(a:read Pair,b:read Pair)->read i64 from a.left{"
            "var p:read Pair=pairs(read a,read b,true);return read p.left;}",
            "declared source",
        ),
        "narrow-stored": (
            RECORDS + "fn bad(a:read View,b:read View)->read i64 from a.value{"
            "var p:read View=views(read a,read b,true);return read p.value;}",
            "declared source",
        ),
        "third-source": (
            PICK + "fn bad(a:read i64,b:read i64,c:read i64)->read i64 from a,b{return read c;}",
            "declared source",
        ),
        "local-source": (
            PICK + "fn bad(a:read i64,b:read i64)->read i64 from a,b{"
            "var c:i64=0i64;return read c;}",
            "declared source",
        ),
        "unknown-origin": (
            "fn bad(a:read i64)->read i64 from a,missing{trap;}",
            "borrow parameter",
        ),
        "unborrowed-origin": (
            "fn bad(a:read i64,b:i64)->read i64 from a,b{trap;}",
            "borrow parameter",
        ),
        "shared-mut-origin": (
            "fn bad(a:mut i64,b:read i64)->mut i64 from a,b{trap;}",
            "mutable source",
        ),
        "wrong-type": (
            "fn bad(a:read i64,b:read i32)->read i64 from a,b{trap;}",
            "declared origin",
        ),
        "absent-path": (
            RECORDS + "fn bad(a:read i64,b:read Pair)->read i64 from a,b.missing{trap;}",
            "absent field",
        ),
        "trailing-comma": ("fn bad(a:read i64)->read i64 from a,{trap;}", "expected"),
        "child-keeps-both": (
            PICK + main(start + "var child:read i64=read x;b=3i64;var used:i64=child;"),
            "active",
        ),
        "defer-keeps-both": (
            PICK + "fn use(x:read i64)->unit{}" + main(start + "defer use(read x);b=3i64;"),
            "active",
        ),
        "scope-escape": (
            PICK
            + "record Saved{value:read i64;}"
            + main(
                "var a:i64=0i64;var x:Saved=uninit;{var b:i64=1i64;"
                "x=make Saved{value:pick(read a,read b,true)};}var use:i64=x.value;"
            ),
            "outlive",
        ),
        "mut-result-borrow": (
            PICK
            + main(
                "var a:i64=1i64;var b:i64=2i64;var x:mut i64=choose(mut a,mut b,true);"
                "var alias:read i64=read b;x=3i64;"
            ),
            "active",
        ),
        "record-projection-keeps-both": (
            RECORDS
            + main(
                records + "var x:read i64=field(read a,read b,false);b.left=9i64;" "var used:i64=x;"
            ),
            "active",
        ),
    }
    for source in ("a", "b"):
        result[f"write-{source}"] = (
            PICK + main(start + f"{source}=3i64;var used:i64=x;"),
            "active",
        )
    return result


def check_origins(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    source = ROOT / "examples/ownership-basics/origins.crs"
    generated, symbols = directory / "origins.c", directory / "origins.rsp"
    command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, source])
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "origins", sanitize, b"A\n")
    projected = directory / "origin-projections.crs"
    projected.write_text(
        RECORDS
        + main(
            "var a:Pair=make Pair{left:7i64,right:8i64};"
            "var b:Pair=make Pair{left:9i64,right:10i64};"
            "var x:read i64=field(read a,read b,false);if x!=9i64{trap;}"
            "var av:View=make View{value:read a.left};var bv:View=make View{value:read b.left};"
            "var y:read i64=stored(read av,read bv,false);if y!=9i64{trap;}"
            "a.left=11i64;b.left=12i64;"
        )
    )
    command([compiler, "--emit-c", "--symbols", symbols, "-o", generated, projected])
    execute(generated, symbols, directory, "origin-projections", sanitize, b"")
    rejected(compiler, directory, cases())
    check_selection_chains(build, directory, sanitize)
    check_resource_origins(build, directory, sanitize)
    check_domain_origins(build, directory)
    check_opaque_selection(build, directory)
    check_imports(build, directory, source)
    print(f"returned origins: native O0/O2, erasure, bodyless imports, {len(cases())} rejections")


def check_imports(build, directory, source):
    provider, body = source.read_text().split("fn main(", 1)
    library, client = directory / "origins-provider.crs", directory / "origins-client.crs"
    library.write_text(provider)
    client.write_text("fn main(" + body)
    driver = build / "crust-ownership-import-test"
    cache = directory / "origins-cache"
    cache.mkdir()
    receipt = publish(driver, cache, [library])
    _, _, interface = unpack(receipt[0].read_bytes())
    assert "from left, right" in interface and "from pair.left, pair.right" in interface
    library.unlink()
    output = directory / "origins-imported"
    import_command(import_arguments(driver, cache, receipt, client, output))
    assert command([output]).stdout == b"A\n"
    client.write_text(client.read_text().replace("if first!=65i64", "right=0i64;if first!=65i64"))
    result = import_command(import_arguments(driver, cache, receipt, client, output), success=False)
    assert "active" in result.stderr


def check_resource_origins(build, directory, sanitize):
    provider = (ROOT / "examples/ownership-basics/heap.crs").read_text().split("fn main(")[0]
    provider += """
fn owners(a:mut CellOwner,b:mut CellOwner,first:bool)->mut CellOwner modifies() from a,b {
    if first{return mut a;}return mut b;
}
fn cells(a:read CellOwner,b:read CellOwner,first:bool)->read Cell from a.cell,b.cell {
    if first {if a.cell==null(*Cell){trap;}return read *a.cell;}
    if b.cell==null(*Cell){trap;}return read *b.cell;
}
"""
    start = "var a:CellOwner=cell_new(1i64);var b:CellOwner=cell_new(2i64);"
    release = "if p!=null(*Cell){release(p as *u8);}"
    select = "var v:mut CellOwner=owners(mut a,mut b,false);var p:*Cell=move v.cell;"
    restored = select + "v.cell=null(*Cell);" + release + "drop v;"
    source = directory / "origin-resources.crs"
    source.write_text(provider + main(start + restored + "if b.cell!=null(*Cell){trap;}"))
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source]
    )
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "origin-resources", sanitize, b"")
    negative = {
        "selected-unrestored": (start + select + release + "drop v;", "must be initialized"),
        "selected-implicit-unrestored": (start + select + release, "must be initialized"),
        "selected-stale-null-fact": (
            start
            + "if a.cell==null(*Cell)||b.cell==null(*Cell){trap;}"
            + restored
            + "var bad:i64=b.cell.value;",
            "live non-null storage",
        ),
        "selected-null-alternative": (
            "var a:CellOwner=make CellOwner{cell:null(*Cell)};var b:CellOwner=cell_new(2i64);"
            "var v:read Cell=cells(read a,read b,false);var n:i64=v.value;var bad:i64=a.cell.value;",
            "checked storage origin",
        ),
        "selected-retirement": (
            start + "var v:read Cell=cells(read a,read b,false);drop b;var bad:i64=v.value;",
            "active",
        ),
    }
    rejected(
        build / "crust-ownership-test",
        directory,
        {
            name: (provider + main(body), diagnostic)
            for name, (body, diagnostic) in negative.items()
        },
    )
    print(
        f"returned resource origins: restoration, nullable alternatives, {len(negative)} rejections"
    )


def check_domain_origins(build, directory):
    provider = ROOT / "examples/intrusive/links.crs"
    header = (
        "fn pick(a:read Owner,b:read Owner,first:bool)->read i64 access(read,Graph) from a,b {"
        "if first{return owner_value(read a);}return owner_value(read b);}"
    )
    for name, action in {
        "domain-retire": "drop c;",
        "domain-edit": "var head:ReadyHead=uninit;ready_init(&head);ready_insert(mut head,read b);",
    }.items():
        source = directory / (name + ".crs")
        source.write_text(
            header
            + main(
                "domain Graph {var a:Owner=owner_new(1i64);"
                "var b:Owner=owner_new(2i64);var c:Owner=owner_new(3i64);var x:read i64=pick(read a,read b,true);"
                + action
                + "var use:i64=x;}"
            )
        )
        result = command(
            [build / "crust-ownership-test", "trusted", provider, "--check", source], expected=1
        )
        assert b"active domain loan" in result.stderr, result.stderr


def check_selection_chains(build, directory, sanitize):
    body = "var a:i64=1i64;var b:i64=2i64;var x0:read i64=pick(read a,read b,true);"
    body += "".join(f"var x{i}:read i64=pick(read x{i-1},read x{i-1},true);" for i in range(1, 24))
    source = directory / "selection-chain.crs"
    source.write_text(PICK + main(body + "if x23!=1i64{trap;}a=3i64;b=4i64;"))
    generated, symbols = source.with_suffix(".c"), source.with_suffix(".rsp")
    command(
        [build / "crust-ownership-test", "--emit-c", "--symbols", symbols, "-o", generated, source]
    )
    command([build / "crust-ownership-erasure", source])
    execute(generated, symbols, directory, "selection-chain", sanitize, b"")
    source.write_text(PICK + main(body + "b=3i64;var use:i64=x23;"))
    result = command([build / "crust-ownership-test", "--library", "--check", source], expected=1)
    assert b"active" in result.stderr, result.stderr


def check_opaque_selection(build, directory):
    provider = directory / "selected-opaque.crs"
    provider.write_text(
        """
domain D(Container,Item,Ticket);
record Container {item:*Item;} opaque;
resource Ticket {value:i64;} drop ticket_drop;
fn ticket_drop(value:mut Ticket)->unit access(reclaim,D) {}
resource Item {ticket:*Ticket;} owns(ticket:storage) drop item_drop;
fn item_drop(value:mut Item)->unit access(reclaim,D) {}
fn select(a:mut Container,b:mut Container,first:bool)->mut Item access(edit,D) from a,b {trap;}
"""
    )
    client = directory / "selected-opaque-client.crs"
    client.write_text(
        """
fn bad(a:mut Container,b:mut Container)->unit access(edit,D) {
    var view:mut Item=select(mut a,mut b,true);
    var stolen:*Ticket=move view.ticket;
    view.ticket=null(*Ticket);
    trap;
}
"""
    )
    result = command(
        [build / "crust-ownership-test", "trusted", provider, "--library", "--check", client],
        expected=1,
    )
    assert b"retained reference" in result.stderr, result.stderr
