#!/usr/bin/env python3
"""Compile and run user sources that select ordinary external compiler stages."""

import argparse
import json
import os
from pathlib import Path
import re
import resource
import shlex
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
SIMPLE = 'fn main(argc: i32, argv: **u8) -> i32 { return 0i32; }\n'
ENTRY = 'fn build(request: *RmdBuild) -> i32 { return c_program(request); }'


class Suite:
    def __init__(self, build):
        self.build = build.resolve()
        self.compiler = self.build / "rmd0"
        self.work = self.build / "stage-tests"
        self.work.mkdir(parents=True, exist_ok=True)
        self.backend = self.work / "copied libraries" / "ordinary backend.plugin"
        self.backend.parent.mkdir(exist_ok=True)
        shutil.copyfile(self.build / "rmd-c-library.so", self.backend)
        self.checks = 0

    def run(self, arguments, expected=0, **options):
        command = [str(arg) for arg in arguments]
        result = subprocess.run(command, cwd=options.pop("cwd", ROOT),
                                capture_output=True, timeout=30, **options)
        self.checks += 1
        if result.returncode != expected:
            raise AssertionError(
                f"{shlex.join(command)}: status {result.returncode}, expected {expected}\n"
                f"{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}")
        return result

    def source(self, name, body=ENTRY, target=SIMPLE, relative=False, dependencies=None):
        path = self.work / f"{name}.rmd"
        path.parent.mkdir(parents=True, exist_ok=True)
        inputs = dependencies if dependencies is not None else [
            ("source", ROOT / "api/rmd0.rmd"),
            ("source", ROOT / "api/rmd0_stage.rmd"),
            ("source", ROOT / "stages/c/api.rmd"),
            ("link", self.backend),
        ]
        declarations = []
        for kind, input_path in inputs:
            spelling = os.path.relpath(input_path, path.parent) if relative else str(input_path)
            declarations.append(f"    {kind} {json.dumps(spelling)};")
        prefix = "meta {\n" + "\n".join(declarations) + "\n" + body + "\n}\n"
        payload = target.encode() if isinstance(target, str) else target
        path.write_bytes(prefix.encode() + payload)
        return path

    def compile(self, source, output, **options):
        output.unlink(missing_ok=True)
        return self.run([self.compiler, source, "-o", output], **options)

    def temporary(self, name, relative=False):
        directory = self.work / name
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir()
        environment = os.environ.copy()
        environment["TMPDIR"] = directory.name if relative else str(directory)
        return directory, environment

    def clean_run(self, source, name, expected=0, fake=None, relative=False):
        directory, environment = self.temporary(name, relative)
        if fake:
            tool, status = fake
            tools = self.work / f"fail-{tool}"
            tools.mkdir(exist_ok=True)
            executable = tools / tool
            executable.write_text(f"#!/bin/sh\nexit {status}\n")
            executable.chmod(0o755)
            environment["PATH"] = str(tools) + os.pathsep + os.environ["PATH"]
        result = self.run([self.compiler, source], expected=expected, env=environment,
                          cwd=self.work if relative else ROOT)
        assert list(directory.iterdir()) == [], f"stage temporary files retained in {directory}"
        return result


