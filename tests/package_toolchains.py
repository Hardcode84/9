# SPDX-License-Identifier: Apache-2.0
"""Build packages through a selected assembler and the shared artifact path."""

import json
import os
import shutil


def check(work, seed, run):
    package = work / "asm packages"
    package.mkdir()
    compiler = package / "compiler.crs"
    compiler.write_text('stage_include(stage,"../stages/asm/compiler-package.crs");\n')
    provider = package / "provider.crs"
    provider.write_text("fn answer()->i32{return 23i32;}\n")
    manifest = package / "package.crs"
    selection = """stage_source(stage,"../api/crust0.crs");
stage_source(stage,"provider.crs");
stage_export(stage,"answer");
stage_compiler(stage,"compiler.crs","asm_stage_compile");
stage_toolchain(stage,"asm_stage_toolchain");
"""
    manifest.write_text(selection)
    root = package / "main.crs"
    root.write_text(
        """host_source(run,"../stages/build/load.crs");
if !stage_setup(run,".."){return 1i32;};
var stages:*StageSession=stage_open(run,"..","../build/stage-cache");
if stages==null(*StageSession){return 1i32;};
var artifact:*u8=stage_library(stages,"asm packages/package.crs");
if artifact==null(*u8){return 1i32;};
if crust0_host_write_stream(1u32,artifact,native_strlen(artifact))!=0i32 || !crust_run_link(run,artifact){return 1i32;};
extern fn answer()->i32="answer";
return answer();
"""
    )
    first = run([seed, root], expected=23, cwd="/").stdout
    assert run([seed, root], expected=23, cwd="/").stdout == first
    # The emission endpoint returns the selected backend's input before object compilation.
    assembly, symbols = package / "output.s", package / "output.symbols"
    run([seed, work / "stages/build/emit.crs", manifest, assembly, symbols], cwd="/")
    assert b".text" in assembly.read_bytes() and symbols.read_bytes() == b""
    provider.write_text("fn answer()->i32{return 29i32;}\n")
    assert run([seed, root], expected=29, cwd="/").stdout != first
    selected_inputs(package, work, seed, run, compiler, root)
    failures(package, work, seed, run, compiler, root)
    manifest.write_text(selection + 'stage_toolchain(stage,"asm_stage_toolchain");\n')
    assert b"toolchain already selected" in run([seed, root], expected=1, cwd="/").stderr
    manifest.write_text(selection.replace('"asm_stage_toolchain"', '"absent_toolchain"'))
    compiler.write_text('stage_include(stage,"../stages/asm/compiler-package.crs");\n')
    assert b"absent_toolchain" in run([seed, root], expected=1, cwd="/").stderr
    manifest.write_text('stage_toolchain(stage,"asm_stage_toolchain");\n')
    assert b"select a compiler" in run([seed, root], expected=1, cwd="/").stderr
    assert not list((work / "build/stage-cache").glob("crust-*"))
    production(package, work, seed, run)
    print(
        "package toolchains: ASM emission/loading, captured tools/options, failures, cleanup, ASM-built C backend passed"
    )


