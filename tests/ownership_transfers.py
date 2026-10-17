# SPDX-License-Identifier: Apache-2.0
"""Check data capabilities at scoped task and channel boundaries."""

from ownership_support import command, execute

PROVIDER = """
extern fn application_raw()->unit="raw_provider_only";
resource Shared {value:i64;} opaque send share drop shared_drop;
fn shared_new()->Shared{return make Shared{value:7i64};}
fn shared_drop(value:mut Shared)->unit{}
fn shared_read(value:read Shared)->i64{return value.value;}
fn shared_edit(value:mut Shared)->unit{value.value=8i64;}
resource LocalAuthority {identity:i64;} opaque drop authority_drop;
fn authority_drop(value:mut LocalAuthority)->unit{}
fn application_edit(authority:mut LocalAuthority)->unit{}
resource Exclusive {value:i64;} opaque send drop exclusive_drop;
fn exclusive_drop(value:mut Exclusive)->unit{}
resource SharedOnly {value:i64;} opaque share drop shared_only_drop;
fn shared_only_drop(value:mut SharedOnly)->unit{}
resource Guard {value:read Shared;} opaque drop guard_drop;
fn guard(value:read Shared)->Guard transfers(value) from value{return make Guard{value:read value};}
fn guard_drop(value:mut Guard)->unit{}
resource Channel {value:i64;full:bool;} opaque send drop channel_drop;
fn channel_new()->Channel{return make Channel{value:0i64,full:false};}
fn channel_drop(value:mut Channel)->unit{}
fn channel_send(channel:mut Channel,value:Shared)->unit transfers(value){
if channel.full{trap;}channel.value=value.value;channel.full=true;}
fn channel_receive(channel:mut Channel)->Shared{
if !channel.full{trap;}channel.full=false;return make Shared{value:channel.value};}
"""

VALID = """
fn helper(v:read Shared)->i64{return shared_read(read v);}
fn compute(v:read Shared)->i64{return helper(read v);}
fn local_operation(value:mut LocalAuthority)->unit{application_edit(mut value);}
fn send_exclusive(value:Exclusive)->unit transfers(value){}
fn lend_exclusive(value:mut Exclusive)->unit transfers(value){}
fn lend_shared(value:read SharedOnly)->unit transfers(value){}
record Data {values:[i64;2];}
fn send_data(value:Data)->unit transfers(value){}
fn main(argc:i32,argv:**u8)->i32{
var v:Shared=shared_new();
{var task:Guard=guard(read v);if compute(read v)!=7i64{trap;}}
shared_edit(mut v);
var channel:Channel=channel_new();channel_send(mut channel,move v);
var received:Shared=channel_receive(mut channel);
return (shared_read(read received)!=8i64) as i32;}
"""

CASES = {
    "send-cache-is-not-share": (
        "record Envelope{item:Exclusive;}"
        "fn send(v:Envelope)->unit transfers(v){}"
        "fn share(v:read Envelope)->unit transfers(v){}",
        "shareable read loan",
    ),
    "share-cache-is-not-send": (
        "record Envelope{item:SharedOnly;}"
        "fn share(v:read Envelope)->unit transfers(v){}"
        "fn send(v:Envelope)->unit transfers(v){}",
        "transferable storage",
    ),
    "local-read": ("fn bad(v:read LocalAuthority)->unit transfers(v){}", "shareable read loan"),
    "local-move": ("fn bad(v:LocalAuthority)->unit transfers(v){}", "transferable storage"),
    "exclusive-read": ("fn bad(v:read Exclusive)->unit transfers(v){}", "shareable read loan"),
    "shared-move": ("fn bad(v:SharedOnly)->unit transfers(v){}", "transferable storage"),
    "shared-mutable": ("fn bad(v:mut SharedOnly)->unit transfers(v){}", "transferable storage"),
    "nested-authority": (
        "record Capture{authority:read LocalAuthority;}fn bad(v:Capture)->unit transfers(v){}",
        "shareable read loan",
    ),
    "owned-cleanup": (
        "resource Capture{authority:LocalAuthority;}drop cleanup;"
        "fn cleanup(value:mut Capture)->unit{application_edit(mut value.authority);}"
        "fn bad(value:Capture)->unit transfers(value){}",
        "transferable storage",
    ),
    "raw-pointer": ("fn bad(v:*u8)->unit transfers(v){}", "transferable storage"),
    "function-pointer": ("fn bad(v:fn()->unit)->unit transfers(v){}", "transferable storage"),
    "unknown-capture": ("fn bad()->unit transfers(absent){}", "must name a function parameter"),
    "forged-capability": ("record Bad {value:i64;} send;", "trusted opaque representation"),
    "forged-authority": (
        "fn bad()->unit{var local:LocalAuthority=make LocalAuthority{identity:0i64};}",
        "opaque",
    ),
    "missing-authority": ("fn bad()->unit{application_edit();}", "argument"),
    "raw-provider-call": ("fn bad()->unit{application_raw();}", "explicit foreign contract"),
    "capture-mutation": (
        "fn bad(v:mut Shared)->unit{var task:Guard=guard(read v);shared_edit(mut v);}",
        "active payload loan",
    ),
    "capture-escape": (
        "fn bad(v:read Shared)->Guard from v{var local:Shared=shared_new();return guard(read local);}",
        "declared source",
    ),
    "channel-reuse": (
        "fn bad(channel:mut Channel)->unit{var v:Shared=shared_new();"
        "channel_send(mut channel,move v);shared_read(read v);}",
        "moved",
    ),
    "removed-worker-clause": ("fn bad()->unit worker{}", "expected"),
}


