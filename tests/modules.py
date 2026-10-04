#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check source-selected modules, export discovery, and context lifetimes."""

import argparse
from pathlib import Path

from source_order import ROOT, Suite, check_examples, string


def check_bindings(suite):
    prefix = f'host_source(run,{string(ROOT / "stages/modules/library.crs")});\n'
    provider = ROOT / "examples/modules/provider.crs"
    setup = f"""
var provider:CrustModule=uninit;
var consumer:CrustModule=uninit;
module_init(&provider,null(*CrustAllocator));
module_init(&consumer,null(*CrustAllocator));
if !module_read(&provider,{string(provider)},1u64) || !module_check(&provider) {{return 80i32;}};
if !module_export(&provider,"Value","") ||
   !module_export(&provider,"answer","public_answer") ||
   !module_export(&provider,"increment","public_increment") {{return 81i32;}};
"""
    cleanup = """
if provider.context.error_count!=0usize {crust_run_diagnostic(&provider.context);};
if consumer.context.error_count!=0usize {crust_run_diagnostic(&consumer.context);};
module_destroy(&consumer);
module_destroy(&provider);
return 0i32;
"""
    cases = (
        ("private", 'module_import(&consumer,&provider,"helper","local");', "not exported"),
        ("absent", 'module_export(&provider,"absent","native");', "name is absent"),
        ("duplicate", 'module_export(&provider,"answer","second");', "duplicate module export"),
        ("record-native", 'module_export(&provider,"Value","native");', "invalid native name"),
        ("function-native", 'module_export(&provider,"helper","");', "invalid native name"),
        (
            "duplicate-import",
            'module_import(&consumer,&provider,"Value","Alias");'
            'module_import(&consumer,&provider,"Value","Alias");',
            "duplicate name 'Alias'",
        ),
        (
            "reexport",
            'module_import(&consumer,&provider,"answer","call");'
            'module_export(&consumer,"call","another");',
            "requires a checked owned definition",
        ),
    )
    for name, action, diagnostic in cases:
        suite.root(name, prefix + setup + action + cleanup, diagnostic=diagnostic.encode())

    before = """
extern fn copy_bytes(dest:*u8,source:*u8,size:usize)->*u8="memcpy";
extern fn compare_bytes(left:*u8,right:*u8,size:usize)->i32="memcmp";
var facts:*CrustDecl=module_find(&provider,"Value");
var saved:CrustDecl=uninit;
var saved_type:CrustType=uninit;
var saved_context:CrustContext=uninit;
copy_bytes(&saved as *u8,facts as *u8,sizeof(CrustDecl));
copy_bytes(&saved_type as *u8,(*facts).type as *u8,sizeof(CrustType));
copy_bytes(&saved_context as *u8,&provider.context as *u8,sizeof(CrustContext));
if !module_import(&consumer,&provider,"Value","First") ||
   !module_import(&consumer,&provider,"Value","Second") ||
   !module_import(&consumer,&provider,"answer","call") {return 82i32;};
"""
    consumer = suite.write(
        "alias-consumer.crs",
        "fn same(item:*First)->*Second{return item;}\n"
        "fn use(item:*Second)->i32{return call(same(item));}\n",
    )
    after = """
if compare_bytes(&saved as *u8,facts as *u8,sizeof(CrustDecl))!=0i32 ||
   compare_bytes(&saved_type as *u8,(*facts).type as *u8,sizeof(CrustType))!=0i32 ||
   compare_bytes(&saved_context as *u8,&provider.context as *u8,sizeof(CrustContext))!=0i32 {return 84i32;};
"""
    suite.root(
        "readonly-provider",
        prefix
        + setup
        + before
        + f"if !module_read(&consumer,{string(consumer)},2u64) || !module_check(&consumer) {{return 83i32;}};\n"
        + after
        + cleanup,
    )
    for name, body, identity, diagnostic in (
        ("hidden-helper", "fn use()->i32{return helper();}", 2, "unknown name 'helper'"),
        ("missing-import", "fn use(item:*Value)->i32{return 0i32;}", 2, "unknown name 'Value'"),
        (
            "identity-conflict",
            "record Different {byte:u8;}",
            1,
            "distinct declarations share one identity",
        ),
    ):
        source = suite.write(name + "-input.crs", body)
        action = (
            f"module_read(&consumer,{string(source)},{identity}u64); module_check(&consumer);\n"
        )
        suite.root(
            name, prefix + setup + before + action + after + cleanup, diagnostic=diagnostic.encode()
        )
    suite.root(
        "missing-file",
        prefix + setup + 'module_read(&consumer,"no-such-module.crs",2u64);' + cleanup,
        diagnostic=b"cannot read module source",
    )


def check_exports(suite):
    command = [suite.runner, ROOT / "stages/modules/exports.crs"]
    interfaces = [ROOT / "stages/c/api.crs", ROOT / "stages/c/extension.crs"]
    flags = suite.command([*command, *interfaces]).stdout.split()
    assert flags[::2] == [b"--export"] * (len(flags) // 2), flags
    symbols = suite.command(
        ["nm", "-D", "--defined-only", suite.build / "crust-c-library.so"]
    ).stdout.split()[2::3]
    markers = {b"CRUST_ABI_crust0", b"CRUST_ABI_crust0_host", b"CRUST_ABI_crust0_stage"}
    assert set(flags[1::2]) | markers == set(symbols), (flags, symbols)
    invalid = suite.write("aliased-interface.crs", 'extern fn source()->i32="native";')
    malformed = suite.write("bad-interface.crs", "fn broken(")
    for paths, message in (
        ([], b"expected consumer interface paths"),
        ([*interfaces, invalid], b"identical source and native names"),
        ([*interfaces, malformed], b"expected"),
    ):
        result = suite.command([*command, *paths], expected=1)
        assert not result.stdout and message in result.stderr, result
    with open("/dev/full", "wb") as full:
        result = suite.command([*command, *interfaces], expected=1, stdout=full)
    assert b"cannot write export arguments" in result.stderr, result.stderr


def check_allocations(suite):
    fixture = suite.work / "allocation-sweep"
    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    flags += [item for flag in suite.ldflags for item in ("--ldflag", flag)]
    suite.command(
        [
            suite.build / "crust-c",
            "-o",
            fixture,
            ROOT / "api/crust0.crs",
            ROOT / "api/crust0_host.crs",
            ROOT / "stages/modules/library.crs",
            ROOT / "tests/modules_alloc.crs",
            "--ldflag",
            suite.build / "libcrust0.a",
            "--ldflag",
            suite.build / "libcrust0_host.a",
            *flags,
        ]
    )
    provider = suite.write(
        "large-provider.crs",
        (ROOT / "examples/modules/provider.crs").read_text()
        + "\n".join(f"const value_{i}:i32={i}i32;" for i in range(2000)),
    )
    suite.command([fixture, provider, ROOT / "examples/modules/consumer.crs"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    suite = Suite(parser.parse_args())
    suite.work = suite.build / "module-tests"
    suite.work.mkdir(exist_ok=True)
    check_examples(suite)
    check_bindings(suite)
    check_exports(suite)
    check_allocations(suite)
    print(f"modules: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
