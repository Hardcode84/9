#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check opaque operation leases through destruction and ownership transfer."""

from ownership_support import command, execute

PROVIDER = """
resource Lease {payload:mut i64;} opaque drop lease_drop;
fn lease(input:mut i64)->Lease from input {return make Lease{payload:mut input};}
fn lease_drop(token:mut Lease)->unit {token.payload=token.payload+1i64;}
fn poll(token:mut Lease)->bool {return token.payload==7i64;}
fn consume(token:Lease)->unit {}
resource Cell {value:i64;} opaque drop cell_drop;
fn cell_drop(cell:mut Cell)->unit {}
fn cell_new()->Cell{return make Cell{value:7i64};}
fn cell_lease(cell:mut Cell)->Lease from cell{return make Lease{payload:mut cell.value};}
fn cell_value(cell:read Cell)->i64{return cell.value;}
record Pair {left:Cell;right:Cell;}
resource Context {owner:read Cell;} opaque drop context_drop;
fn context(owner:read Cell)->Context from owner{return make Context{owner:read owner};}
fn context_drop(value:mut Context)->unit{}
resource Nested {context:mut Context;owner:read Cell;} opaque drop nested_drop;
fn nested(value:mut Context)->Nested from value{
return make Nested{context:mut value,owner:read value.owner};}
fn nested_drop(value:mut Nested)->unit{}
record Numbers {left:i64;right:i64;}
resource SplitLease {first:mut i64;second:mut i64;} opaque drop split_drop;
fn split(input:mut Numbers)->SplitLease from input.left,input.right{
return make SplitLease{first:mut input.left,second:mut input.right};}
fn split_drop(token:mut SplitLease)->unit{
token.first=token.first+1i64;token.second=token.second+1i64;}


"""


WRAPPERS = (
    "record Wrapper{lease:Lease;}record Outer{inner:Wrapper;}"
    "record SplitWrapper{lease:SplitLease;}"
)
EMBEDDED = {
    "two-paths": "var numbers:Numbers=make Numbers{left:7i64,right:9i64};"
    "{var token:SplitWrapper=make SplitWrapper{lease:split(mut numbers)};"
    "var next:SplitWrapper=move token;}"
    "if numbers.left!=8i64 || numbers.right!=10i64{trap;}value=numbers.left;",
    "scope": "{var token:Wrapper=make Wrapper{lease:lease(mut value)};}",
    "drop": "var token:Wrapper=make Wrapper{lease:lease(mut value)};drop token;",
    "move": "{var first:Lease=lease(mut value);"
    "var token:Wrapper=make Wrapper{lease:move first};}",
    "nested": "{var token:Outer=make Outer{inner:make Wrapper{lease:lease(mut value)}};"
    "var next:Outer=move token;}",
}


def embedded_client(body):
    return (
        WRAPPERS
        + "fn main(argc:i32,argv:**u8)->i32{var value:i64=7i64;"
        + body
        + "return (value!=8i64) as i32;}"
    )


def check_embedded(compiler, provider, directory, sanitize):
    source = directory / "embedded-lease.crs"
    generated, symbols = directory / "embedded-lease.c", directory / "embedded-lease.rsp"
    for name, body in EMBEDDED.items():
        source.write_text(embedded_client(body))
        command(
            [compiler, "trusted", provider, "--emit", "--symbols", symbols, "-o", generated, source]
        )
        execute(generated, symbols, directory, "embedded-" + name, sanitize, b"")
    invalid = [
        "var token:Outer=make Outer{inner:make Wrapper{lease:lease(mut value)}};"
        "var next:Outer=move token;value=9i64;"
    ]
    for field in ("left", "right"):
        invalid.append(
            "var numbers:Numbers=make Numbers{left:7i64,right:9i64};"
            "var token:SplitWrapper=make SplitWrapper{lease:split(mut numbers)};"
            "var next:SplitWrapper=move token;" + f"numbers.{field}=0i64;"
        )
    for body in invalid:
        source.write_text(embedded_client(body))
        result = command([compiler, "trusted", provider, "--check", source], expected=1)
        assert "active payload loan" in result.stderr.decode(), result.stderr


