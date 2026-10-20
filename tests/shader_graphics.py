# SPDX-License-Identifier: Apache-2.0
"""Check graphics execution models, interfaces, and rejected contracts."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def check_graphics(host, compiler, llvm, tools, work, environment):
    run = host.run
    example = ROOT / "examples/graphics/main.crs"
    output = work / "graphics"
    selected = host.root(example)
    source = selected.read_text(encoding="utf-8")
    for name in ("vertex.crs", "fragment.crs"):
        source = source.replace(
            f'host_path(run, "{name}")',
            json.dumps(host.path(example.parent / name), ensure_ascii=False),
        )
    selected.write_text(source, encoding="utf-8")
    command = [compiler, selected, llvm, tools / "spirv-val", output]
    run(command, env=environment)
    vertex = run([tools / "spirv-dis", output.name + ".vert.spv"], cwd=output.parent).stdout
    fragment = run([tools / "spirv-dis", output.name + ".frag.spv"], cwd=output.parent).stdout
    for token in (b"OpEntryPoint Vertex", b"BuiltIn Position", b"BuiltIn VertexIndex"):
        assert token in vertex, token
    for token in (b"OpEntryPoint Fragment", b"OriginUpperLeft", b"Location 0"):
        assert token in fragment, token
    fixture = work / "graphics-contract.crs"
    cases = (
        ("config.stage = 3u32;", "invalid shader stage"),
        ("config.local_size = 1u32;", "zero dispatch dimensions"),
        ("config.execution = SHADER_CHECKED;", "RAW execution"),
        ("inputs[0usize].components = 3u32;", "builtin interface type"),
        ("inputs[2usize].name = inputs[0usize].name;", "duplicate shader interface"),
        ("config.interfaces = null(*ShaderInterface);", "interfaces are missing"),
    )
    for statement, diagnostic in cases:
        fixture.write_text(
            source.replace("var context:", statement + "\nvar context:", 1), encoding="utf-8"
        )
        result = run(
            [compiler, fixture, llvm, tools / "spirv-val", output],
            expected=1,
            env=environment,
        )
        assert diagnostic.encode() in result.stdout + result.stderr, diagnostic
