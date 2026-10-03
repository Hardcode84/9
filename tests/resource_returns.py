#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check single-source returned loans through the ordinary resource compiler."""

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

from resources import ROOT, Failure, Suite, program, source_report

CELL = "record Cell {first:i32; second:i32;}\n"
READ = "fn field(value:read Cell)->read i32 from value {return read value.first;}\n"
MUT = "fn field_mut(value:mut Cell)->mut i32 from value {return mut value.first;}\n"
MAKE = "var cell:Cell=make Cell {first:41i32,second:9i32};"


def source(body, declarations=READ):
    return program(MAKE + body, CELL + declarations, common=False)


def runtime_cases():
    return [
        (
            "returned-view-tutorial",
            (ROOT / "examples/resources/returned/main.crs")
            .read_text()
            .split("// The resource stage reads the remainder of this file.\n", 1)[1],
            b"42\n",
        ),
        (
            "returned-field-lifetime",
            source(
                "{var view:read i32=field(read cell); if view!=41i32 {return 1i32;}}"
                "cell.first=42i32; if cell.first!=42i32 {return 2i32;}"
            ),
            b"",
        ),
        (
            "returned-mut-field",
            source(
                "{var view:mut i32=field_mut(mut cell); view=42i32;}"
                "if cell.first!=42i32 {return 1i32;}",
                MUT,
            ),
            b"",
        ),
        (
            "returned-read-from-mut",
            source(
                "{var view:read i32=readonly(mut cell);"
                "if view!=41i32 || cell.first!=41i32 {return 1i32;}} cell.first=42i32;",
                "fn readonly(value:mut Cell)->read i32 from value {return read value.first;}",
            ),
            b"",
        ),
        (
            "returned-forwarded-and-nested-loans",
            source(
                "{var view:read i32=forward(read identity(read cell));"
                "if view!=41i32 {return 1i32;}} cell.first=42i32;",
                READ + "fn identity(value:read Cell)->read Cell from value {return read value;}"
                "fn forward(value:read Cell)->read i32 from value {"
                "var alias:read Cell=read value; return field(read alias);}",
            ),
            b"",
        ),
        (
            "returned-second-parameter-and-branches",
            source(
                "{var view:read i32=choose(false,read cell);"
                "if view!=9i32 {return 1i32;}} cell.second=10i32;",
                "fn choose(first:bool,value:read Cell)->read i32 from value {"
                "if first {return read value.first;} return read value.second;}",
            ),
            b"",
        ),
        (
            "returned-constant-loan",
            program(
                "var view:read i32=field(read fixed); if view!=7i32 {return 1i32;}",
                CELL + READ + "const fixed:Cell=make Cell {first:7i32,second:8i32};",
                common=False,
            ),
            b"",
        ),
        (
            "returned-loan-captured-by-defer",
            source(
                "{defer verify(field(read cell));} cell.first=42i32;",
                READ + "fn verify(value:read i32)->unit {if value!=41i32 {trap;}}",
            ),
            b"",
        ),
        (
            "returned-mut-through-nested-calls",
            source(
                "{var view:mut i32=field_mut(mut identity(mut cell)); view=42i32;}"
                "if cell.first!=42i32 {return 1i32;}",
                MUT + "fn identity(value:mut Cell)->mut Cell from value {return mut value;}",
            ),
            b"",
        ),
        (
            "returned-temporary-loans-end",
            source(
                "field(read cell); *field_mut(mut cell)=42i32;"
                "if cell.first!=42i32 {return 1i32;}",
                READ + MUT,
            ),
            b"",
        ),
        (
            "returned-resource-loan-and-cleanup",
            program(
                "var value:Token=token(65i32); {var view:read i32=token_field(read value); emit(view);}"
                "var other:Token=move value;",
                "fn token_field(value:read Token)->read i32 from value {unsafe {return read value.id;}}",
            ),
            b"AA",
        ),
        (
            "returned-loan-releases-other-arguments",
            source(
                "{var view:read i32=choose(read cell,read cell); if view!=41i32 {return 1i32;}}"
                "cell.first=42i32;",
                "fn choose(first:read Cell,second:read Cell)->read i32 from first {return read first.first;}",
            ),
            b"",
        ),
    ]


