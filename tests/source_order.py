#!/usr/bin/env python3
"""Execute CRUST host programs and source-selected compiler stages."""
import argparse
import importlib.util
import json
import os
import re
import resource
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("runtime_cases", ROOT / "tests/run.py")
RUNTIME = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNTIME)


def string(value):
    result = []
    for byte in os.fsencode(value):
        if byte in (34, 92):
            result.append("\\" + chr(byte))
        elif 32 <= byte < 127:
            result.append(chr(byte))
        else:
            result.append(f"\\x{byte:02x}")
    return '"' + "".join(result) + '"'


def compilation_root(target, library, allocator_checks=False):
    prefix = (
        f'host_source(run, {string(ROOT / "api/crust0_stage.crs")});\n'
        f'host_source(run, {string(ROOT / "stages/c/api.crs")});\n'
        f"host_link(run, {string(library)});\n"
    )
    allocation = "crust_context_init(&target_context, null(*CrustAllocator));\n"
    release = ""
    if allocator_checks:
        prefix += """
extern fn target_malloc(size:usize)->*u8 = "malloc";
record AllocationCount { allocated:usize; released:usize; }
fn target_allocate(user:*u8, size:usize)->*u8 {
    var counts:*AllocationCount = user as *AllocationCount;
    var result:*u8 = target_malloc(size);
    if result != null(*u8) { (*counts).allocated = (*counts).allocated + 1usize; }
    return result;
}
fn target_release(user:*u8, bytes:*u8)->unit {
    var counts:*AllocationCount = user as *AllocationCount;
    (*counts).released = (*counts).released + 1usize;
    crust0_host_free(bytes);
}
var counts:AllocationCount = make AllocationCount { allocated:0usize, released:0usize };
var allocator:CrustAllocator = make CrustAllocator {
    user:&counts as *u8, allocate:target_allocate, release:target_release
};
"""
        allocation = "crust_context_init(&target_context, &allocator);\n"
        release = "if counts.allocated == 0usize || counts.allocated != counts.released { return 93i32; };\n"
    return (
        prefix
        + "var target_context:CrustContext = uninit;\n"
        + allocation
        + f"""
var target_source:*CrustSource = host_input(run, {string(target)}, 1u64);
if target_source == null(*CrustSource) {{ return 1i32; }};
var request:CrustBuild = make CrustBuild {{
    context:&target_context, source:target_source, target_begin:0usize,
    argc:(*run).argc, argv:(*run).argv
}};
var result:i32 = c_program(&request);
if result != 0i32 {{ crust_run_diagnostic(&target_context); }};
crust_context_destroy(&target_context);
"""
        + release
        + "return result;\n"
    )


class Suite:
    def __init__(self, arguments):
        self.build = arguments.build.resolve()
        self.runner = self.build / "crust"
        self.work = self.build / "source-order-tests"
        self.work.mkdir(parents=True, exist_ok=True)
        self.cc = shlex.split(arguments.cc)
        self.cflags = shlex.split(arguments.cflags)
        self.ldflags = shlex.split(arguments.ldflags)
        self.checks = 0
        self.native = self.work / "native.plugin"
        self.backend = self.work / "copied libraries" / "ordinary output.plugin"
        self.backend.parent.mkdir(exist_ok=True)
        shutil.copyfile(self.build / "crust-c-library.so", self.backend)

    def command(self, command, expected=0, stdout=subprocess.PIPE, **options):
        command = list(map(str, command))
        result = subprocess.run(
            command,
            cwd=options.pop("cwd", ROOT),
            stdout=stdout,
            stderr=subprocess.PIPE,
            timeout=60,
            **options,
        )
        self.checks += 1
        if expected is None:
            correct = result.returncode != 0
        else:
            correct = result.returncode == expected
        if not correct:
            raise AssertionError(
                f"{shlex.join(command)}: status {result.returncode}, expected {expected}\n"
                f"{(result.stdout or b'').decode(errors='replace')}\n{result.stderr.decode(errors='replace')}"
            )
        return result

    def write(self, name, contents):
        path = self.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents if isinstance(contents, bytes) else contents.encode())
        return path

    def root(
        self, name, contents, arguments=(), expected=0, diagnostic=None, stdout=None, **options
    ):
        path = self.write(name + ".crs", contents)
        result = self.command([self.runner, path, *arguments], expected=expected, **options)
        if diagnostic is not None:
            assert diagnostic in result.stderr, (name, result.stderr)
        elif expected == 0:
            assert not result.stderr, (name, result.stderr)
        if stdout is not None:
            assert result.stdout == stdout, (name, result.stdout)
        return result

    def native_library(self):
        self.command(
            [
                *self.cc,
                *RUNTIME.STRICT,
                *self.cflags,
                "-fPIC",
                "-shared",
                ROOT / "tests/native.c",
                *self.ldflags,
                "-o",
                self.native,
            ]
        )

    def host_unit(self, name, body, expected=0, native=False):
        path = self.write(name + "-unit.crs", body)
        prefix = f"host_link(run, {string(self.native)});\n" if native else ""
        return self.root(
            name,
            prefix + f"host_source(run, {string(path)});\nreturn main((*run).argc, (*run).argv);\n",
            ["runtime-witness"],
            expected=expected,
        )


