# SPDX-License-Identifier: Apache-2.0
"""Execute barrier helpers, loops and failed-lane participation."""

import re
import struct

from shader_wgsl import translate_wgsl


def check_collectives(
    run, command, source, output, work, native, environment, wgsl_validator=None, spirv_tools=None
):
    helper = "fn sync()->unit{shader_all_memory_barrier();} fn nested()->unit{sync();}"
    cases = [
        (helper + "fn compute()->unit{nested();}", [1, 2, 3, 4], [0] * 4),
        (
            helper
            + """fn compute()->unit {
            var lane:u32=shader_local_x();
            var round:u32=0u32;
            while round<3u32 {
                scratch_store(lane,values_load(lane)+1f32);
                nested();
                values_store(lane,scratch_load(lane^1u32));
                sync();
                round=round+1u32;
            }
        }""",
            [5, 4, 7, 6],
            [0] * 4,
        ),
        (
            helper
            + """fn compute()->unit {
            var lane:u32=shader_local_x();
            var round:u32=0u32;
            while round<3u32 {
                shader_require(lane!=2u32);
                scratch_store(lane,values_load(lane)+1f32);
                nested();
                values_store(lane,scratch_load(lane^1u32));
                sync();
                round=round+1u32;
            }
        }""",
            [5, 4, 3, 0],
            [0, 0, 1, 0],
        ),
        (
            "fn rounds()->unit{var i:u32=0u32;while i<2u32{shader_all_memory_barrier();i=i+1u32;}}"
            "fn compute()->unit{rounds();}",
            [1, 2, 3, 4],
            [0] * 4,
        ),
    ]
    cases.extend(
        [
            (
                helper + "fn compute()->unit{var i:u32=0u32;while i<0u32{sync();i=i+1u32;}}",
                [1, 2, 3, 4],
                [0] * 4,
            ),
            (
                helper
                + """fn compute()->unit {
            var lane:u32=shader_local_x();
            var outer:u32=0u32;
            while outer<2u32 {
                var inner:u32=0u32;
                while inner<2u32 {
                    scratch_store(lane,values_load(lane)+1f32);
                    nested();
                    values_store(lane,scratch_load(lane^1u32));
                    sync();
                    inner=inner+1u32;
                }
                outer=outer+1u32;
            }
        }""",
                [5, 6, 7, 8],
                [0] * 4,
            ),
        ]
    )
    cases.extend(
        [
            (
                "fn sync(n:u32)->bool{var i:u32=0u32;while i<n{shader_workgroup_barrier();i=i+2u32;}return true;}"
                "fn compute()->unit{if sync(4u32){values_store(shader_local_x(),7f32);}}",
                [7] * 4,
                [0] * 4,
            ),
            (
                "fn compute()->unit{if 1u32==2u32{return;}shader_workgroup_barrier();values_store(shader_local_x(),7f32);}",
                [7] * 4,
                [0] * 4,
            ),
        ]
    )
    for failed in (False, True):
        cases.append(
            (
                """fn compute()->unit {
                var lane:u32=shader_local_x();
                if lane==0u32 { scratch_store(3u32,3f32); }
                FAILURE
                while scratch_uniform_load(3u32)>0f32 {
                    values_store(lane,values_load(lane)+1f32);
                    shader_all_memory_barrier();
                    if lane==0u32 { scratch_store(3u32,scratch_load(3u32)-1f32); }
                }
            }""".replace(
                    "FAILURE", "shader_require(lane!=2u32);" if failed else ""
                ),
                [4, 5, 3 if failed else 6, 7],
                [0, 0, int(failed), 0],
            )
        )
    cases.append(
        (
            "fn compute()->unit{var x:f32=scratch_uniform_load(4u32);values_store(shader_local_x(),x);}",
            [1, 2, 3, 4],
            [1] * 4,
        )
    )
    cases += [
        (
            program.replace("shader_all_memory_barrier()", "shader_workgroup_barrier()"),
            values,
            status,
        )
        for program, values, status in cases
    ]
    for program, values, status in cases:
        source.write_text(program)
        run(command, env=environment)
        expected = work / "collective.expected"
        expected.write_bytes(struct.pack("<4f4I", *values, *status))
        run([native, output, expected], env=environment)
        if wgsl_validator:
            wgsl_command = command.copy()
            wgsl_command[2] = "wgsl"
            wgsl = work / "collective.wgsl"
            wgsl_command[4] = wgsl
            run(wgsl_command, env=environment)
            translated = work / "collective-wgsl.spv"
            translate_wgsl(run, wgsl_validator, wgsl, translated, environment)
            run([native, translated, expected], env=environment)
    source.write_text(
        "fn compute()->unit{shader_workgroup_barrier();var x:f32=scratch_uniform_load(0u32);values_store(shader_local_x(),x);}"
    )
    run(command, env=environment)
    assembly = run(
        [spirv_tools / "spirv-dis", output.name], env=environment, cwd=output.parent
    ).stdout.decode()
    constants = dict(re.findall(r"(%\w+) = OpConstant %\w+ (\d+)", assembly))
    barriers = re.findall(r"OpControlBarrier (%\w+) (%\w+) (%\w+)", assembly)
    assert barriers and all(
        tuple(constants[item] for item in barrier) == ("2", "2", "264") for barrier in barriers
    ), assembly
