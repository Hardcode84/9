# SPDX-License-Identifier: Apache-2.0
"""Check compiler selection, cache provenance, and checked production packages."""

import os


def check(work, seed, run):
    package = work / "custom compiler"
    package.mkdir()
    source = package / "compile.crs"
    text = r"""fn custom_compile(request:*StageCompile)->bool {
    var stage:CStage=uninit;c_stage_init(&stage,request->context);
    c_buffer_text(&stage.header,"const char *CRUST_ABI_crust0=\"");
    c_buffer_text(&stage.header,CRUST_ABI_crust0);
    c_buffer_text(&stage.header,"\";\nint answer(void){return 17;}\n");
    var success:bool=!stage.status.failed &&
        crust0_host_write_file(request->output,stage.header.data,stage.header.size)==0i32 &&
        crust0_host_write_file(request->symbols,"",0usize)==0i32;
    c_stage_destroy(&stage);
    if !success{crust_set_error(request->context,null(*CrustSource),0usize,"custom emission failed");}
    return success;
}
"""
    source.write_text(text)
    (package / "compiler.crs").write_text(
        'stage_include(stage,"../stages/c/sources.crs");\n'
        'stage_source(stage,"../stages/cache/model.crs");\n'
        'stage_source(stage,"../stages/build/interface.crs");\n'
        'stage_source(stage,"compile.crs");\n'
        'stage_export(stage,"custom_compile");\n'
    )
    (package / "input.crs").write_text("this is input for the selected compiler\n")
    manifest = package / "package.crs"
    selection = (
        'stage_source(stage,"input.crs");\n'
        'stage_compiler(stage,"compiler.crs","custom_compile");\n'
    )
    manifest.write_text(selection)
    root = work / "compiler-main.crs"
    root.write_text(
        """host_source(run,"stages/build/load.crs");
if !stage_setup(run,"."){return 1i32;};
var stages:*StageSession=stage_open(run,".","build/stage-cache");
if stages==null(*StageSession){return 1i32;};
var path:*u8=stage_library(stages,"custom compiler/package.crs");
if path==null(*u8){return 1i32;};
if crust0_host_write_stream(1u32,path,native_strlen(path))!=0i32 || !crust_run_link(run,path){return 1i32;};
extern fn answer()->i32="answer";
return answer();
"""
    )
    first = run([seed, root], expected=17, cwd="/").stdout
    assert run([seed, root], expected=17, cwd="/").stdout == first
    stat = source.stat()
    source.write_text(text.replace("return 17;", "return 19;"))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = run([seed, root], expected=19, cwd="/").stdout
    assert changed != first
    manifest.write_text(
        selection + 'stage_source_option(stage,stage->sources.items[0usize],"chosen");\n'
    )
    options = run([seed, root], expected=19, cwd="/").stdout
    assert options != changed
    manifest.write_text(
        selection
        + """stage_source_option(stage,stage->sources.items[0usize],"a");
stage_source_option(stage,stage->sources.items[0usize],"b");
"""
    )
    assert b"conflicting stage source options" in run([seed, root], expected=1, cwd="/").stderr
    manifest.write_text(selection)
    source.write_text("fn custom_compile(request:*StageCompile)->bool{return false;}\n")
    assert b"failed without a diagnostic" in run([seed, root], expected=1, cwd="/").stderr
    manifest.write_text(selection.replace('"custom_compile"', '"absent_entry"'))
    assert b"absent_entry" in run([seed, root], expected=1, cwd="/").stderr
    manifest.write_text(selection.replace('"compiler.crs"', '"package.crs"'))
    assert b"dependency depth exceeds" in run([seed, root], expected=1, cwd="/").stderr

    # The normal union package must reject changes in its checked source.
    union_root = work / "examples/union/main.crs"
    run([seed, union_root], cwd="/")
    assert run([work / "build/union"]).stdout == b"union: OK\n"
    checked = work / "stages/union/layout_checked.crs"
    original = checked.read_text()
    for edit, diagnostic in (
        ("layout.pointer;", b"opaque fields"),
        ("drop layout;", b"borrowed value"),
    ):
        checked.write_text(
            original.replace("var data:SuLayoutData=", edit + "var data:SuLayoutData=", 1)
        )
        rejected = run([seed, union_root], expected=1, cwd="/")
        assert diagnostic in rejected.stderr, rejected.stderr
        assert b"layout_checked.crs:" in rejected.stderr, rejected.stderr
    checked.write_text(original.replace("access(edit,CompilerArena)", "access(read,CompilerArena)"))
    assert b"stronger domain authority" in run([seed, union_root], expected=1, cwd="/").stderr
    checked.write_text(original)
    checked = work / "stages/union/lower_checked.crs"
    original = checked.read_text()
    for edit, diagnostic in (
        ("destination.pointer;", b"opaque fields"),
        ("drop destination;", b"borrowed value"),
    ):
        checked.write_text(original.replace("var name:SuName=", edit + "var name:SuName=", 1))
        rejected = run([seed, union_root], expected=1, cwd="/")
        assert diagnostic in rejected.stderr, rejected.stderr
        assert b"lower_checked.crs:" in rejected.stderr, rejected.stderr
    checked.write_text(original.replace("access(edit,CompilerArena)", "access(read,CompilerArena)"))
    assert b"stronger domain authority" in run([seed, union_root], expected=1, cwd="/").stderr
    checked.write_text(original)
    print(
        "stage compilers: source selection, compiler and option invalidation, failures, cycles, checked union passed"
    )