def check_root(suite):
    suite.root("empty", "", stdout=b"")
    suite.root("trivia", "// no implicit target\n// complete\n", stdout=b"")
    buffered_output = suite.write(
        "buffered-output.crs",
        'extern fn native_puts(text:*u8)->i32="puts"; native_puts("buffered root output");',
    )
    for argument in ("--help", "--version", buffered_output):
        with open("/dev/full", "wb") as full:
            failure = suite.command([suite.runner, argument], expected=1, stdout=full)
        assert b"crust: cannot write standard output" in failure.stderr, failure.stderr
    suite.root(
        "arguments",
        """
if (*run).argc != 2i32 || (*run).argv[2usize] != null(*u8) { return 1i32; };
if (*run).argv[0usize][0usize] != 65u8 || (*run).argv[1usize][0usize] != 66u8 { return 2i32; };
return 0i32;
""",
        ["A", "B"],
    )
    suite.root(
        "locals",
        """
var value:u32 = 0u32;
while value < 8u32 {
    value = value + 1u32;
    if value == 2u32 { continue; }
    if value == 5u32 { break; }
};
{ var local:u32 = 2u32; value = value + local; };
if value == 7u32 { value = value + 1u32; } else { return 2i32; };
if value != 8u32 { return 3i32; };
return 0i32;
""",
    )
    suite.root(
        "self-recursion",
        """
fn fact(n:u32)->u32 { if n == 0u32 { return 1u32; } return n * fact(n - 1u32); }
if fact(6u32) != 720u32 { return 1i32; };
return 0i32;
""",
    )
    suite.root("return-skips-unread", b"return 37i32;\0unread", expected=37)
    suite.root(
        "effect-once-before-return",
        'crust0_host_write_stream(1u32,"X",1usize); return 37i32;',
        expected=37,
        stdout=b"X",
    )
    suite.root(
        "status-survives-ordinary-action", "(*run).status=37i32; var value:u32=1u32;", expected=37
    )
    suite.root(
        "nested-default-execution-retains-status",
        """
fn consume_next(current:*CrustRun)->bool {
    var action:*u8=null(*u8);
    if !crust_run_read(current,null(*u8),&action) { return false; }
    if action==null(*u8) {
        crust_set_error((*current).context,(*current).source,(*current).cursor,"expected nested action");
        return false;
    }
    return crust_run_execute(current,null(*u8),action);
}
(*run).status=37i32;
consume_next(run);
var consumed:u32=7u32;
if consumed!=7u32 { return 1i32; };
""",
        expected=37,
    )
    for code in ("return -1i32;", "return 256i32;"):
        suite.root(
            "bad-status-" + str(len(code)),
            code,
            expected=1,
            diagnostic=b"root status must be between zero and 255",
        )
    for name, code in {
        "no-forward-call": "later(); fn later()->unit {}",
        "no-unread-body-name": "fn early()->i32 { return later(); } fn later()->i32{return 0i32;}",
        "no-root-capture": "var value:i32=1i32; fn f()->i32{return value;}",
        "nominal-identities": "record A{x:u8;} record B{x:u8;} var a:A=make A{x:1u8}; var b:B=make B{x:2u8}; a=b;",
        "block-needs-end": "if true { return 0i32; }",
        "root-break": "break;",
        "root-return-type": "return 1u64;",
    }.items():
        result = suite.root(name, code, expected=1)
        assert b"error:" in result.stderr, (name, result.stderr)
    marker = suite.work / "earlier-effect.txt"
    marker.unlink(missing_ok=True)
    code = f'crust0_host_write_file({string(marker)}, "once", 4usize);\n@'
    result = suite.root("effect-before-parse-error", code, expected=1)
    assert marker.read_bytes() == b"once" and b":2:1:" in result.stderr, result.stderr
    unit = suite.write(
        "mutual.crs",
        """
fn even(value:u32)->bool { if value==0u32{return true;} return odd(value-1u32); }
fn odd(value:u32)->bool { if value==0u32{return false;} return even(value-1u32); }
""",
    )
    relative = os.path.relpath(unit, suite.work)
    suite.root(
        "closed-forward-references",
        f"host_source(run,{string(relative)}); if !even(10u32) || !odd(9u32){{return 1i32;}};",
        cwd="/tmp",
    )
    saved = suite.write("snapshot-input.crs", "immutable snapshot\n")
    encoded = os.fsencode(saved)
    body = (
        f"var path_bytes:[u8; {len(encoded)+1}] = make [u8; {len(encoded)+1}] {{"
        + ",".join(f"{byte}u8" for byte in encoded + b"\0")
        + "};\n"
    )
    body += "var snapshot:*CrustSource=host_input(run,&path_bytes[0usize],99u64);\n"
    body += "if snapshot==null(*CrustSource){return 1i32;}; path_bytes[0usize]=88u8;\n"
    body += f"if (*snapshot).path[0usize]!=47u8 || (*snapshot).size!={len('immutable snapshot'+chr(10))}usize || (*snapshot).bytes[0usize]!=105u8{{return 2i32;}};\n"
    suite.root("captured-path-storage", body)
    conflict = suite.write("local-conflict.crs", "fn taken()->unit{}")
    suite.root(
        "local-declaration-conflict",
        f"var taken:u32=1u32; host_source(run,{string(conflict)});",
        expected=1,
        diagnostic=b"conflicts with a root local",
    )


