#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check generic ownership contracts through the composed source stage."""

import argparse
import tempfile
from pathlib import Path

from ownership_support import ROOT, command, execute

PAYLOADS = """
extern fn emit(code:i32)->i32 foreign(scalar)="putchar";
record Plain { value:i64; }
resource Ticket { value:i64; } drop ticket_drop;
fn ticket_drop(value:mut Ticket)->unit {emit(value.value as i32);}
resource Stream { handle:*u8; } owns(handle=null(*u8)) drop stream_drop;
extern fn open_stream(size:usize)->*u8 foreign(acquire Stream.handle)="malloc";
extern fn close_stream(value:*u8)->unit foreign(move value:Stream.handle)="free";
fn stream_drop(value:mut Stream)->unit {
    if value.handle!=null(*u8) {close_stream(move value.handle);}
}
"""

DEFINITIONS = """
fn transfer!(Value)(value:Value)->Value {
    var view:read Value=observe!(Value)(read value);inspect_view!(Value)(read view);return move value;
}
fn inspect_view!(Value)(value:read Value)->unit {}
fn discard!(Value)(value:Value)->unit {drop value;}
fn observe!(Value)(value:read Value)->read Value from value {return read value;}
fn edit!(Value)(value:mut Value)->mut Value from value {return mut value;}
fn select!(Value)(left:read Value,right:read Value,first:bool)->read Value from left,right {
    if first {return read left;}return read right;
}
fn select_mut!(Value)(left:mut Value,right:mut Value,first:bool)->mut Value from left,right {
    if first {return mut left;}return mut right;
}
fn choose!(Left,Right)(left:Left,right:Right)->Left {
    discard!(Right)(move right);return transfer!(Left)(move left);
}
record Box!(Value) { value:Value; }
fn wrap!(Value)(value:Value)->Box!(Value) {return make Box!(Value){value:move value};}
fn delayed!(Value)(value:Value)->unit {defer discard!(Value)(move value);}
resource Wrapper!(Value) { value:Value; } drop wrapper_drop!(Value);
fn wrapper_drop!(Value)(value:mut Wrapper!(Value))->unit {}
"""

PROGRAM = """
fn main(argc:i32,argv:**u8)->i32 {
    if sizeof(Plain)!=sizeof(Ticket) || alignof(Plain)!=alignof(Ticket) {trap;}
    var plain:Plain=make Plain{value:7i64};
    var copied:Plain=transfer!(Plain)(plain);
    discard!(Plain)(copied);
    var other:Plain=make Plain{value:9i64};
    var choice:read Plain=select!(Plain)(read plain,read other,false);
    if choice.value!=9i64{trap;}
    var edit_choice:mut Plain=select_mut!(Plain)(mut plain,mut other,true);
    edit_choice.value=11i64;
    if edit_choice.value!=11i64{trap;}
    if plain.value!=11i64 || other.value!=9i64{trap;}
    var first:Ticket=make Ticket{value:65i64};
    var second:Ticket=make Ticket{value:66i64};
    var selected:Ticket=choose!(Ticket,Ticket)(move first,move second);
    {var view:read Ticket=observe!(Ticket)(read selected);if view.value!=65i64 {trap;}}
    {var view:mut Ticket=edit!(Ticket)(mut selected);view.value=67i64;}
    delayed!(Ticket)(move selected);
    {var boxed:Box!(Plain)=wrap!(Plain)(plain);if boxed.value.value!=11i64 {trap;}}
    {var value:Ticket=make Ticket{value:68i64};var boxed:Box!(Ticket)=wrap!(Ticket)(move value);}
    {var value:Ticket=make Ticket{value:69i64};
        var wrapped:Wrapper!(Ticket)=make Wrapper!(Ticket){value:move value};}
    var handle:*u8=open_stream(8usize);if handle==null(*u8) {trap;}
    var stream:Stream=make Stream{handle:move handle};discard!(Stream)(move stream);
    emit(10i32);return 0i32;
}
"""


def emit_c(compiler, directory, name, sources, trusted=None):
    generated = directory / f"{name}.c"
    symbols = directory / f"{name}.rsp"
    selection = ["trusted", trusted] if trusted else []
    command([compiler, *selection, "--emit-c", "--symbols", symbols, "-o", generated, *sources])
    return generated, symbols