def check_application(suite):
    source = suite.source("intrusive", target=(ROOT / "examples/intrusive.rmd").read_bytes())
    output = suite.work / "intrusive"
    output.unlink(missing_ok=True)
    suite.run([suite.compiler, source, "-o", output, "--ldflag", suite.build / "librmd0_host.a"])
    assert suite.run([output]).stdout == b"intrusive: ok\n"
    symbols = suite.run(["nm", output]).stdout
    assert not re.search(rb"\b(?:rmd_(?:meta|context|read|collect|resolve|check|x64)\w*|c_program|c_backend_build)\b", symbols)
    dynamic = suite.run(["readelf", "-dW", output]).stdout
    assert suite.backend.name.encode() not in dynamic
    library = suite.run(["readelf", "-dW", suite.backend]).stdout
    assert b"TEXTREL" not in library and b"BIND_NOW" in library

    target = '''fn main(argc: i32, argv: **u8) -> i32 { return 13i32; }
fn chosen(argc: i32, argv: **u8) -> i32 { return 42i32; }
'''
    source = suite.source("inline-selection", target=target)
    output = suite.work / "inline-selection"
    suite.compile(source, output)
    suite.run([output], expected=13)
    override = '''fn build(request: *RmdBuild) -> i32 {
    if (*request).argc != 2i32 { return 91i32; }
    var args: [*u8; 4] = make [*u8; 4] {
        "--entry", "chosen", (*request).argv[0usize], (*request).argv[1usize]
    };
    var changed: RmdBuild = *request;
    changed.argc = 4i32;
    changed.argv = &args[0usize];
    return c_program(&changed);
}'''
    suite.source("inline-selection", body=override, target=target)
    suite.compile(source, output)
    suite.run([output], expected=42)

    host = '''const shared: u64 = 41u64;
const host_only: *u8 = "HOST_COMPILATION_ONLY_SENTINEL";
fn main() -> u64 { return shared; }
fn main_host_only() -> i32 { return 0i32; }
fn build(request: *RmdBuild) -> i32 {
    if main() != 41u64 || host_only[0usize] != 72u8 { return 92i32; }
    return c_program(request);
}'''
    target = '''const shared: u64 = 42u64;
fn main(argc: i32, argv: **u8) -> i32 {
    if shared != 42u64 { return 1i32; }
    return 0i32;
}
'''
    source = suite.source("phase-names", body=host, target=target)
    output = suite.work / "phase-names"
    suite.compile(source, output)
    suite.run([output])
    assert b"HOST_COMPILATION_ONLY_SENTINEL" not in output.read_bytes()
    source = suite.source("private-host-name", body=host,
                          target='fn main(argc:i32,argv:**u8)->i32 { return main_host_only(); }\n')
    result = suite.run([suite.compiler, source, "--check"], expected=1)
    assert b"unknown name 'main_host_only'" in result.stderr
    source = suite.source("private-host-value", body=host,
                          target='fn main(argc:i32,argv:**u8)->i32 { return host_only[0usize] as i32; }\n')
    result = suite.run([suite.compiler, source, "--check"], expected=1)
    assert b"unknown name 'host_only'" in result.stderr


def check_reader_and_snapshot(suite):
    prefix = b"\xff@custom-reader\x00!\n"
    expected = ", ".join(f"{byte}u8" for byte in prefix)
    body = f'''fn build(request: *RmdBuild) -> i32 {{
    var source: *RmdSource = (*request).source;
    var index: usize = (*request).target_begin;
    while index < (*source).size && ((*source).bytes[index] == 10u8 || (*source).bytes[index] == 13u8 ||
          (*source).bytes[index] == 32u8 || (*source).bytes[index] == 9u8) {{ index = index + 1usize; }}
    var expected: [u8; {len(prefix)}] = make [u8; {len(prefix)}] {{ {expected} }};
    var offset: usize = 0usize;
    while offset < {len(prefix)}usize {{
        if index + offset >= (*source).size || (*source).bytes[index + offset] != expected[offset] {{
            rmd_set_error((*request).context, source, index + offset, "custom reader prefix differs");
            return 1i32;
        }}
        offset = offset + 1usize;
    }}
    (*request).target_begin = index + {len(prefix)}usize;
    return c_program(request);
}}'''
    source = suite.source("custom-reader", body=body, target=prefix + SIMPLE.encode())
    output = suite.work / "custom-reader"
    suite.compile(source, output)
    suite.run([output])
    source = suite.source("custom-reader-error", body=body, target=b"?" + prefix[1:] + SIMPLE.encode())
    line = source.read_bytes()[:source.read_bytes().index(b"?@custom-reader")].count(b"\n") + 1
    result = suite.run([suite.compiler, source, "--check"], expected=1)
    assert f"{source}:{line}:1: error: custom reader prefix differs".encode() in result.stderr

    body = '''extern fn remove_source(path: *u8) -> i32 = "unlink";
fn build(request: *RmdBuild) -> i32 {
    if remove_source((*(*request).source).path) != 0i32 { return 93i32; }
    return c_program(request);
}'''
    source = suite.source("captured-source", body=body)
    output = suite.work / "captured-source"
    suite.compile(source, output)
    assert not source.exists()
    suite.run([output])
    source = suite.source("captured-diagnostic", body=body,
                          target='\nfn main(argc:i32,argv:**u8)->i32 {\n    return missing_after_capture();\n}\n')
    contents = source.read_text()
    line = contents[:contents.index("    return missing_after_capture")].count("\n") + 1
    result = suite.run([suite.compiler, source, "--check"], expected=1)
    assert not source.exists()
    assert f"{source}:{line}:12: error:".encode() in result.stderr
    assert b"unknown name 'missing_after_capture'" in result.stderr