def check_runtime(suite):
    suite.native_library()
    suite.root(
        "full-runtime",
        f'host_link(run,{string(suite.native)}); host_source(run,{string(ROOT / "tests/runtime.crs")}); '
        "return main((*run).argc,(*run).argv);",
        ["runtime-witness"],
    )
    for name, declaration, statement, diagnostic in (
        ("callback-trap", "", "trap;", b"required execution trap"),
        (
            "callback-error",
            'extern fn absent()->i32="crust_callback_missing_symbol";',
            "return absent();",
            b"unresolved native symbol",
        ),
    ):
        body = (
            'extern fn native_callback(function:fn(i8,u8,i16,u16,i32,u32,i64,u64)->i32)->i32="native_callback";'
            + declaration
            + "fn callback(a:i8,b:u8,c:i16,d:u16,e:i32,f:u32,g:i64,h:u64)->i32{"
            + statement
            + "} fn main(argc:i32,argv:**u8)->i32{return native_callback(callback);}"
        )
        failed = suite.host_unit(name, body, expected=-signal.SIGABRT, native=True)
        assert diagnostic in failed.stderr, failed.stderr
    comparisons = 0
    for kind, (bits, signed) in RUNTIME.TYPES.items():
        cases = RUNTIME.integer_cases(kind, bits, signed)
        comparisons += len(cases)
        functions = []
        for start in range(0, len(cases), 200):
            name = f"case_{start}"
            body = [f"fn {name}()->i32{{"]
            body += [
                f"if ({expression}) != ({value}) {{return {index}i32;}}"
                for index, (expression, value) in enumerate(cases[start : start + 200], 1)
            ]
            body += ["return 0i32;}"]
            functions.append((name, "\n".join(body)))
        main = "\n".join(
            f"var s{i}:i32={name}(); if s{i}!=0i32{{return s{i};}}"
            for i, (name, _) in enumerate(functions)
        )
        body = (
            "\n".join(body for _, body in functions)
            + "\nfn main(argc:i32,argv:**u8)->i32{"
            + main
            + "return 0i32;}"
        )
        suite.host_unit("integer-" + kind, body)
    traps = ["trap;"]
    for kind, (bits, signed) in RUNTIME.TYPES.items():
        traps += [f"1{kind} {op} 0{kind};" for op in ("/", "%")]
        traps += [f"1{kind} {op} {bits}{kind};" for op in ("<<", ">>")]
        if signed:
            traps += [f"1{kind} {op} -1{kind};" for op in ("<<", ">>")]
            traps += [f"-{1 << (bits - 1)}{kind} {op} -1{kind};" for op in ("/", "%")]
    for index, statement in enumerate(traps):
        suite.root(
            f"required-trap-{index}",
            statement,
            expected=-signal.SIGABRT,
            diagnostic=b"required execution trap",
        )
    dynamic = [
        "1i32 / native_i32(0i32);",
        "-2147483648i32 / native_i32(-1i32);",
        "1i32 << native_i32(-1i32);",
        "1i32 >> native_i32(32i32);",
    ]
    for index, statement in enumerate(dynamic):
        suite.root(
            f"native-trap-{index}",
            f"host_link(run,{string(suite.native)});"
            'extern fn native_i32(value:i32)->i32="native_i32";' + statement,
            expected=-signal.SIGABRT,
            diagnostic=b"required execution trap",
        )
    check_pointer_constants(suite)
    print(f"host integers: {comparisons} comparisons; required traps: {len(traps) + len(dynamic)}")