def check_leases(build, directory, sanitize):
    compiler = build / "crust-ownership-test"
    provider = directory / "lease-provider.crs"
    provider.write_text(PROVIDER)
    check_embedded(compiler, provider, directory, sanitize)
    nested = directory / "nested-capture.crs"
    setup = "var owner:Cell=cell_new();var ctx:Context=context(read owner);"
    nested.write_text(
        "fn main(argc:i32,argv:**u8)->i32{"
        + setup
        + "{var token:Nested=nested(mut ctx);}{var again:Nested=nested(mut ctx);}return 0i32;}"
    )
    command([compiler, "trusted", provider, "--check", nested])
    for name, invalid in {
        "reuse": "var again:Nested=nested(mut ctx);",
        "drop-context": "drop ctx;",
        "drop-owner": "drop owner;",
    }.items():
        nested.write_text(
            "fn bad()->unit{" + setup + "var token:Nested=nested(mut ctx);" + invalid + "}"
        )
        result = command(
            [compiler, "trusted", provider, "--library", "--check", nested], expected=1
        )
        assert "active" in result.stderr.decode(), (name, result.stderr)
    prefix = "fn main(argc:i32,argv:**u8)->i32 {var value:i64=7i64;"
    live = "var token:Lease=lease(mut value);"
    cases = {
        "dead-token-write": (prefix + live + "value=9i64;return 0i32;}", "active"),
        "polled-token-write": (
            prefix + live + "var ready:bool=poll(mut token);value=9i64;return 0i32;}",
            "active",
        ),
        "moved-token-write": (
            prefix + live + "var next:Lease=move token;value=9i64;return 0i32;}",
            "active",
        ),
        "copy-token": (prefix + live + "var next:Lease=token;return 0i32;}", "explicit move"),
        "private-loan": (prefix + live + "token.payload=9i64;return 0i32;}", "private"),
        "escaped-token": (
            "fn bad(other:mut i64)->Lease from other {var local:i64=7i64;return lease(mut local);}",
            "declared source",
        ),
    }
    pair = "var pair:Pair=make Pair{left:cell_new(),right:cell_new()};"
    cases["same-owner"] = (
        prefix + pair + "var a:Lease=cell_lease(mut pair.left);"
        "var b:Lease=cell_lease(mut pair.left);return 0i32;}",
        "active",
    )
    cases["drop-parent"] = (
        prefix + pair + "var a:Lease=cell_lease(mut pair.left);" "drop pair;return 0i32;}",
        "active",
    )
    for name, (text, error) in cases.items():
        source = directory / f"lease-{name}.crs"
        source.write_text(text)
        result = command(
            [compiler, "trusted", provider, "--check", "--library", source], expected=1
        )
        assert error in result.stderr.decode(), (name, result.stderr)
    source = directory / "lease-valid.crs"
    source.write_text(
        prefix + "{" + live + "var ready:bool=poll(mut token);"
        "if !ready{trap;}var next:Lease=move token;consume(move next);}"
        "if value!=8i64{trap;}value=7i64;{" + live + "drop token;}"
        "if value!=8i64{trap;}return 0i32;}"
    )
    generated, symbols = directory / "lease.c", directory / "lease.rsp"
    command(
        [compiler, "trusted", provider, "--emit", "--symbols", symbols, "-o", generated, source]
    )
    execute(generated, symbols, directory, "lease", sanitize, b"")
    source.write_text(
        prefix + pair + "{var a:Lease=cell_lease(mut pair.left);"
        "var b:Lease=cell_lease(mut pair.right);var ready:bool=poll(mut a);"
        "if !ready{trap;}}if cell_value(read pair.left)!=8i64 || "
        "cell_value(read pair.right)!=8i64 {trap;}return 0i32;}"
    )
    command(
        [compiler, "trusted", provider, "--emit", "--symbols", symbols, "-o", generated, source]
    )
    execute(generated, symbols, directory, "sibling-leases", sanitize, b"")
