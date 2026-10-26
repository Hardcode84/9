#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check generic ownership contracts through the composed source stage."""

import argparse
import tempfile
from pathlib import Path

from host import sanitizer_compiler, sanitizer_flags
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
fn array_value!(T)(i:usize)->i32 {
 var a:[[i32;2];1]=make [[i32;2];1]{make [i32;2]{3i32,7i32}};
 return a[0usize][i];
}

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
    if array_value!(i32)(1usize)!=7i32 {trap;}
    if sizeof(Plain)!=sizeof(Ticket) || alignof(Plain)!=alignof(Ticket) {trap;}
    var scalar:i64=transfer!(i64)(42i64);
    var boxed_scalar:Box!(i64)=wrap!(i64)(scalar);
    if boxed_scalar.value!=42i64 {trap;}
    var flag:bool=transfer!(bool)(true);if !flag {trap;}
    discard!(i64)(scalar);
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
    command([compiler, *selection, "--emit", "--symbols", symbols, "-o", generated, *sources])
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
        "unused-array-short": (
            "fn bad!(T)()->[i32;2]{return make [i32;2]{1i32};}",
            "initialize every element",
        ),
        "unused-array-long": (
            "fn bad!(T)()->[i32;2]{return make [i32;2]{1i32,2i32,3i32};}",
            "initialize every element",
        ),
        "unused-array-type": (
            "fn bad!(T)()->[i32;2]{return make [i32;2]{true,false};}",
            "type mismatch",
        ),
        "unused-array-nested-type": (
            "fn bad!(T)()->[[i32;1];1]{return make [[i32;1];1]{make [bool;1]{true}};}",
            "type mismatch",
        ),
        "unused-array-bool-index": (
            "fn bad!(T)()->i32 {var a:[i32;1]=make [i32;1]{1i32};return a[false];}",
            "indexes require usize",
        ),
        "unused-array-signed-index": (
            "fn bad!(T)()->i32 {var a:[i32;1]=make [i32;1]{1i32};return a[0i32];}",
            "indexes require usize",
        ),
        "unused-array-zero": ("fn bad!(T)()->unit {make [i32;0]{};}", "count must be positive"),
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
        "pointer-value-argument": (
            "fn use()->unit{transfer!(*u8)(null(*u8));}",
            "scalar or closed movable record",
        ),
        "scalar-use-after-drop": (
            "fn use()->i64{var value:i64=7i64;drop value;return value;}",
            "has been moved",
        ),
        "scalar-drop-with-loan": (
            "fn use()->unit{var value:i64=7i64;var loan:read i64=read value;drop value;drop loan;}",
            "active",
        ),
        "indirect-to-owner": (
            "fn bad!(T)(value:read T)->unit{sizeof(Box!(T));}",
            "indirect type parameter cannot satisfy a closed ownership contract",
        ),
        "indirect-to-owner-function": (
            "fn closed!(T)()->usize{return sizeof(T);}"
            "fn bad!(T)(value:read T)->usize{return closed!(T)();}",
            "indirect type parameter cannot satisfy a closed ownership contract",
        ),
        "indirect-domain-authority": (
            "domain Graph(Node);record Node{value:i64;}"
            "fn use(value:read Node)->unit access(read,Graph){inspect_view!(Node)(read value);}",
            "borrowed value requires its declared domain authority",
        ),
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
    trusted.write_text(
        "record Plain{value:i64;} record Hidden{value:read Plain;} opaque;record Outer{value:Hidden;}"
    )
    source = directory / "nested-opaque.crs"
    source.write_text(DEFINITIONS + "fn use(value:Outer)->unit{discard!(Outer)(move value);}")
    result = command([compiler, "trusted", trusted, "--library", "--check", source], expected=1)
    assert b"borrowed fields" in result.stderr, result.stderr


def check_payloads(compiler, directory, sanitize):
    source = directory / "payloads.crs"
    source.write_text(PAYLOADS + DEFINITIONS + PROGRAM)
    generated, symbols = emit_c(compiler, directory, "payloads", [source])
    execute(generated, symbols, directory, "payloads", sanitize, b"BCDE\n")