READER_PREFIX = """
record ReaderState { reads:usize; executions:usize; boundary:usize; }
record ReaderPayload { byte:u8; }
fn wrong_executor(current:*CrustRun,user:*u8, payload:*u8)->bool {
    crust_set_error((*current).context,(*current).source,(*current).cursor,"wrong executor selected");
    return false;
}
fn selected_reader(current:*CrustRun,user:*u8, output:**u8)->bool {
    var state:*ReaderState = user as *ReaderState;
    (*state).reads = (*state).reads + 1usize;
    if (*current).cursor == (*(*current).source).size {
        if (*state).reads != 2usize || (*state).executions != 1usize {
            crust_set_error((*current).context,(*current).source,(*current).cursor,"reader counts differ");
            return false;
        }
        *output = null(*u8);
        return true;
    }
    var position:usize = (*current).cursor;
    if position != (*state).boundary || (*(*current).source).bytes[position] != 0u8 {
        crust_set_error((*current).context,(*current).source,position,"incorrect reader boundary");
        return false;
    }
    if position + 1usize >= (*(*current).source).size || (*(*current).source).bytes[position+1usize] != 65u8 {
        crust_set_error((*current).context,(*current).source,position+1usize,"expected alternate A");
        return false;
    }
    var payload:*ReaderPayload = crust_try_alloc((*current).context,sizeof(ReaderPayload),alignof(ReaderPayload)) as *ReaderPayload;
    if payload == null(*ReaderPayload) { return false; }
    (*payload).byte = 65u8;
    (*current).cursor = position + 2usize;
    (*current).execute = wrong_executor;
    *output = payload as *u8;
    return true;
}
fn selected_executor(current:*CrustRun,user:*u8, opaque:*u8)->bool {
    var state:*ReaderState = user as *ReaderState;
    var payload:*ReaderPayload = opaque as *ReaderPayload;
    (*state).executions = (*state).executions + 1usize;
    if (*payload).byte != 65u8 { return false; }
    return crust0_host_write_stream(1u32,&(*payload).byte,1usize) == 0i32;
}
fn install_reader(current:*CrustRun,state:*ReaderState)->unit {
    (*state).boundary = (*current).cursor;
    (*current).user = state as *u8;
    (*current).read = selected_reader;
    (*current).execute = selected_executor;
}
var reader_state:ReaderState = make ReaderState {reads:0usize,executions:0usize,boundary:0usize};
install_reader(run,&reader_state);"""


def check_reader_state(suite):
    state = "record StageState {byte:u8; next:*StageState;}\n"
    operations = """
fn next_reader(current:*CrustRun,user:*u8,output:**u8)->bool {
    (*current).cursor=(*(*current).source).size;
    *output=current as *u8;
    return true;
}
fn next_executor(current:*CrustRun,user:*u8,action:*u8)->bool {
    var selected:*StageState=user as *StageState;
    (*current).returned=true;
    return crust0_host_write_stream(1u32,&(*selected).byte,1usize)==0i32;
}
fn first_reader(current:*CrustRun,user:*u8,output:**u8)->bool {
    var selected:*StageState=user as *StageState;
    (*current).read=next_reader;
    (*current).execute=next_executor;
    (*current).user=(*selected).next as *u8;
    (*current).cursor=(*current).cursor+1usize;
    *output=current as *u8;
    return true;
}
fn first_executor(current:*CrustRun,user:*u8,action:*u8)->bool {
    var selected:*StageState=user as *StageState;
    return crust0_host_write_stream(1u32,&(*selected).byte,1usize)==0i32;
}
"""
    setup = """
var after:StageState=make StageState {byte:66u8,next:null(*StageState)};
var before:StageState=make StageState {byte:65u8,next:&after};
{ (*run).read=first_reader; (*run).execute=first_executor; (*run).user=&before as *u8; };
This input belongs to the selected stages.
"""
    suite.root("reader-state-interpreted", state + operations + setup, stdout=b"AB")
    source = suite.write("reader-state-native.crs", state + operations)
    obj = source.with_suffix(".o")
    library = source.with_suffix(".plugin")
    suite.command(
        [
            suite.build / "crust-c",
            "--library",
            "--object",
            "--export",
            "first_reader",
            "--export",
            "first_executor",
            "--cflag=-fPIC",
            *[item for flag in suite.cflags for item in ("--cflag", flag)],
            "-o",
            obj,
            ROOT / "api/crust0.crs",
            ROOT / "api/crust0_host.crs",
            ROOT / "api/crust0_eval.crs",
            ROOT / "api/crust0_run.crs",
            source,
        ]
    )
    suite.command([*suite.cc, "-shared", obj, *suite.ldflags, "-o", library])
    declarations = """
extern fn first_reader(current:*CrustRun,user:*u8,output:**u8)->bool="first_reader";
extern fn first_executor(current:*CrustRun,user:*u8,action:*u8)->bool="first_executor";
"""
    suite.root(
        "reader-state-native",
        f"host_link(run,{string(library)});\n" + state + declarations + setup,
        stdout=b"AB",
    )


