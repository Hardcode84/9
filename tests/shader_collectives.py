# SPDX-License-Identifier: Apache-2.0
"""Check collective helpers, bounded loops and failed-lane participation."""

import struct


def check_collectives(run, command, source, output, work, native, environment):
    helper = "fn sync()->unit{shader_barrier();} fn nested()->unit{sync();}"
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
            "fn rounds()->unit{var i:u32=0u32;while i<2u32{shader_barrier();i=i+1u32;}}"
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
    for program, values, status in cases:
        source.write_text(program)
        run(command, env=environment)
        expected = work / "collective.expected"
        expected.write_bytes(struct.pack("<4f4I", *values, *status))
        run([native, output, expected], env=environment)
    rejected = [
        helper + "fn compute()->unit{if shader_local_x()==0u32{nested();}}",
        "fn sync()->unit{if shader_local_x()==0u32{return;}shader_barrier();}fn compute()->unit{sync();}",
        "fn sync()->bool{shader_barrier();return true;}fn compute()->unit{sync();}",
        helper + "fn compute()->unit{var i:u32=shader_local_x();while i<4u32{sync();i=i+1u32;}}",
        helper
        + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();if shader_local_x()==0u32{break;}i=i+1u32;}}",
        helper
        + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();if shader_local_x()==0u32{continue;}i=i+1u32;}}",
        helper
        + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();i=shader_local_x();i=i+1u32;}}",
        helper
        + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();(i)=shader_local_x();i=i+1u32;}}",
        helper + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();return;i=i+1u32;}}",
        helper
        + "fn compute()->unit{if shader_local_x()==0u32{var i:u32=0u32;while i<4u32{sync();i=i+1u32;}}}",
        helper + "fn compute()->unit{var i:u32=0u32;while i<4u32{sync();i=i+2u32;}}",
    ]
    previous = output.read_bytes()
    for program in rejected:
        source.write_text(program)
        result = run(command, expected=1, env=environment)
        assert b"collective" in result.stdout + result.stderr, result
        assert output.read_bytes() == previous
