# SPDX-License-Identifier: Apache-2.0
"""Execute unsigned shader atomics and check their memory scopes."""

import re
import struct

from shader_wgsl import translate_wgsl


def check_atomics(run, compiler, root, llvm, tools, work, native, environment, validator):
    template = root.read_text().replace('"../../', f'"{root.parents[2]}/')
    fixture = work / "atomics-main.crs"
    source = work / "atomics.crs"
    output = work / "atomics.spv"
    expected = work / "atomics.expected"
    program = """fn compute()->unit {
        var lane:u32=shader_local_x();
        if lane==0u32 { DATA_store(0u32,0u32); DATA_store(1u32,100u32);
                       DATA_store(2u32,0u32); DATA_store(3u32,0u32); }
        shader_barrier();
        DATA_atomic_add(0u32,1u32);
        DATA_atomic_min(1u32,lane+5u32);
        DATA_atomic_max(2u32,lane+5u32);
        DATA_atomic_or(3u32,1u32 << lane);
        var previous:u32=DATA_atomic_or(3u32,1u32 << lane);
        shader_require((previous & (1u32 << lane)) != 0u32);
        shader_barrier();
        if lane==0u32 {
            var old:u32=DATA_atomic_exchange(3u32,9u32);
            shader_require(old==15u32);
        }
        shader_barrier();
        OUTPUT
    }"""
    for shared in (False, True):
        mode = "shared-u32" if shared else None
        text = template
        if not shared:
            text = text.replace("kind: SHADER_BUFFER_F32,", "kind: SHADER_BUFFER_U32,", 1)
        fixture.write_text(text)
        data = "scratch" if shared else "values"
        store = "values_store(lane,scratch_uniform_load(0u32) as f32);" if shared else ""
        source.write_text(program.replace("DATA", data).replace("OUTPUT", store))
        command = [compiler, fixture, llvm, tools / "spirv-val", output, source]
        if mode:
            command.append(mode)
        run(command, env=environment)
        assembly = run([tools / "spirv-dis", output.name], cwd=output.parent).stdout.decode()
        for token in (
            "OpAtomicIAdd",
            "OpAtomicUMin",
            "OpAtomicUMax",
            "OpAtomicExchange",
            "OpAtomicOr",
        ):
            assert token in assembly, token
        constants = dict(re.findall(r"(%\w+) = OpConstant %\w+ (\d+)", assembly))
        operands = re.findall(r"OpAtomic\w+ %\w+ %\w+ (%\w+) (%\w+)", assembly)
        assert operands
        for scope, semantics in operands:
            assert constants[scope] == ("2" if shared else "1")
            # AcquireRelease plus the storage class selected for this resource.
            assert int(constants[semantics]) == 8 | (256 if shared else 64)
        payload = struct.pack("<4f", *([4.0] * 4)) if shared else struct.pack("<4I", 4, 5, 8, 9)
        expected.write_bytes(payload + struct.pack("<4I", 0, 0, 0, 0))
        run([native, output, expected], env=environment)
        wgsl = work / "atomics.wgsl"
        command[2] = "wgsl"
        command[4] = wgsl
        run(command, env=environment)
        assert "atomic<u32>" in wgsl.read_text()
        if validator:
            translated = work / "atomics-wgsl.spv"
            translate_wgsl(run, validator, wgsl, translated, environment)
            run([native, translated, expected], env=environment)
        command[2] = llvm
        command[4] = output
        cases = [
            (
                f"fn compute()->unit {{ {data}_atomic_or(4u32,1u32); }}",
                struct.pack("<4f4I", 1, 2, 3, 4, 1, 1, 1, 1),
            ),
            (
                program.replace("DATA", data)
                .replace("OUTPUT", store)
                .replace(
                    f"{data}_atomic_add(0u32,1u32);",
                    f"shader_require(lane!=2u32); {data}_atomic_add(0u32,1u32);",
                )
                .replace("old==15u32", "old==11u32"),
                (struct.pack("<4f", 3, 3, 3, 3) if shared else struct.pack("<4I", 3, 5, 8, 9))
                + struct.pack("<4I", 0, 0, 1, 0),
            ),
        ]
        for code, result in cases:
            source.write_text(code)
            expected.write_bytes(result)
            run(command, env=environment)
            run([native, output, expected], env=environment)
            wgsl_command = command.copy()
            wgsl_command[2] = "wgsl"
            wgsl_command[4] = wgsl
            run(wgsl_command, env=environment)
            if validator:
                translate_wgsl(run, validator, wgsl, translated, environment)
                run([native, translated, expected], env=environment)