def check_readers(suite):
    check_reader_state(suite)
    suite.root("interpreted-reader-transfer", READER_PREFIX.encode() + b"\0A", stdout=b"A")
    suite.root(
        "reader-reentry-explicit-return",
        b"""
fn nested_reader(current:*CrustRun,user:*u8,output:**u8)->bool {
    (*current).read=crust_run_read;
    var completed:bool=crust_run_loop(current);
    *output=null(*u8);
    return completed;
}
(*run).read=nested_reader;return 37i32;\0unread""",
        expected=37,
    )
    failure = READER_PREFIX.encode() + b"\0B"
    result = suite.root(
        "reader-original-location", failure, expected=1, diagnostic=b"expected alternate A"
    )
    offset = len(READER_PREFIX.encode()) + 1
    line = failure[:offset].count(b"\n") + 1
    column = offset - failure.rfind(b"\n", 0, offset)
    assert f":{line}:{column}:".encode() in result.stderr, result.stderr
    consuming = READER_PREFIX.replace(
        "(*state).executions = (*state).executions + 1usize;",
        "(*state).executions = (*state).executions + 1usize; (*current).cursor = (*current).cursor + 1usize;",
    )
    suite.root("executor-consumes-input", consuming.encode() + b"\0A?", stdout=b"A")
    cases = {
        "reader-no-progress": ("*output = current as *u8; return true;", b"without input progress"),
        "reader-out-of-range": (
            "(*current).cursor = (*(*current).source).size + 1usize; *output = current as *u8; return true;",
            b"invalid cursor",
        ),
        "reader-early-eof": ("*output = null(*u8); return true;", b"EOF with unread bytes"),
        "reader-no-diagnostic": ("return false;", b"reader failed without a diagnostic"),
        "reader-changes-source": (
            "(*current).source = null(*CrustSource); return true;",
            b"reader changed the source",
        ),
    }
    for name, (body, diagnostic) in cases.items():
        code = (
            f"fn reader(current:*CrustRun,user:*u8,output:**u8)->bool{{{body}}}\n(*run).read=reader;".encode()
            + b"\0"
        )
        suite.root(name, code, expected=1, diagnostic=diagnostic)
    for value in (-1, 256):
        body = (
            f"(*current).status={value}i32; (*current).cursor=(*(*current).source).size;"
            "*output=null(*u8); return true;"
        )
        code = (
            f"fn reader(current:*CrustRun,user:*u8,output:**u8)->bool{{{body}}}\n(*run).read=reader;".encode()
            + b"\0"
        )
        suite.root(
            f"reader-invalid-eof-status-{value}",
            code,
            expected=1,
            diagnostic=b"root status must be between zero and 255",
        )
    rewind = READER_PREFIX.replace(
        "return crust0_host_write_stream(1u32,&(*payload).byte,1usize) == 0i32;",
        "(*current).cursor=0usize; return true;",
    )
    suite.root(
        "executor-rewinds", rewind.encode() + b"\0A", expected=1, diagnostic=b"invalid cursor"
    )


def check_foreign_errors(suite):
    suite.root(
        "unneeded-native-symbol", 'extern fn absent()->i32="crust_test_absent_symbol"; return 0i32;'
    )
    suite.root(
        "missing-native-symbol",
        'extern fn absent()->i32="crust_test_absent_symbol"; return absent();',
        expected=1,
        diagnostic=b"unresolved native symbol",
    )
    suite.root(
        "native-signature-conflict",
        'extern fn a()->u8="crust_test_shared"; extern fn b()->u64="crust_test_shared";',
        expected=1,
        diagnostic=b"native",
    )
    suite.root(
        "missing-input",
        'host_source(run,"no-such-source.crs");',
        expected=1,
        diagnostic=b"cannot read source input",
    )
    suite.root(
        "empty-input-path", 'host_source(run,"");', expected=1, diagnostic=b"input path is empty"
    )
    suite.root(
        "missing-library",
        'host_link(run,"no-such-library.plugin");',
        expected=1,
        diagnostic=b"cannot load native input",
    )
    suite.root(
        "no-implicit-loader-search",
        'crust_run_link(run,"libc.so.6");',
        expected=1,
        diagnostic=b"error:",
    )
    libraries = []
    for index in range(2):
        path = suite.write(
            f"ambiguous-{index}.c",
            f"int shared_symbol(void);\nint shared_symbol(void){{return {index};}}\n",
        )
        library = path.with_suffix(".plugin")
        suite.command(
            [
                *suite.cc,
                *RUNTIME.STRICT,
                *suite.cflags,
                "-fPIC",
                "-shared",
                path,
                *suite.ldflags,
                "-o",
                library,
            ]
        )
        libraries.append(library)
    code = "".join(f"host_link(run,{string(path)});" for path in libraries)
    suite.root(
        "ambiguous-native-symbol",
        code + 'extern fn value()->i32="shared_symbol"; return value();',
        expected=1,
        diagnostic=b"ambiguous native symbol",
    )
    suite.root(
        "resolved-native-address-stays-fixed",
        f'host_link(run,{string(libraries[0])}); extern fn value()->i32="shared_symbol";'
        f"if value()!=0i32{{return 1i32;}}; host_link(run,{string(libraries[1])}); return value();",
    )