def rejection_cases():
    return {
        "narrowed-origins": (
            "fn bad!(T)(a:read T,b:read T)->read T from a{return select!(T)(read a,read b,true);}",
            "declared source",
        ),
        "second-origin-live": (
            "fn bad(a:Plain,b:Plain)->unit{var x:read Plain=select!(Plain)(read a,read b,true);"
            "b.value=0i64;var later:i64=x.value;}",
            "active",
        ),
        "unused-copy": ("fn bad!(T)(value:T)->T{return value;}", "movable owned"),
        "unused-release-type": (
            'extern fn release(value:*u8)->unit foreign(release)="free";'
            "fn bad!(T)()->unit{release(42i64);}",
            "type mismatch",
        ),
        "sizeof-type-equality": (
            "fn bad!(A,B)(value:A)->B{if sizeof(A)==sizeof(B){return move value;}trap;}"
            "fn use(value:Plain)->Plain{return bad!(Plain,Plain)(value);}",
            "type mismatch",
        ),
        "sizeof-manufacture": (
            "fn bad!(T)()->T{if sizeof(T)==0usize{return make T{};}trap;}",
            "visible fields",
        ),
        "sizeof-consumption": (
            "fn bad!(T)(value:T)->unit{if sizeof(T)==0usize{drop value;}drop value;}",
            "owner consumption",
        ),
        "unused-after-move": (
            "fn bad!(T)(value:T)->T{var next:T=move value;return move value;}",
            "has been moved",
        ),
        "unused-construct": ("fn bad!(T)()->T{return make T{};}", "visible fields"),
        "unused-field": ("fn bad!(T)(value:read T)->unit{value.value;}", "field does not exist"),
        "unused-add": ("fn bad!(T)(value:T)->unit{value+value;}", "operator is unavailable"),
        "unused-equality": (
            "fn bad!(T)(value:T)->unit{if value==value {}}",
            "operator is unavailable",
        ),
        "unused-cast": ("fn bad!(T)(value:T)->i64{return value as i64;}", "cast requires"),
        "unused-offset": ("fn bad!(T)()->usize{return offsetof(T,value);}", "visible fields"),
        "unused-uninitialized": (
            "fn bad!(T)()->T{var value:T=uninit;return move value;}",
            "initialized storage",
        ),
        "unused-missing-return": ("fn bad!(T)(value:T)->T{}", "must return"),
        "unused-empty-return": ("fn bad!(T)(value:T)->T{return;}", "return requires"),
        "independent-parameters": (
            "fn bad!(Left,Right)(value:Left)->Right{return move value;}",
            "type mismatch",
        ),
        "phantom-parameters": (
            "record Phantom!(T){tag:i32;}"
            "fn bad!(A,B)(value:Phantom!(A))->Phantom!(B){return value;}"
            "fn use(value:Phantom!(Plain))->Phantom!(Plain){return bad!(Plain,Plain)(value);}",
            "type mismatch",
        ),
        "same-concrete-parameters": (
            "fn bad!(Left,Right)(value:Left)->Right{return move value;}"
            "fn use(value:Plain)->Plain{return bad!(Plain,Plain)(value);}",
            "type mismatch",
        ),
        "helper-mismatch": (
            "fn bad!(Left,Right)(value:Left)->Right{return transfer!(Right)(move value);}",
            "type mismatch",
        ),
        "helper-arity": (
            "fn bad!(T)(left:T,right:T)->T{return transfer!(T)(move left,move right);}",
            "argument count",
        ),
        "helper-wrong-loan": (
            "fn bad!(A,B)(value:read A)->unit{observe!(B)(read value);}",
            "type mismatch",
        ),
        "read-move": ("fn bad!(T)(value:read T)->T{return move value;}", "borrowed value"),
        "mut-move": ("fn bad!(T)(value:mut T)->T{return move value;}", "borrowed value"),
        "mut-drop": ("fn bad!(T)(value:mut T)->unit{drop value;}", "borrowed value"),
        "borrowed-owner-drop": (
            "fn bad!(T)(value:T)->unit{var loan:read T=read value;drop value;drop loan;}",
            "active payload loan",
        ),
        "defer-owner-drop": (
            "fn inspect!(T)(value:read T)->unit{}"
            "fn bad!(T)(value:T)->unit{defer inspect!(T)(read value);drop value;}",
            "active payload loan",
        ),
        "defer-result": (
            "fn bad!(T)(value:T)->unit{defer transfer!(T)(move value);}",
            "must return unit",
        ),
        "escaping-loan": ("fn bad!(T)(value:T)->read T{return read value;}", "from parameter"),
        "wrong-return-origin": (
            "fn bad!(T)(left:read T,right:read T)->read T from left{return read right;}",
            "declared",
        ),
        "wrong-initializer": (
            "fn bad!(A,B)(value:A)->Box!(B){return make Box!(B){value:move value};}",
            "type mismatch",
        ),
        "destructor-field-move": (
            "fn bad!(T)(value:Wrapper!(T))->T{return move value.value;}",
            "field out of a resource",
        ),
        "array-owner": ("fn bad!(T)(value:[T;2])->unit{}", "arrays of owners"),
        "integer-argument": ("fn use(value:Box!(i64))->unit{}", "sized movable record"),
        "same-layout-resource-copy": (
            "fn use(value:Ticket)->Ticket{return transfer!(Ticket)(value);}",
            "explicit move",
        ),
        "same-layout-wrong-kind": (
            "fn use(value:Plain)->Ticket{return transfer!(Ticket)(value);}",
            "incompatible type",
        ),
        "client-retained-loan": (
            "fn use(value:Ticket)->unit{var view:read Ticket=observe!(Ticket)(read value);drop value;drop view;}",
            "active",
        ),
        "client-mut-alias": (
            "fn use(value:Ticket)->unit{var a:mut Ticket=edit!(Ticket)(mut value);"
            "var b:mut Ticket=edit!(Ticket)(mut value);drop a;}",
            "active",
        ),
        "nested-stored-loan": (
            "record View{value:read Plain;} record Outer{value:View;}"
            "fn use(value:Outer)->unit{discard!(Outer)(move value);}",
            "closed ownership",
        ),
        "nested-domain": (
            "domain Graph(Inner);record Inner{x:i64;}record Outer{value:Inner;}"
            "fn use(value:Outer)->unit{discard!(Outer)(move value);}",
            "domain-free cleanup",
        ),
        "nested-storage-loan": (
            "record View{value:read Plain;} resource Holder{pointer:*View;} owns(pointer:storage) drop holder_drop;"
            "fn holder_drop(value:mut Holder)->unit{}"
            "fn use(value:Holder)->unit{discard!(Holder)(move value);}",
            "cannot retain borrowed fields",
        ),
    }