def check_transfers(build, directory):
    compiler = build / "crust-ownership-test"
    provider = directory / "transfer-provider.crs"
    provider.write_text(PROVIDER)
    check_transfer_dag(compiler, directory)
    valid = directory / "transfer-valid.crs"
    valid.write_text(VALID)
    generated, symbols = directory / "transfer.c", directory / "transfer.rsp"
    command([compiler, "trusted", provider, "--emit", "--symbols", symbols, "-o", generated, valid])
    execute(generated, symbols, directory, "transfer", False, b"")
    for name, (text, diagnostic) in CASES.items():
        path = directory / f"transfer-{name}.crs"
        path.write_text(text)
        result = command([compiler, "trusted", provider, "--library", "--check", path], expected=1)
        assert diagnostic in result.stderr.decode(), (name, result.stderr)


def check_transfer_imports(directory, driver, cache, environment):
    from ownership_imports import command as run
    from ownership_imports import import_arguments, publish, reject_import, unpack

    provider = directory / "transfer-provider.crs"
    library = directory / "transfer-library.crs"
    client = directory / "transfer-client.crs"
    provider.write_text(PROVIDER)
    library.write_text("fn compute(value:read Shared)->i64{return shared_read(read value);}")
    receipt = publish(driver, cache, [library], "trusted", str(provider))
    _, _, interface = unpack(receipt[0].read_bytes())
    assert "application_raw" not in interface, interface
    provider.unlink()
    library.unlink()
    output = directory / "transfer-client"
    args = import_arguments(driver, cache, receipt, client, output, trusted=True)
    client.write_text(
        "fn call(value:read Shared)->i64 transfers(value){return compute(read value);}"
        "fn main(argc:i32,argv:**u8)->i32{var value:Shared=shared_new();"
        "var channel:Channel=channel_new();channel_send(mut channel,move value);"
        "var next:Shared=channel_receive(mut channel);return (call(read next)!=7i64) as i32;}"
    )
    run(args, env=environment)
    run([str(output)])
    client.write_text(
        "fn bad(value:read LocalAuthority)->unit transfers(value){}"
        "fn main(argc:i32,argv:**u8)->i32{return 0i32;}"
    )
    reject_import(args, environment, "shareable read loan")
    client.write_text(
        "fn bad()->unit{application_raw();}fn main(argc:i32,argv:**u8)->i32{return 0i32;}"
    )
    reject_import(args, environment, "unknown value name")
    return 2


def check_transfer_dag(compiler, directory):
    provider = directory / "transfer-dag.crs"
    provider.write_text(
        "record R0{value:i64;}"
        + "".join(f"record R{i}{{a:R{i-1};b:R{i-1};}}" for i in range(1, 33))
        + "fn send(value:R32)->unit transfers(value){}"
        + "fn share(value:read R32)->unit transfers(value){}"
    )
    client = directory / "transfer-dag-client.crs"
    client.write_text("fn main(argc:i32,argv:**u8)->i32{return 0i32;}")
    # Repeated fields must cost work per declared type, not per layout occurrence.
    command([compiler, "trusted", provider, "--check", client], timeout=10)