def check_target(suite):
    target = ROOT / "examples/intrusive/program.crs"
    response = suite.work / "intrusive.rsp"
    code = compilation_root(target, suite.backend, allocator_checks=True)
    result = suite.root("intrusive-stage", code, ["--emit-c", "--symbols", response])
    c_path = suite.write("intrusive.c", result.stdout)
    reference = suite.work / "reference.rsp"
    prepared = suite.command([suite.build / "crust-c", "--emit-c", "--symbols", reference, target])
    assert result.stdout == prepared.stdout and response.read_bytes() == reference.read_bytes()
    prefix = (
        f'host_source(run,{string(ROOT / "api/crust0_stage.crs")});\n'
        f'host_source(run,{string(ROOT / "stages/c/api.crs")});\n'
        f'host_source(run,{string(ROOT / "stages/c/build.crs")});\n'
        f"host_link(run,{string(suite.backend)});\n"
        f"var captured:*CrustSource=host_input(run,{string(target)},1u64);\n"
    )
    reader = READER_PREFIX.replace(
        "boundary:usize; }", "boundary:usize; target:*CrustSource; argc:i32; argv:**u8; }"
    )
    reader = reader.replace(
        "boundary:0usize};", "boundary:0usize,target:captured,argc:(*run).argc,argv:(*run).argv};"
    )
    reader = reader.replace(
        "return crust0_host_write_stream(1u32,&(*payload).byte,1usize) == 0i32;",
        "return c_build((*state).target,0usize,(*state).argc,(*state).argv) == 0i32;",
    )
    transferred = suite.root(
        "reader-selected-intrusive",
        (prefix + reader).encode() + b"\0A",
        ["--emit-c", "--symbols", response],
    )
    assert transferred.stdout == prepared.stdout and response.read_bytes() == reference.read_bytes()
    raw = suite.work / "intrusive-raw.o"
    obj = suite.work / "intrusive.o"
    executable = suite.work / "intrusive"
    suite.command(
        [
            *suite.cc,
            "-std=c99",
            "-pedantic-errors",
            *suite.cflags,
            "-Wno-overlength-strings",
            "-c",
            c_path,
            "-o",
            raw,
        ]
    )
    suite.command(["objcopy", "@" + str(response), raw, obj])
    suite.command(
        [
            *suite.cc,
            "-no-pie",
            obj,
            suite.build / "libcrust0_host.a",
            *suite.ldflags,
            "-o",
            executable,
        ]
    )
    assert suite.command([executable]).stdout == b"intrusive: ok\n"
    symbols = suite.command(["nm", executable]).stdout
    assert not re.search(
        rb"\b(?:crust_(?:run|eval|context|read|check|collect|resolve)\w*|c_program|c_backend_build|ffi_\w*)\b",
        symbols,
    )
    needed = suite.command(["readelf", "-dW", executable]).stdout
    assert b"libffi" not in needed and suite.backend.name.encode() not in needed
    later = suite.write(
        "forward-target.crs",
        "fn main(argc:i32,argv:**u8)->i32{return later();}\nfn later()->i32{return 0i32;}\n",
    )
    suite.root(
        "target-forward",
        compilation_root(later, suite.backend),
        ["--emit-c", "--symbols", "/dev/null"],
    )
    bad = suite.write(
        "host-name-target.crs", "fn main(argc:i32,argv:**u8)->i32{return host_source();}\n"
    )
    result = suite.root(
        "target-separate-names",
        compilation_root(bad, suite.backend),
        ["--emit-c", "--symbols", "/dev/null"],
        expected=1,
        diagnostic=b"unknown name 'host_source'",
    )
    assert str(bad).encode() + b":1:" in result.stderr, result.stderr
    check_backend_reuse(suite)