def check_rejections(compiler, directory):
    for name, (extra, message) in rejection_cases().items():
        source = directory / f"{name}.crs"
        source.write_text(PAYLOADS + DEFINITIONS + extra)
        result = command([compiler, "--library", "--check", source], expected=1)
        assert message in result.stderr.decode(), (name, result.stderr)
    trusted = directory / "opaque.crs"
    trusted.write_text("record Hidden{value:i64;} opaque;record Outer{value:Hidden;}")
    source = directory / "nested-opaque.crs"
    source.write_text(DEFINITIONS + "fn use(value:Outer)->unit{discard!(Outer)(move value);}")
    result = command([compiler, "trusted", trusted, "--library", "--check", source], expected=1)
    assert b"domain-free cleanup" in result.stderr, result.stderr


def check_payloads(compiler, directory, sanitize):
    source = directory / "payloads.crs"
    source.write_text(PAYLOADS + DEFINITIONS + PROGRAM)
    generated, symbols = emit_c(compiler, directory, "payloads", [source])
    execute(generated, symbols, directory, "payloads", sanitize, b"BCDE\n")


def check_intrusive(compiler, directory, sanitize):
    example = ROOT / "examples/generics/ownership"
    provider = directory / "provider.crs"
    provider.write_text(
        (example / "provider.crs")
        .read_text()
        .replace('= "malloc";', '= "ownership_test_allocate";')
        .replace('= "free";', '= "ownership_test_release";')
    )
    sources = [example / "payloads.crs", example / "checked.crs", example / "program.crs"]
    generated, symbols = emit_c(compiler, directory, "intrusive", sources, provider)
    for optimization in ("-O0", "-O2"):
        flags = ["-std=c99", "-pedantic-errors", optimization]
        if sanitize:
            flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-no-pie"]
        raw = directory / "intrusive-input.o"
        obj = directory / "intrusive.o"
        binary = directory / f"intrusive{optimization}"
        command(["gcc", *flags, "-c", generated, "-o", raw])
        command(["objcopy", f"@{symbols}", raw, obj])
        command(["gcc", *flags, obj, ROOT / "tests/ownership_runtime.c", "-o", binary])
        result = command([binary])
        assert result.stdout == b"HFBFOK\n", result.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build", type=Path)
    parser.add_argument("--sanitize", action="store_true")
    options = parser.parse_args()
    build = (ROOT / options.build).resolve()
    compiler = build / "crust-ownership-generics-test"
    with tempfile.TemporaryDirectory(prefix="ownership-generics-", dir=build) as temporary:
        directory = Path(temporary)
        check_payloads(compiler, directory, options.sanitize)
        check_rejections(compiler, directory)
        check_intrusive(compiler, directory, options.sanitize)
    print(
        "ownership generics: abstract definitions, equal-layout payloads, helper interfaces, "
        f"O0/O2, exact-address reuse, {len(rejection_cases()) + 1} rejections"
    )


if __name__ == "__main__":
    main()