def check_indirect(compiler, directory, sanitize):
    provider = directory / "indirect-provider.crs"
    provider.write_text(
        "record Hidden{pointer:*u8;number:i64;} opaque;"
        "fn hidden_new()->Hidden{return make Hidden{pointer:null(*u8),number:42i64};}"
        "fn hidden_number(value:read Hidden)->i64{return value.number;}"
    )
    source = directory / "indirect-client.crs"
    source.write_text(
        DEFINITIONS + "domain Graph(Managed);record Managed{value:i64;}"
        "fn observe_graph!(T)(value:read T)->read T access(read,Graph) from value{return read value;}"
        "fn main(argc:i32,argv:**u8)->i32{var value:Hidden=hidden_new();"
        "var loan:read Hidden=observe!(Hidden)(read value);"
        "inspect_view!(Hidden)(read loan);"
        "if hidden_number(read loan)!=42i64{trap;}"
        "domain Graph{var node:Managed=make Managed{value:7i64};"
        "var view:read Managed=observe_graph!(Managed)(read node);if view.value!=7i64{trap;}}"
        "return 0i32;}"
    )
    generated, symbols = emit_c(compiler, directory, "indirect", [source], provider)
    execute(generated, symbols, directory, "indirect", sanitize, b"")
    for _name, code in (
        (
            "unused",
            "fn size!(T)()->usize{return sizeof(T);}fn use()->usize{return size!(Hidden)();}",
        ),
        (
            "callback-value",
            "fn call!(T)(value:fn()->T)->unit{}" "fn use()->unit{call!(Hidden)(hidden_new);}",
        ),
    ):
        source.write_text(code)
        command([compiler, "trusted", provider, "--library", "--check", source])


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
            flags += sanitizer_flags() + [optimization]
        raw = directory / "intrusive-input.o"
        obj = directory / "intrusive.o"
        binary = directory / f"intrusive{optimization}"
        command([sanitizer_compiler() if sanitize else "gcc", *flags, "-c", generated, "-o", raw])
        command(["objcopy", f"@{symbols}", raw, obj])
        command(
            [
                sanitizer_compiler() if sanitize else "gcc",
                *flags,
                obj,
                ROOT / "tests/ownership_runtime.c",
                "-o",
                binary,
            ]
        )
        result = command([binary])
        assert result.stdout == b"HFBFOK\n", result.stdout


def check_capabilities(compiler, directory):
    from ownership_transfers import CASES, PROVIDER, VALID

    provider = directory / "capability-provider.crs"
    provider.write_text(PROVIDER)
    source = directory / "capability-client.crs"
    source.write_text(VALID)
    command([compiler, "trusted", provider, "--check", source])
    for name, (text, diagnostic) in CASES.items():
        source.write_text(text)
        result = command(
            [compiler, "trusted", provider, "--library", "--check", source], expected=1
        )
        assert diagnostic in result.stderr.decode(), (name, result.stderr)
    for text in (
        "record Box!(T){value:T;}" "fn boundary!(T)(value:Box!(T))->unit transfers(value){}",
    ):
        source.write_text(text)
        result = command([compiler, "--library", "--check", source], expected=1)
        assert b"transfer requires transferable storage" in result.stderr, result.stderr
    source.write_text(
        "fn send!(T)(v:T)->T transfers(v){return move v;}"
        "fn share!(T)(v:read T)->unit transfers(v){}"
        "fn main(argc:i32,argv:**u8)->i32{var a:Shared=shared_new();"
        "share!(Shared)(read a);var b:Shared=send!(Shared)(move a);return 0i32;}"
    )
    command([compiler, "trusted", provider, "--check", source])
    for text in (
        "fn send!(T)(v:T)->unit transfers(v){} fn use(v:LocalAuthority)->unit{send!(LocalAuthority)(move v);}",
        "fn share!(T)(v:read T)->unit transfers(v){} fn use(v:read Exclusive)->unit{share!(Exclusive)(read v);}",
    ):
        source.write_text(text)
        result = command(
            [compiler, "trusted", provider, "--library", "--check", source], expected=1
        )
        assert b"transfer" in result.stderr, result.stderr
    source.write_text(
        "fn boundary!(T)(value:read Shared)->unit transfers(value){}"
        "fn main(argc:i32,argv:**u8)->i32{"
        "var value:Shared=shared_new();boundary!(i64)(read value);return 0i32;}"
    )
    command([compiler, "trusted", provider, "--check", source])


