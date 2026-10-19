# SPDX-License-Identifier: Apache-2.0
"""Exercise explicit raw execution and buffer layout contracts."""

import struct


def check_policy(run, compiler, root, llvm, tools, work, native, environment):
    script = root.read_text(encoding="utf-8").replace(
        "execution: SHADER_CHECKED", "execution: SHADER_RAW"
    )
    script = script.replace("layout: SHADER_FIXED", "layout: SHADER_UNBOUNDED", 1)
    script = script.replace("length: 4u32", "length: 0u32", 1)
    selected = work / "raw-root.crs"
    selected.write_text(script, encoding="utf-8")
    source, output, expected = (work / name for name in ("raw.crs", "raw.spv", "raw.expected"))
    command = [compiler, selected, llvm, tools / "spirv-val", output, source]
    source.write_text("fn compute()->unit {}")
    run(command, env=environment)
    assembly = run([tools / "spirv-dis", output.name], cwd=output.parent).stdout
    for absent in (
        b"DescriptorSet",
        b"Binding",
        b"sp_failed",
        b"OpTypeFloat",
        b"OpCapability Int8",
    ):
        assert absent not in assembly, absent
    expected.write_bytes(struct.pack("<4f4I", 1, 2, 3, 4, 0, 0, 0, 0))
    run([native, output, expected], env=environment)
    source.write_text(
        "fn compute()->unit {var i:u32=shader_local_x();scratch_store(i,values_load(i)+2f32);shader_barrier();values_store(i,scratch_load(i));}"
    )
    run(command, env=environment)
    assembly = run([tools / "spirv-dis", output.name], cwd=output.parent).stdout
    assert b"sp_failed" not in assembly and b"init_scratch" not in assembly
    expected.write_bytes(struct.pack("<4f4I", 3, 4, 5, 6, 0, 0, 0, 0))
    run([native, output, expected], env=environment)
    source.write_text("fn compute()->unit {shader_require(true);}")
    result = run(command, expected=1, env=environment)
    assert b"checked execution" in result.stdout + result.stderr
    selected.write_text(
        script.replace("execution: SHADER_RAW", "execution: SHADER_CHECKED"), encoding="utf-8"
    )
    result = run(command, expected=1, env=environment)
    assert b"layout/length" in result.stdout + result.stderr