def selected_inputs(package, work, seed, run, compiler, root):
    assembler = package / "assembler"
    shutil.copy2("/usr/bin/as", assembler)
    flags = package / "assembler.flags"
    flags.write_text("--gdwarf-4")
    source = package / "toolchain.crs"
    source.write_text(
        """fn selected_toolchain(config:*StageToolchain)->bool {
    var flags:*CrustSource=crust_try_alloc(config->context,sizeof(CrustSource),alignof(CrustSource)) as *CrustSource;
    if flags==null(*CrustSource) || !cache_read(config->context,FLAGS,flags) || !cache_add(config->context,&config->inputs,flags){return false;}
    config->user=flags->bytes;
    config->object=selected_object;
    var paths:[*u8;1]=make [*u8;1]{ASSEMBLER};
    return cache_tools(config->context,&config->inputs,&paths[0usize],1usize,config->directory);
}
fn selected_object(request:*StageObject)->bool {
    var arguments:[*u8;7]=make [*u8;7]{ASSEMBLER,"--64",request->user,request->source,"-o",request->output,null(*u8)};
    return cache_tool(request->context,&arguments[0usize],null(*u8));
}
""".replace(
            "FLAGS", json.dumps(str(flags))
        ).replace(
            "ASSEMBLER", json.dumps(str(assembler))
        )
    )
    compiler.write_text(
        """stage_include(stage,"../stages/asm/compiler-package.crs");
stage_source(stage,"toolchain.crs");
stage_export(stage,"selected_toolchain");
"""
    )
    manifest = package / "package.crs"
    manifest.write_text(
        manifest.read_text().replace('"asm_stage_toolchain"', '"selected_toolchain"')
    )
    first = run([seed, root], expected=29, cwd="/").stdout
    assert run([seed, root], expected=29, cwd="/").stdout == first
    stat = assembler.stat()
    with assembler.open("ab") as output:
        output.write(b"toolchain cache witness\n")
    os.utime(assembler, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = run([seed, root], expected=29, cwd="/").stdout
    assert changed != first
    stat = flags.stat()
    flags.write_text("--gdwarf-5")
    os.utime(flags, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    options = run([seed, root], expected=29, cwd="/").stdout
    assert options != changed
    flags.write_text("--crust-invalid-option")
    assert b"tool failed" in run([seed, root], expected=1, cwd="/").stderr
    flags.unlink()
    assert run([seed, root], expected=1, cwd="/").stderr
    flags.write_text("--gdwarf-5")
    assert run([seed, root], expected=29, cwd="/").stdout == options


def failures(package, work, seed, run, compiler, root):
    source = package / "toolchain.crs"
    for definition, diagnostic in (
        ("return false;", b"selected toolchain failed without a diagnostic"),
        ("return true;", b"has no object compiler"),
        (
            "config->object=broken_object;return true;",
            b"selected object compiler failed without a diagnostic",
        ),
        (
            'native_error(config->context,"configuration error");return true;',
            b"configuration error",
        ),
    ):
        source.write_text(
            "fn selected_toolchain(config:*StageToolchain)->bool{" + definition + "}\n"
            "fn broken_object(request:*StageObject)->bool{return false;}\n"
        )
        assert diagnostic in run([seed, root], expected=1, cwd="/").stderr
    source.write_text(
        """fn selected_toolchain(config:*StageToolchain)->bool{config->object=broken_object;return true;}
fn broken_object(request:*StageObject)->bool {
    cache_save(request->context,request->output,"partial",7usize);
    return native_error(request->context,"object compilation stopped");
}
"""
    )
    assert b"object compilation stopped" in run([seed, root], expected=1, cwd="/").stderr


def production(package, work, seed, run):
    (package / "c-backend.crs").write_text(
        """stage_include(stage,"../stages/c/sources.crs");
stage_export_as(stage,"c_backend_build","asm_c_backend_build");
stage_compiler(stage,"../stages/asm/compiler-package.crs","asm_stage_compile");
stage_toolchain(stage,"asm_stage_toolchain");
"""
    )
    root = package / "production.crs"
    root.write_text(
        """host_source(run,"../stages/build/load.crs");
if !stage_setup(run,".."){return 1i32;};
var stages:*StageSession=stage_open(run,"..","../build/stage-cache");
if stages==null(*StageSession) || !stage_load(stages,"asm packages/c-backend.crs"){return 1i32;};
extern fn asm_c_backend_build(context:*CrustContext,entry:*CrustDecl,options:*CBackendOptions)->i32="asm_c_backend_build";
var target:CrustContext=uninit;
crust_context_init(&target,null(*CrustAllocator));
var text:*u8="extern fn puts(text:*u8)->i32=\\"puts\\";fn main(argc:i32,argv:**u8)->i32{puts(\\"ASM-built C backend\\");return 0i32;}";
var source:CrustSource=make CrustSource{path:"application",bytes:text,size:native_strlen(text),identity:1u64};
var parsed:*CrustUnit=null(*CrustUnit);
var success:bool=crust_read(&target,&source,&parsed) && crust_collect(&target) && crust_resolve(&target) && crust_check(&target) && stage_names(null(*StageName),&target);
var name:*CrustName=crust_try_intern(&target,"main",4usize);
var entry:*CrustSymbol=crust_map_get(&target.globals,name as usize) as *CrustSymbol;
var options:CBackendOptions=make CBackendOptions{mode:0u32,output:host_path(run,"program"),symbols:null(*u8),cflags:null(**u8),cflag_count:0usize,ldflags:null(**u8),ldflag_count:0usize};
if success{success=asm_c_backend_build(&target,entry->decl,&options)==0i32;};
stage_diagnostic(run->context,&target);
crust_context_destroy(&target);
if !success{return 1i32;};
return 0i32;
"""
    )
    run([seed, root], cwd="/")
    assert run([package / "program"]).stdout == b"ASM-built C backend\n"