def check_manual_storage(compiler, directory, sanitize):
    provider = directory / "manual-provider.crs"
    provider.write_text(
        """
resource Optional!(T){active:bool;value:T;} opaque manual drop optional_drop!(T);
fn optional_drop!(T)(owner:mut Optional!(T))->unit{
 if owner.active {var p:*T=&owner.value;drop *p;}
}
fn optional_init!(T)(owner:*Optional!(T))->unit initializes(owner){owner->active=false;}
fn optional_empty!(T)()->Optional!(T){var o:Optional!(T)=uninit;optional_init!(T)(&o);return move o;}
fn optional_some!(T)(v:T)->Optional!(T){return make Optional!(T){active:true,value:move v};}
fn optional_take!(T)(o:mut Optional!(T))->T{if !o.active{trap;}o.active=false;var p:*T=&o.value;return move *p;}
"""
    )
    tutorial = (ROOT / "docs/ownership.md").read_text().split("### Trusted optional storage", 1)[1]
    initialize = tutorial.split("```crs\n", 1)[1].split("```", 1)[0]
    provider.write_text(provider.read_text() + initialize)
    client = directory / "manual-client.crs"
    client.write_text(
        PAYLOADS
        + """
fn main(argc:i32,argv:**u8)->i32{
 var empty:Optional!(Ticket)=optional_empty!(Ticket)();drop empty;
 var full:Optional!(Ticket)=optional_some!(Ticket)(make Ticket{value:65i64});
 var value:Ticket=optional_take!(Ticket)(mut full);drop full;drop value;
 var other:Optional!(Ticket)=optional_some!(Ticket)(make Ticket{value:66i64});drop other;
 var filled:Optional!(Ticket)=optional_empty!(Ticket)();
 optional_put!(Ticket)(mut filled,make Ticket{value:67i64});drop filled;
 return 0i32;
}
"""
    )
    generated, symbols = emit_c(compiler, directory, "manual", [client], provider)
    execute(generated, symbols, directory, "manual", sanitize, b"ABC")
    bad = directory / "manual-bad.crs"
    bad.write_text("resource Bad{value:i64;} manual drop destroy;fn destroy(v:mut Bad)->unit{}")
    result = command([compiler, "--library", "--check", bad], expected=1)
    assert b"manual cleanup requires a trusted opaque resource" in result.stderr, result.stderr


def check_tagged_storage(compiler, directory, sanitize):
    provider = directory / "choice-provider.crs"
    provider.write_text(
        """
resource Choice!(Left,Right){which:u32;first:Left;second:Right;} opaque manual drop destroy!(Left,Right);
fn destroy!(Left,Right)(x:mut Choice!(Left,Right))->unit{
 if x.which==1u32{var p:*Left=&x.first;drop *p;}
 if x.which==2u32{var p:*Right=&x.second;drop *p;}
}
fn vacant!(Left,Right)(p:*Choice!(Left,Right))->unit initializes(p){p->which=0u32;}
fn first!(Left,Right)(v:Left)->Choice!(Left,Right){var r:Choice!(Left,Right)=uninit;vacant!(Left,Right)(&r);var dst:*Left=&r.first;*dst=move v;r.which=1u32;return move r;}
fn second!(Left,Right)(v:Right)->Choice!(Left,Right){var r:Choice!(Left,Right)=uninit;vacant!(Left,Right)(&r);var dst:*Right=&r.second;*dst=move v;r.which=2u32;return move r;}
fn take!(Left,Right)(r:mut Choice!(Left,Right))->Right{if r.which!=2u32{trap;}r.which=0u32;var p:*Right=&r.second;return move *p;}
"""
    )
    client = directory / "choice-client.crs"
    client.write_text(
        """
extern fn emit(c:i32)->i32 foreign(scalar)="putchar";
resource Token{value:i32;} drop finish;fn finish(t:mut Token)->unit{emit(t.value);}
fn main(argc:i32,argv:**u8)->i32{
 var a:Choice!(Token,i64)=first!(Token,i64)(make Token{value:65i32});drop a;
 var b:Choice!(i64,Token)=second!(i64,Token)(make Token{value:66i32});var t:Token=take!(i64,Token)(mut b);drop b;drop t;
 var inside:Choice!(Token,i64)=first!(Token,i64)(make Token{value:67i32});
 var outside:Choice!(i64,Choice!(Token,i64))=second!(i64,Choice!(Token,i64))(move inside);drop outside;return 0i32;
}
"""
    )
    generated, symbols = emit_c(compiler, directory, "choice", [client], provider)
    execute(generated, symbols, directory, "choice", sanitize, b"ABC")