def check_backend_reuse(suite):
    extra_text = """record Extra { value: i32; }
const extra_value: i32 = 42i32;
const extra_callback: fn(*Extra) -> i32 = helper;
fn helper(item: *Extra) -> i32 { return (*item).value; }
"""
    extra = suite.work / "retained-extra.crs"
    extra.write_text(extra_text)
    generated = suite.work / "retained.c"
    symbols = suite.work / "retained.rsp"
    generated.unlink(missing_ok=True)
    symbols.unlink(missing_ok=True)
    body = """extern fn compare_bytes(left:*u8,right:*u8,size:usize)->i32 = "memcmp";
extern fn compare_text(left:*u8,right:*u8)->i32 = "strcmp";
extern fn text_size(text:*u8)->usize = "strlen";
fn build(request:*CrustBuild)->i32 {
    if sizeof(CBackendOptions)!=56usize || alignof(CBackendOptions)!=8usize ||
       offsetof(CBackendOptions,mode)!=0usize || offsetof(CBackendOptions,output)!=8usize ||
       offsetof(CBackendOptions,symbols)!=16usize || offsetof(CBackendOptions,cflags)!=24usize ||
       offsetof(CBackendOptions,cflag_count)!=32usize || offsetof(CBackendOptions,ldflags)!=40usize ||
       offsetof(CBackendOptions,ldflag_count)!=48usize { return 80i32; }
    if (*request).argc!=2i32 || compare_text((*request).argv[0usize],"-o")!=0i32 { return 81i32; }
    var args:[*u8;2] = make [*u8;2] { "--prepare", @EXTRA@ };
    var prepare:CrustBuild = *request;
    prepare.argc = 2i32;
    prepare.argv = &args[0usize];
    var status:i32 = c_program(&prepare);
    if status!=0i32 { return status; }
    var context:*CrustContext = (*request).context;
    var parsed:*CrustUnit = (*context).units;
    if parsed==null(*CrustUnit) || (*parsed).source!=(*request).source ||
       (*parsed).next==null(*CrustUnit) { return 82i32; }
    var entry:*CrustDecl = (*parsed).declarations;
    var extra_source:*CrustSource = (*(*parsed).next).source;
    if compare_text((*(*entry).name).text,"main")!=0i32 ||
       compare_text((*extra_source).path,@EXTRA@)!=0i32 ||
       (*extra_source).size!=text_size(@EXTRA_TEXT@) ||
       compare_bytes((*extra_source).bytes,@EXTRA_TEXT@,(*extra_source).size)!=0i32 { return 83i32; }
    var saved_name:*u8 = crust_try_copy_string(context,(*entry).link_name,text_size((*entry).link_name));
    if saved_name==null(*u8) { return 1i32; }
    var before_decl:CrustDecl = *entry;
    var before_type:CrustType = *(*entry).type;
    var before_body:CrustStmt = *(*entry).body;
    var before_source:CrustSource = *extra_source;
    var options:CBackendOptions = make CBackendOptions {
        mode:2u32,output:@GENERATED@,symbols:@SYMBOLS@,
        cflags:null(**u8),cflag_count:0usize,ldflags:null(**u8),ldflag_count:0usize
    };
    status = c_backend_build(context,entry,&options);
    if status!=0i32 { return status; }
    options.mode = 0u32;
    options.output = (*request).argv[1usize];
    options.symbols = null(*u8);
    status = c_backend_build(context,entry,&options);
    if status!=0i32 { return status; }
    if compare_bytes(entry as *u8,&before_decl as *u8,sizeof(CrustDecl))!=0i32 ||
       compare_bytes((*entry).type as *u8,&before_type as *u8,sizeof(CrustType))!=0i32 ||
       compare_bytes((*entry).body as *u8,&before_body as *u8,sizeof(CrustStmt))!=0i32 ||
       compare_bytes(extra_source as *u8,&before_source as *u8,sizeof(CrustSource))!=0i32 ||
       compare_text((*entry).link_name,saved_name)!=0i32 ||
       compare_bytes((*extra_source).bytes,@EXTRA_TEXT@,(*extra_source).size)!=0i32 { return 84i32; }
    return 0i32;
}"""
    for marker, value in (
        ("@EXTRA@", str(extra)),
        ("@EXTRA_TEXT@", extra_text),
        ("@GENERATED@", str(generated)),
        ("@SYMBOLS@", str(symbols)),
    ):
        body = body.replace(marker, json.dumps(value))
    target = """fn main(argc:i32,argv:**u8)->i32 {
    var item:Extra = make Extra { value:extra_value };
    return extra_callback(&item);
}
"""
    target_path = suite.write("retained-target.crs", target)
    program = compilation_root(target_path, suite.backend)
    program = program.replace(
        "var target_context:CrustContext = uninit;",
        body + "\nvar target_context:CrustContext = uninit;",
    )
    program = program.replace(
        "var result:i32 = c_program(&request);", "var result:i32 = build(&request);"
    )
    output = suite.work / "retained-context"
    suite.root("retained-context", program, ["-o", output])
    assert b"int main(" in generated.read_bytes()
    assert symbols.read_bytes() == b""
    suite.command([output], expected=42)


