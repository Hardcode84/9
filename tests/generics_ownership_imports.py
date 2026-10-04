#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check frozen generic ownership providers and independent client specializations."""

import argparse
import hashlib
import shutil
from pathlib import Path

from ownership_support import execute
from source_order import ROOT, Suite

TAG = b"crust-generic-ownership-v1-closed-records-linux-x64\n"

HELPERS = """
fn transfer!(Payload)(value:Payload)->Payload {return move value;}
fn discard!(Payload)(value:Payload)->unit {drop value;}
fn answer()->i32 {return 37i32;}
"""

CLIENT = """
extern fn emit(value:i32)->i32 foreign(scalar)="putchar";
resource Value {code:i32;} drop value_drop;
fn value_drop(value:mut Value)->unit {emit(value.code);}
fn main(argc:i32,argv:**u8)->i32 {
    var first:Value=make Value {code:65i32};
    var second:Value=transfer!(Value)(move first);
    discard!(Value)(move second);
    return answer()-37i32;
}
"""


def build_driver(suite):
    rule = "generic-import-sources: ; @echo $(GENERIC_OWNERSHIP)"
    result = suite.command(
        ["make", "--no-print-directory", "-s", "--eval", rule, "generic-import-sources"],
        cwd=ROOT,
    )
    sources = [ROOT / path for path in result.stdout.decode().split()]
    sources.append(ROOT / "tests/generics_ownership_import_driver.crs")
    libraries = [suite.build / "libcrust0.a", suite.build / "libcrust0_host.a", *suite.ldflags]
    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    flags += [item for flag in libraries for item in ("--ldflag", flag)]
    driver = suite.work / "generics-ownership-imports"
    suite.command([suite.build / "crust-c", "-o", driver, *sources, *flags])
    return driver


def publish(suite, driver, name, sources, trusted=False, ranged=False):
    cache = suite.work / name / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    mode = "publish-trusted" if trusted else "publish"
    if ranged:
        mode = "publish-range"
    result = suite.command([driver, mode, cache, *sources])
    artifact, digest, status = result.stdout.decode().splitlines()
    receipt = Path(artifact), digest, status
    assert hashlib.sha256(receipt[0].read_bytes()).hexdigest() == digest
    assert status == ("trusted" if trusted else "checked")
    return cache, receipt


def import_args(suite, driver, name, cache, receipt, sources):
    output = suite.work / name / "program.c"
    symbols = output.with_suffix(".rsp")
    output.parent.mkdir(parents=True, exist_ok=True)
    return [driver, "import", cache, *receipt, output, symbols, *sources]


def compile_client(suite, driver, name, cache, receipt, sources, expected, sanitize):
    args = import_args(suite, driver, name, cache, receipt, sources)
    result = suite.command(args)
    assert not result.stdout and not result.stderr, (result.stdout, result.stderr)
    output, symbols = args[6:8]
    execute(output, symbols, output.parent, "program", sanitize, expected)
    return args


def check_checked_library(suite, driver, sanitize):
    provider = suite.write("checked/provider.crs", HELPERS)
    cache, receipt = publish(suite, driver, "checked", [provider])
    provider.unlink()
    client = suite.write("checked/client.crs", CLIENT)
    args = compile_client(suite, driver, "checked/first", cache, receipt, [client], b"A", sanitize)
    second = suite.write(
        "checked/second.crs", CLIENT.replace("Value", "Other").replace("65i32", "66i32")
    )
    compile_client(suite, driver, "checked/second", cache, receipt, [second], b"B", sanitize)
    rejected = suite.write("checked/copy.crs", CLIENT.replace("move first", "first"))
    result = suite.command(
        import_args(suite, driver, "checked/bad", cache, receipt, [rejected]), expected=1
    )
    assert b"explicit move" in result.stderr, result.stderr
    return args, receipt


def check_trusted_container(suite, driver, sanitize):
    original = ROOT / "examples/generics/ownership"
    provider = suite.write("container/provider.crs", (original / "provider.crs").read_bytes())
    helpers = suite.write("container/checked.crs", (original / "checked.crs").read_bytes())
    cache, receipt = publish(suite, driver, "container", [provider, helpers], trusted=True)
    provider.unlink()
    helpers.unlink()
    payloads = suite.write("container/payloads.crs", (original / "payloads.crs").read_bytes())
    client = suite.write("container/client.crs", (original / "program.crs").read_bytes())
    compile_client(
        suite, driver, "container/client", cache, receipt, [payloads, client], b"HFBFOK\n", sanitize
    )
    other_payloads = suite.write(
        "container/other-payloads.crs", payloads.read_text().replace("Plain", "Point")
    )
    other_client = suite.write(
        "container/other-client.crs", client.read_text().replace("Plain", "Point")
    )
    compile_client(
        suite,
        driver,
        "container/other",
        cache,
        receipt,
        [other_payloads, other_client],
        b"HFBFOK\n",
        sanitize,
    )