def check_opaque_owner_array(compiler, directory, sanitize):
    provider = directory / "owner-array.crs"
    provider.write_text(
        """
extern fn emit(c:i32)->i32="putchar";
resource Token{value:i32;} opaque drop token_drop;
fn token_drop(t:mut Token)->unit{emit(t.value);}
record Storage{values:[Token;2];} opaque;
fn use_storage()->unit{
 var s:Storage=make Storage{values:make [Token;2]{make Token{value:65i32},make Token{value:66i32}}};
}
"""
    )
    client = directory / "owner-array-client.crs"
    client.write_text(
        "fn identity!(T)(v:T)->T{return move v;}fn main(argc:i32,argv:**u8)->i32{use_storage();return identity!(i32)(0i32);}"
    )
    generated, symbols = emit_c(compiler, directory, "owner-array", [client], provider)
    execute(generated, symbols, directory, "owner-array", sanitize, b"BA")
    client.write_text("fn bad(s:read Storage)->i32{return s.values[0usize].value;}")
    result = command([compiler, "trusted", provider, "--library", "--check", client], expected=1)
    assert b"opaque" in result.stderr, result.stderr


def check_wasm_layout(compiler, directory, clang):
    source = directory / "generic-wasm.crs"
    source.write_text(
        """
record Box!(T){tag:u8;value:T;}
fn identity!(T)(value:T)->T{return move value;}
fn wasm_probe()->i32{
 var b:Box!(usize)=make Box!(usize){tag:1u8,value:identity!(usize)(7usize)};
 if sizeof(usize)!=4usize || sizeof(*u8)!=4usize || sizeof(Box!(usize))!=8usize || alignof(Box!(usize))!=4usize {return 1i32;}
 return (b.value!=7usize) as i32;
}
"""
    )
    generated = directory / "generic-wasm.c"
    command(
        [
            compiler,
            "wasm32",
            "--library",
            "--emit",
            "--export",
            "wasm_probe",
            "-o",
            generated,
            source,
        ]
    )
    script = directory / "generic-wasm.mjs"
    script.write_text(
        "const {instance}=await WebAssembly.instantiate(await Bun.file(process.argv[2]).arrayBuffer(),{});if(instance.exports.wasm_probe())throw Error('generic wasm layout');"
    )
    for level in [0, 2]:
        output = directory / f"generic-wasm-O{level}.wasm"
        command(
            [
                clang,
                "--target=wasm32",
                "-nostdlib",
                f"-O{level}",
                "-Wl,--no-entry",
                "-Wl,--export=wasm_probe",
                generated,
                "-o",
                output,
            ]
        )
        command(["bun", script, output])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build", type=Path)
    parser.add_argument("--sanitize", action="store_true")
    parser.add_argument("--wasm-clang", type=Path)
    options = parser.parse_args()
    build = (ROOT / options.build).resolve()
    compiler = build / "crust-ownership-generics-test"
    with tempfile.TemporaryDirectory(prefix="ownership-generics-", dir=build) as temporary:
        directory = Path(temporary)
        check_opaque_owner_array(compiler, directory, options.sanitize)
        if options.wasm_clang:
            check_wasm_layout(compiler, directory, options.wasm_clang.resolve())
        check_manual_storage(compiler, directory, options.sanitize)
        check_tagged_storage(compiler, directory, options.sanitize)
        check_capabilities(compiler, directory)
        check_payloads(compiler, directory, options.sanitize)
        check_indirect(compiler, directory, options.sanitize)
        check_rejections(compiler, directory)
        check_intrusive(compiler, directory, options.sanitize)
    print(
        "ownership generics: abstract definitions, equal-layout payloads, helper interfaces, "
        f"O0/O2, exact-address reuse, {len(rejection_cases()) + 3} rejections"
    )


if __name__ == "__main__":
    main()