def check_failures(suite):
    counter = suite.work / "entry-effects"
    counter.write_bytes(b"")
    body = f'''extern fn open(path: *u8, mode: *u8) -> *u8 = "fopen";
extern fn put(value: i32, file: *u8) -> i32 = "fputc";
extern fn close(file: *u8) -> i32 = "fclose";
fn build(request: *RmdBuild) -> i32 {{
    var file: *u8 = open({json.dumps(str(counter))}, "ab");
    if file == null(*u8) {{ return 94i32; }}
    var written: i32 = put(88i32, file);
    var closed: i32 = close(file);
    if written != 88i32 || closed != 0i32 {{ return 95i32; }}
    return 37i32;
}}'''
    source = suite.source("entry-failure", body=body, target="not parsed by this stage")
    suite.clean_run(source, "tmp-entry-failure", expected=37)
    assert counter.read_bytes() == b"X", "compilation entry effects were repeated"

    for kind in ("source", "link"):
        source = suite.source(f"missing-{kind}", dependencies=[(kind, suite.work / "absent-input")])
        result = suite.clean_run(source, f"tmp-missing-{kind}", expected=1)
        assert b"cannot resolve stage input path" in result.stderr
    source = suite.work / "malformed.rmd"
    source.write_text('meta { fn build() -> i32 { return 0i32; }\n')
    assert b"error:" in suite.clean_run(source, "tmp-malformed", expected=1).stderr
    source = suite.source("wrong-entry", body='fn build() -> i32 { return 0i32; }')
    result = suite.clean_run(source, "tmp-wrong-entry", expected=1)
    assert b"meta entry must be a defined fn build(*RmdBuild) -> i32" in result.stderr
    source = suite.source("missing-entry", body='fn another(request:*RmdBuild)->i32 { return 0i32; }')
    result = suite.clean_run(source, "tmp-missing-entry", expected=1)
    assert b"meta entry must be" in result.stderr
    source = suite.source("native-unresolved", body='''extern fn absent() -> i32 = "stage_unresolved_must_fail";
fn build(request:*RmdBuild)->i32 { return absent(); }''')
    result = suite.clean_run(source, "tmp-unresolved", expected=1)
    assert b"cannot load stage" in result.stderr and b"stage_unresolved_must_fail" in result.stderr

    source = suite.source("tool-failure", body='fn build(request:*RmdBuild)->i32 { return 0i32; }')
    for tool, status in (("as", 43), ("ld", 44)):
        result = suite.clean_run(source, f"tmp-{tool}-failure", expected=status, fake=(tool, status))
        assert f"stage tool {tool} failed with status {status}".encode() in result.stderr
    source = suite.source("bad-status", body='fn build(request:*RmdBuild)->i32 { return 256i32; }')
    result = suite.clean_run(source, "tmp-bad-status", expected=1)
    assert b"compilation entry status must be between 0 and 255" in result.stderr


def check_entry_layout(suite):
    declarations = (ROOT / "api/rmd0_stage.rmd").read_text()
    inputs = [("source", ROOT / "api/rmd0.rmd")]
    changes = (
        ("context: *RmdContext", "context: *RmdSource"),
        ("source: *RmdSource", "source: *RmdContext"),
        ("target_begin: usize", "target_begin: u64"),
        ("argc: i32", "argc: u32"),
        ("argv: **u8", "argv: *u8"),
    )
    for index, (before, after) in enumerate(changes):
        assert before in declarations
        body = declarations.replace(before, after) + '''
fn build(request:*RmdBuild)->i32 { return 0i32; }
'''
        source = suite.source(f"entry-layout-{index}", body=body, dependencies=inputs)
        result = suite.clean_run(source, f"tmp-entry-layout-{index}", expected=1)
        assert b"meta entry must be a defined fn build(*RmdBuild) -> i32" in result.stderr