def reject_cases():
    ancestry = "returned loan does not derive from its declared source parameter"
    conflict = "access conflicts with an active borrow"
    direct = "functions with returned loans can only be called directly"
    return [
        (
            "returned-loan-blocks-mutation",
            source("var view:read i32=field(read cell); cell.first=0i32;"),
            conflict,
        ),
        (
            "returned-mut-blocks-read",
            source("var view:mut i32=field_mut(mut cell); var value:i32=cell.first;", MUT),
            conflict,
        ),
        (
            "returned-mut-blocks-second-loan",
            source(
                "var first:mut i32=field_mut(mut cell); var second:mut i32=field_mut(mut cell);",
                MUT,
            ),
            conflict,
        ),
        (
            "returned-read-downgrade-blocks-mutation",
            source(
                "var view:read i32=field(read identity(mut cell)); cell.first=0i32;",
                READ + "fn identity(value:mut Cell)->mut Cell from value {return mut value;}",
            ),
            conflict,
        ),
        (
            "returned-local-escape",
            source(
                "",
                "fn bad(value:read Cell)->read i32 from value {var local:i32=1i32; return read local;}",
            ),
            ancestry,
        ),
        (
            "returned-unrelated-parameter",
            source(
                "",
                "fn bad(value:read Cell,other:read Cell)->read i32 from value {return read other.first;}",
            ),
            ancestry,
        ),
        (
            "returned-constant-is-not-parameter",
            source(
                "",
                "const fixed:i32=1i32; fn bad(value:read Cell)->read i32 from value {return read fixed;}",
            ),
            ancestry,
        ),
        (
            "returned-unsafe-forged-loan",
            source(
                "",
                "fn bad(value:mut Cell)->read i32 from value {unsafe {var pointer:*i32=&value.first; return read *pointer;}}",
            ),
            ancestry,
        ),
        (
            "returned-mut-upgrade",
            source(
                "", "fn bad(value:read Cell)->mut i32 from value {unsafe {return mut value.first;}}"
            ),
            "mutable result requires a mutable source parameter",
        ),
        (
            "returned-missing-source",
            source("", "fn bad(value:read Cell)->read i32 {return read value.first;}"),
            "without a from parameter",
        ),
        (
            "returned-unknown-source",
            source("", "fn bad(value:read Cell)->read i32 from absent {return read value.first;}"),
            "from must name a borrow parameter",
        ),
        (
            "returned-value-source",
            source("", "fn bad(value:Cell)->read i32 from value {return read value.first;}"),
            "returned loan source must be a borrow parameter",
        ),
        (
            "returned-from-on-value",
            source("", "fn bad(value:read Cell)->i32 from value {return value.first;}"),
            "from requires a borrowed function result",
        ),
        (
            "returned-native-import",
            source("", 'extern fn bad(value:read Cell)->read i32 from value="bad";'),
            "returned loans require a source ABI import",
        ),
        ("returned-function-storage", source("var callback:fn(read Cell)->*i32=field;"), direct),
        (
            "returned-function-cast",
            source("unsafe {var callback:fn(read Cell)->*i32=field as fn(read Cell)->*i32;}"),
            direct,
        ),
        (
            "returned-indirect-type",
            source("var callback:fn(read Cell)->read i32=field;"),
            "indirect function types",
        ),
        (
            "returned-function-constant",
            source("", READ + "const callback:fn(*Cell)->*i32=field;"),
            direct,
        ),
        (
            "returned-defer-requires-unit",
            source("defer field(read cell);"),
            "deferred calls must return unit",
        ),
        (
            "returned-view-blocks-owner-move",
            program(
                "var value:Token=token(65i32);"
                "var view:read i32=token_field(read value); var other:Token=move value;",
                "fn token_field(value:read Token)->read i32 from value {unsafe {return read value.id;}}",
            ),
            conflict,
        ),
        (
            "returned-view-keeps-named-parent-loan",
            source(
                "var parent:mut Cell=mut cell;"
                "var view:read i32=field(read parent); parent.first=0i32;"
            ),
            conflict,
        ),
        (
            "returned-local-escape-through-call",
            source(
                "",
                READ + "fn bad(value:read Cell)->read i32 from value {"
                "var local:Cell=make Cell {first:1i32,second:2i32}; return field(read local);}",
            ),
            ancestry,
        ),
        (
            "returned-temporary-escape",
            source(
                "var view:read i32=scalar(read make_cell().first);",
                "fn make_cell()->Cell {return make Cell {first:1i32,second:2i32};}"
                "fn scalar(value:read i32)->read i32 from value {return read value;}",
            ),
            "borrow would outlive its source storage",
        ),
    ]


