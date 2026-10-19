<!-- SPDX-License-Identifier: Apache-2.0 -->

# Vulkan vertex and fragment shaders

Run from the Crust repository:

```sh
build/crust examples/graphics/main.crs "$LLVM_DIRECTORY" \
  "$SPIRV_VAL" build/triangle
```

The root writes `build/triangle.vert.spv` and `build/triangle.frag.spv`.
Both files pass Vulkan 1.2 validation before publication. The caller supplies
the graphics pipeline, descriptor bindings, attachments, and draw commands.

Set `ShaderConfig.stage` to `SHADER_VERTEX` or `SHADER_FRAGMENT`. Graphics
stages require `SHADER_RAW`, zero `invocations`, and zero `local_size`.
Compute stages use `SHADER_COMPUTE` and an empty interface table. Workgroup
storage and invocation/barrier builtins require a compute stage. The WGSL
emitter accepts compute stages; it rejects graphics stages before emission.

Each `ShaderInterface` defines one input or output. Its kind is
`SHADER_BUFFER_F32` or `SHADER_BUFFER_U32`, with one to four components.
The generated accessors are `name_load(component)` for inputs and
`name_store(component, value)` for outputs. The component must be in range.
Write each required output component on every path through the entry.

Use `SHADER_LOCATION` and `slot` for user interfaces. Input and output
locations have separate namespaces. Match type, width, location, and
interpolation between stages. `SHADER_SMOOTH` uses perspective interpolation;
`SHADER_NOPERSPECTIVE` uses screen-space interpolation; `SHADER_FLAT` uses
the provoking vertex. Integer fragment inputs require flat interpolation.

Supported builtins have zero slot and `SHADER_SMOOTH`:

| Semantic | Stage and direction | Type |
|---|---|---|
| `SHADER_POSITION` | Vertex output | Four f32 components |
| `SHADER_VERTEX_INDEX` | Vertex input | One u32 component |
| `SHADER_INSTANCE_INDEX` | Vertex input | One u32 component |
| `SHADER_FRAG_COORD` | Fragment input | Four f32 components |

`shader_discard()` discards the current fragment. It is available only in
fragment shaders. Buffer and image resource access follows the
[shader resource contract](../shader/README.md).