def check_backend_reuse(suite):
    extra_text = '''record Extra { value: i32; }
const extra_value: i32 = 42i32;
const extra_callback: fn(*Extra) -> i32 = helper;
fn helper(item: *Extra) -> i32 { return (*item).value; }
'''
    extra = suite.work / "retained-extra.rmd"
    extra.write_text(extra_text)
    generated = suite.work / "retained.c"
    symbols = suite.work / "retained.rsp"
    generated.unlink(missing_ok=True)
    symbols.unlink(missing_ok=True)
    body = '''extern fn compare_bytes(left:*u8,right:*u8,size:usize)->i32 = "memcmp";
extern fn compare_text(left:*u8,right:*u8)->i32 = "strcmp";
extern fn text_size(text:*u8)->usize = "strlen";
fn build(request:*RmdBuild)->i32 {
    if sizeof(CBackendOptions)!=56usize || alignof(CBackendOptions)!=8usize ||
       offsetof(CBackendOptions,mode)!=0usize || offsetof(CBackendOptions,output)!=8usize ||
       offsetof(CBackendOptions,symbols)!=16usize || offsetof(CBackendOptions,cflags)!=24usize ||
       offsetof(CBackendOptions,cflag_count)!=32usize || offsetof(CBackendOptions,ldflags)!=40usize ||
       offsetof(CBackendOptions,ldflag_count)!=48usize { return 80i32; }
    if (*request).argc!=2i32 || compare_text((*request).argv[0usize],"-o")!=0i32 { return 81i32; }
    var args:[*u8;2] = make [*u8;2] { "--prepare", @EXTRA@ };
    var prepare:RmdBuild = *request;
    prepare.argc = 2i32;
    prepare.argv = &args[0usize];
    var status:i32 = c_program(&prepare);
    if status!=0i32 { return status; }
    var context:*RmdContext = (*request).context;
    var parsed:*RmdUnit = (*context).units;
    if parsed==null(*RmdUnit) || (*parsed).source!=(*request).source ||
       (*parsed).next==null(*RmdUnit) { return 82i32; }
    var entry:*RmdDecl = (*parsed).declarations;
    var extra_source:*RmdSource = (*(*parsed).next).source;
    if compare_text((*(*entry).name).text,"main")!=0i32 ||
       compare_text((*extra_source).path,@EXTRA@)!=0i32 ||
       (*extra_source).size!=text_size(@EXTRA_TEXT@) ||
       compare_bytes((*extra_source).bytes,@EXTRA_TEXT@,(*extra_source).size)!=0i32 { return 83i32; }
    var saved_name:*u8 = rmd_try_copy_string(context,(*entry).link_name,text_size((*entry).link_name));
    if saved_name==null(*u8) { return 1i32; }
    var before_decl:RmdDecl = *entry;
    var before_type:RmdType = *(*entry).type;
    var before_body:RmdStmt = *(*entry).body;
    var before_source:RmdSource = *extra_source;
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
    if compare_bytes(entry as *u8,&before_decl as *u8,sizeof(RmdDecl))!=0i32 ||
       compare_bytes((*entry).type as *u8,&before_type as *u8,sizeof(RmdType))!=0i32 ||
       compare_bytes((*entry).body as *u8,&before_body as *u8,sizeof(RmdStmt))!=0i32 ||
       compare_bytes(extra_source as *u8,&before_source as *u8,sizeof(RmdSource))!=0i32 ||
       compare_text((*entry).link_name,saved_name)!=0i32 ||
       compare_bytes((*extra_source).bytes,@EXTRA_TEXT@,(*extra_source).size)!=0i32 { return 84i32; }
    return 0i32;
}'''
    for marker, value in (("@EXTRA@", str(extra)), ("@EXTRA_TEXT@", extra_text),
                          ("@GENERATED@", str(generated)), ("@SYMBOLS@", str(symbols))):
        body = body.replace(marker, json.dumps(value))
    target = '''fn main(argc:i32,argv:**u8)->i32 {
    var item:Extra = make Extra { value:extra_value };
    return extra_callback(&item);
}
'''
    source = suite.source("retained-context", body=body, target=target)
    output = suite.work / "retained-context"
    suite.compile(source, output)
    assert b"int main(" in generated.read_bytes()
    assert b"_rmd0_u" in symbols.read_bytes()
    suite.run([output], expected=42)


def check_pointer_constants(suite):
    body = '''extern fn length(text: *u8) -> usize = "strlen";
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
fn build(request: *RmdBuild) -> i32 {
    if number != 17u64 || missing != null(*u8) || missing_function != null(fn(*u8) -> usize) { return 1i32; }
    if constant_text[0usize] != 97u8 || constant_text[1usize] != 0u8 || constant_text[2usize] != 98u8 || constant_text[3usize] != 0u8 { return 2i32; }
    if callback(constant_text) != 2usize || external_callback(constant_text) != 1usize { return 3i32; }
    if callback != local || external_callback != length { return 4i32; }
    if nested.items[0usize].function(nested.items[0usize].text) != 6usize ||
       nested.items[1usize].function(nested.items[1usize].text) != 8usize { return 5i32; }
    return c_program(request);
}'''
    source = suite.source("pointer-constants", body=body)
    output = suite.work / "pointer-constants"
    suite.compile(source, output)
    suite.run([output])


def check_paths(suite):
    source = suite.source("paths with spaces/-program", relative=True)
    output = suite.work / "paths with spaces" / "-output"
    directory, environment = suite.temporary("temporary directory with spaces")
    suite.compile(source, output, env=environment)
    suite.run([output])
    assert list(directory.iterdir()) == []
    source = suite.source("dash-tmpdir", body='fn build(request:*RmdBuild)->i32 { return 0i32; }')
    suite.clean_run(source, "-temporary", relative=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    suite = Suite(args.build)
    check_application(suite)
    check_reader_and_snapshot(suite)
    check_failures(suite)
    check_entry_layout(suite)
    check_backend_reuse(suite)
    check_pointer_constants(suite)
    check_paths(suite)
    print(f"source stages: {suite.checks} process checks passed")


if __name__ == "__main__":
    main()
