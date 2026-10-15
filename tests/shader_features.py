# SPDX-License-Identifier: Apache-2.0
"""Check shader requirements against reachable source features."""


def check_features(run, command, tools, source, output, environment):
    for program in (
        "fn compute()->unit {}",
        "fn unused()->f32{return shader_sqrt(2f32);} fn compute()->unit {}",
        "fn twice(n:u32)->u32{return n*2u32;} fn compute()->unit {shader_require(twice(shader_global_x())<8u32);}",
    ):
        source.write_text(program)
        run(command, env=environment)
        assembly = run([tools / "spirv-dis", output]).stdout
        for absent in (
            b"OpTypeFloat",
            b" Sqrt ",
            b"RoundingModeRTE",
            b"SignedZeroInfNanPreserve",
            b"OpTypeImage",
        ):
            assert absent not in assembly, absent