def import_root(suite, output, provider, target, register):
    paths = [
        "api/crust0_stage.crs",
        "stages/c/model.crs",
        "stages/c/api.crs",
        "stages/c/extension.crs",
        "stages/resources/model.crs",
        "stages/resources/extension.crs",
    ]
    text = "".join(f"host_source(run,{json.dumps(str(ROOT / path))});\n" for path in paths)
    for name in ("crust-c-library.so", "crust-resource-library.so"):
        text += f"host_link(run,{json.dumps(str(suite.build / name))});\n"
    text += """
fn compile_target(source:*CrustSource,begin:usize)->i32 {
var context:CrustContext=uninit;
crust_context_init(&context,null(*CrustAllocator));
var stage:RsStage=uninit;
rs_init(&stage,&context);
var success:bool=rs_read(&stage,source,begin,(*source).size);
if success {
    var declaration:*CrustDecl=(*context.units).declarations;
    while declaration!=null(*CrustDecl) && success {
        if (*declaration).kind==CRUST_D_EXTERN {
            success=rs_source_import(&stage,declaration);
"""
    if register:
        text += "if success {success=rs_return_from(&stage,declaration,(*(*declaration).params).name);}\n"
    text += """
        }
        declaration=(*declaration).next;
    }
}
if success {success=rs_prepare(&stage);}
var status:i32=1i32;
if success {
    var unit_value:*CrustUnit=context.units;
    while unit_value!=null(*CrustUnit) {
        var declaration:*CrustDecl=(*unit_value).declarations;
        while declaration!=null(*CrustDecl) {
            if (*declaration).kind==CRUST_D_FUNCTION && (*declaration).link_name==null(*u8) {
                (*declaration).link_name="";
            }
            declaration=(*declaration).next;
        }
        unit_value=(*unit_value).next;
    }
    var name:*CrustName=crust_try_intern(&context,"main",4usize);
    if name!=null(*CrustName) {
        var symbol:*CrustSymbol=crust_map_get(&context.globals,name as usize) as *CrustSymbol;
"""
    flags = [
        "-O2",
        *(
            option.removeprefix("--cflag=")
            for option in suite.options
            if option.startswith("--cflag=") and option != "--cflag=-O2"
        ),
    ]
    links = [
        str(provider),
        *(
            option.removeprefix("--ldflag=")
            for option in suite.options
            if option.startswith("--ldflag=")
        ),
    ]
    for variable, values in (("flags", flags), ("links", links)):
        text += f"var {variable}:[*u8;{len(values)}]=make [*u8;{len(values)}] {{"
        text += ",".join(json.dumps(value) for value in values) + "};\n"
    text += "var options:CBackendOptions=make CBackendOptions {mode:0u32,output:"
    text += json.dumps(str(output))
    text += ",symbols:null(*u8),cflags:&flags[0usize],cflag_count:"
    text += f"{len(flags)}usize,ldflags:&links[0usize],ldflag_count:{len(links)}usize}};\n"
    text += """
        status=c_backend_build_with_body(&context,(*symbol).decl,&options,rs_c_body,&stage as *u8);
    }
}
if context.error_count!=0usize {crust_run_diagnostic(&context);}
crust_context_destroy(&context);
return status;
}
return compile_target((*run).source,(*run).cursor);
"""
    return text + target


def source_import_cases(suite):
    provider = suite.source("returned-import-provider", CELL + READ)
    object_file = suite.work / "returned-import-provider.o"
    suite.command(
        [
            suite.compiler,
            "--library",
            "--object",
            "--export",
            "field",
            "-o",
            object_file,
            *suite.options,
            provider,
        ]
    )
    for register in (False, True):
        clause = "" if register else " from input"
        declaration = f'extern fn imported(input:read Cell)->read i32{clause}="field";'
        body = "{var view:read i32=imported(read cell); if view!=41i32 {return 1i32;}} cell.first=42i32;"
        output = suite.work / f"returned-import-{register}"
        target = source(body, declaration)
        root = suite.source(
            f"returned-import-root-{register}",
            import_root(suite, output, object_file, target, register),
        )
        result = suite.command([suite.build / "crust", root])
        if result.stdout or result.stderr:
            raise Failure(f"source import produced output: {result.stdout!r} {result.stderr!r}")
        suite.command([output])
        rejected = source("var view:read i32=imported(read cell); cell.first=42i32;", declaration)
        root.write_text(import_root(suite, output, object_file, rejected, register))
        result = suite.command([suite.build / "crust", root], expected=1)
        if b"access conflicts with an active borrow" not in result.stderr:
            raise Failure(f"source import lost its returned loan: {result.stderr!r}")


def allocation_cases(suite, allocator):
    count = 0
    cases = runtime_cases()
    declarations = READ + "".join(
        f"fn relay{index}(value:read Cell)->read i32 from value {{return field(read value);}}"
        for index in range(96)
    )
    cases.append(("returned-contract-map-growth", source("", declarations), b""))
    for name, text, _ in cases:
        path = suite.source("allocation-" + name, text)
        result = suite.command([allocator.resolve(), path])
        matched = re.fullmatch(
            rb"resource allocation: ([0-9]+) failure points checked\n", result.stdout
        )
        if matched is None or result.stderr or int(matched.group(1)) == 0:
            raise Failure(f"invalid allocation result: {result.stdout!r} {result.stderr!r}")
        count += int(matched.group(1))
    print(f"Returned loan allocation suite: {len(cases)} inputs; {count} failure points")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--ldflag", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument(
        "--allocator", type=Path, help="existing resource allocation fixture executable"
    )
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="crust-resource-returns-"))
    suite = Suite(args, work)
    cases = [("runtime", *case) for case in runtime_cases()]
    cases += [("reject", *case) for case in reject_cases()]
    completed = False
    try:
        for group, name, text, expected in cases:
            try:
                getattr(suite, group)(name, text, expected)
            except Failure:
                print(source_report(text), file=sys.stderr)
                raise
        source_import_cases(suite)
        if args.allocator:
            allocation_cases(suite, args.allocator)
        print(
            f"Returned loan suite: {len(runtime_cases())} runtime, "
            f"{len(reject_cases())} rejection, 4 source import cases; {suite.commands} process checks"
        )
        completed = True
        return 0
    except (Failure, OSError) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        if completed:
            shutil.rmtree(work)
        else:
            print(f"Failure artifacts: {work}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
