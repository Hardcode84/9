# SPDX-License-Identifier: Apache-2.0
"""Compose device parsing, an AST edit, emission and publication."""

import struct


def check_composition(run, compiler, root, llvm, tools, work, native, environment):
    text = root.read_text()
    begin = text.index("var ok: bool =")
    end = text.index("if !ok {", begin)
    text = (
        text[:begin]
        + """
var helper_bytes:*u8="fn amount()->f32{return 2f32;}";
var helper:CrustSource=make CrustSource{path:"helper",bytes:helper_bytes,size:30usize,identity:99u64};
var helper_unit:*CrustUnit=null(*CrustUnit);
config.llvm_directory=null(*u8);
config.validator=null(*u8);
var builtins:*CrustUnit=shader_prepare(&context,&config,100u64);
var unit_value:*CrustUnit=null(*CrustUnit);
var ir:CrustSource=uninit;
var ok:bool=builtins!=null(*CrustUnit) && crust_read(&context,&helper,&helper_unit);
if ok {
    // A root-selected transform changes the helper name before resolution.
    helper_unit -> declarations -> name = crust_try_intern(&context,"offset",6usize);
    ok=cache_read(&context,source_path,&source) && crust_read(&context,&source,&unit_value) &&
       crust_collect(&context) && crust_resolve(&context) && crust_check(&context) &&
       shader_emit(&context,&config,builtins,&ir);
    if ok {
        config.llvm_directory=run -> argv[0usize];
        config.validator=run -> argv[1usize];
        ok=shader_publish(&context,&config,&ir,run -> argv[2usize]);
    }
};
"""
        + text[end:]
    )
    # This root is two directories below the repository, like the tutorial.
    build_root = work / "composition.crs"
    build_root.write_text(text)
    source = work / "composition-device.crs"
    source.write_text(
        "fn compute()->unit{var i:u32=shader_global_x();values_store(i,values_load(i)+offset());}"
    )
    output = work / "composition.spv"
    run([compiler, build_root, llvm, tools / "spirv-val", output, source], env=environment)
    expected = work / "composition.expected"
    expected.write_bytes(struct.pack("<4f4I", 3, 4, 5, 6, 0, 0, 0, 0))
    run([native, output, expected], env=environment)