def check_ranged_provider(suite, driver, sanitize):
    prefix = "host_bootstrap(run);\n// target\n"
    suffix = "// end target\ncompiler actions outside parser range\n"
    provider = suite.write("ranged/provider.crs", prefix + HELPERS + suffix)
    cache, receipt = publish(suite, driver, "ranged", [provider], ranged=True)
    provider.unlink()
    client = suite.write("ranged/client.crs", CLIENT)
    compile_client(suite, driver, "ranged/client", cache, receipt, [client], b"A", sanitize)


def check_tampering(suite, driver, args, receipt):
    artifact = receipt[0]
    original = artifact.read_bytes()
    assert original.startswith(TAG) and b"return move value" in original
    altered = original.replace(b"return move value", b"return      value", 1)
    assert len(altered) == len(original) and altered != original
    try:
        for payload in (altered, original[:-1], original + b"extra"):
            artifact.write_bytes(payload)
            result = suite.command(args, expected=1)
            assert b"trusted digest receipt" in result.stderr, result.stderr
    finally:
        artifact.write_bytes(original)
    wrong_trust = list(args)
    wrong_trust[5] = "trusted"
    result = suite.command(wrong_trust, expected=1)
    assert b"root trust receipt differs" in result.stderr, result.stderr
    changed = suite.work / "changed-checker"
    shutil.copy2(driver, changed)
    with changed.open("ab") as stream:
        stream.write(b"different checker image")
    result = suite.command([changed, *args[1:]], expected=1)
    assert b"checker or loaded images changed" in result.stderr, result.stderr


def check_frozen_domains(suite, driver):
    cases = {
        "record": (
            "record Cell{value:i32;} fn cell_value(value:read Cell)->i32{return value.value;}",
            "domain Added(Cell); fn main(argc:i32,argv:**u8)->i32 {domain Added {"
            "var value:Cell=make Cell{value:5i32};return cell_value(read value)-5i32;}}",
        ),
        "family": (
            "record Cell!(Payload){value:Payload;}",
            "record Value{code:i32;} domain Added(Cell);"
            "fn main(argc:i32,argv:**u8)->i32 {return sizeof(Cell!(Value)) as i32 - 4i32;}",
        ),
    }
    for name, (provider_source, client_source) in cases.items():
        provider = suite.write(f"domains/{name}-provider.crs", provider_source)
        cache, receipt = publish(suite, driver, f"domains/{name}", [provider])
        provider.unlink()
        client = suite.write(f"domains/{name}-client.crs", client_source)
        result = suite.command(
            import_args(suite, driver, f"domains/{name}", cache, receipt, [client]), expected=1
        )
        assert b"domain" in result.stderr, result.stderr


def check_frozen_bindings(suite, driver):
    cases = {
        "value": "fn wrapper!(T)(value:T)->T {return missing(value);}",
        "type": "record Node!(T) {value:Missing;} opaque;",
        "argument": "record Box!(T) {value:T;} record Node!(T) {value:Box!(Missing);} opaque;",
        "drop": "resource Owner!(T) {value:T;} opaque drop missing!(T);",
        "domain": "domain Graph(Missing);",
        "access": "fn wrapper!(T)(value:T)->T access(read,Missing) {return move value;}",
        "use-before-local": "fn wrapper!(T)(value:T)->T {missing();var missing:i32=0i32;return move value;}",
    }
    for name, source in cases.items():
        provider = suite.write(f"bindings/{name}.crs", source)
        cache = provider.parent / "cache"
        cache.mkdir(exist_ok=True)
        result = suite.command([driver, "publish-trusted", cache, provider], expected=1)
        assert b"frozen provider" in result.stderr, (name, result.stderr)
    invalid = suite.write(
        "bindings/invalid-proof.crs", HELPERS.replace("return move value", "return value")
    )
    result = suite.command([driver, "publish", cache, invalid], expected=1)
    assert (
        b"schema transfer requires movable owned or fresh storage" in result.stderr
    ), result.stderr


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    parser.add_argument("--sanitize", action="store_true")
    arguments = parser.parse_args()
    suite = Suite(arguments)
    suite.work = suite.build / "generics-ownership-import-tests"
    suite.work.mkdir(exist_ok=True)
    driver = build_driver(suite)
    args, receipt = check_checked_library(suite, driver, arguments.sanitize)
    check_trusted_container(suite, driver, arguments.sanitize)
    check_ranged_provider(suite, driver, arguments.sanitize)
    check_tampering(suite, driver, args, receipt)
    check_frozen_bindings(suite, driver)
    check_frozen_domains(suite, driver)
    print(f"generic ownership imports: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