def check_pointer_constants(suite):
    body = """extern fn length(text: *u8) -> usize = "strlen";
record Item { text: *u8; function: fn(*u8) -> usize; }
record Nested { items: [Item; 2]; }
const number: u64 = 17u64;
const missing: *u8 = null(*u8);
const missing_function: fn(*u8) -> usize = null(fn(*u8) -> usize);
const constant_text: *u8 = ("a\\0b");
const callback: fn(*u8) -> usize = (local);
const external_callback: fn(*u8) -> usize = length;
const nested: Nested = make Nested { items: make [Item; 2] {
    make Item { text: "local", function: local }, make Item { text: "external", function: length }
} };
fn local(text: *u8) -> usize { return length(text) + 1usize; }
fn main(argc:i32,argv:**u8) -> i32 {
    if number != 17u64 || missing != null(*u8) || missing_function != null(fn(*u8) -> usize) { return 1i32; }
    if constant_text[0usize] != 97u8 || constant_text[1usize] != 0u8 || constant_text[2usize] != 98u8 || constant_text[3usize] != 0u8 { return 2i32; }
    if callback(constant_text) != 2usize || external_callback(constant_text) != 1usize { return 3i32; }
    if callback != local || external_callback != length { return 4i32; }
    if nested.items[0usize].function(nested.items[0usize].text) != 6usize ||
       nested.items[1usize].function(nested.items[1usize].text) != 8usize { return 5i32; }
    return 0i32;
}"""
    suite.host_unit("pointer-constants", body)


def check_examples(suite):
    package = suite.work / "example package"
    if package.exists():
        shutil.rmtree(package)
    for directory in ("examples", "api", "stages"):
        shutil.copytree(ROOT / directory, package / directory)
    output = package / "build"
    output.mkdir()
    for name in ("crust-c-library.so", "libcrust0_host.a"):
        shutil.copyfile(suite.build / name, output / name)
    elsewhere = package / "working directory"
    elsewhere.mkdir()

    def compile_example(name, arguments=()):
        path = package / "examples" / name / "main.crs"
        result = suite.command([suite.runner, path, *arguments], cwd=elsewhere)
        assert not result.stdout and not result.stderr, (name, result)
        return path

    hello = compile_example("hello")
    assert suite.command([output / "hello"]).stdout == b"Hello, world!\n"
    compile_example("multiple-files")
    assert suite.command([output / "multiple-files"]).stdout == b"Hello from another source file!\n"

    compile_example("arguments", ["--check"])
    compile_example("arguments", ["-o", "argument output"])
    assert suite.command([elsewhere / "argument output", "first", "two words"]).stdout == (
        b"Program arguments:\nfirst\ntwo words\n"
    )

    flags = [item for flag in suite.cflags for item in ("--cflag", flag)]
    flags += [item for flag in suite.ldflags for item in ("--ldflag", flag)]
    compile_example(
        "intrusive", ["-o", output / "intrusive", "--ldflag", output / "libcrust0_host.a", *flags]
    )
    assert suite.command([output / "intrusive"]).stdout == b"intrusive: ok\n"

    reader = package / "examples/reader-switch/main.crs"
    expected = b"Hello from a reader written in CRUST!\nThese lines use the new grammar.\n"
    result = suite.command([suite.runner, reader], cwd=elsewhere)
    assert result.stdout == expected and not result.stderr, result
    with open("/dev/full", "wb") as full:
        result = suite.command([suite.runner, reader], expected=1, stdout=full, cwd=elsewhere)
    assert b"cannot write text" in result.stderr, result.stderr
    original = reader.read_text()
    bad_line = original[: original.index("> Hello")].count("\n") + 1
    reader.write_text(original.replace("> Hello", "! Hello"))
    result = suite.command([suite.runner, reader], expected=1, cwd=elsewhere)
    assert f"{reader}:{bad_line}:1:".encode() in result.stderr, result.stderr
    assert b"expected '> ' before text" in result.stderr, result.stderr

    original = hello.read_text()
    broken = hello.with_name("bad-target.crs")
    broken.write_text(original + "fn bad()->i32{return missing_value;}\n")
    retained = (output / "hello").read_bytes()
    result = suite.command([suite.runner, broken], expected=1, cwd=elsewhere)
    assert f"{broken}:{original.count(chr(10)) + 1}:".encode() in result.stderr, result.stderr
    assert b"unknown name 'missing_value'" in result.stderr, result.stderr
    assert (output / "hello").read_bytes() == retained


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--cflags", default="-O2")
    parser.add_argument("--ldflags", default="")
    parser.add_argument(
        "--group",
        choices=("all", "root", "runtime", "readers", "foreign", "target", "examples"),
        default="all",
    )
    arguments = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    suite = Suite(arguments)
    for name, function in (
        ("root", check_root),
        ("runtime", check_runtime),
        ("readers", check_readers),
        ("foreign", check_foreign_errors),
        ("target", check_target),
        ("examples", check_examples),
    ):
        if arguments.group in ("all", name):
            function(suite)
            print(f"source order: {name} passed", flush=True)
    print(f"source order: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
