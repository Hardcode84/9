# SPDX-License-Identifier: Apache-2.0

"""Compare the Crust Vulkan declarations with the selected C headers."""

import json
import re
import struct
from pathlib import Path

from prepare import compile_package

BINDINGS = Path(__file__).with_name("bindings.crs")


def check_abi(
    run, build, work, cc, flags, compile_native=compile_package, profile="linux", path=str
):
    text = BINDINGS.read_text(encoding="utf-8")
    c_values, crust_values, names = [], [], []

    def add(name, c, crust):
        names.append(name)
        c_values.append(c)
        crust_values.append(crust)

    records = re.findall(r"record (\w+)\s*\{([^}]+)\}", text)
    for name, body in records:
        add(f"sizeof({name})", f"sizeof({name})", f"sizeof({name})")
        add(
            f"alignof({name})",
            f"offsetof(struct {{ char pad; {name} value; }}, value)",
            f"alignof({name})",
        )
        for field, kind in re.findall(r"(\w+):\s*((?:\[[^]]+\])|[^;]+);", body):
            add(
                f"offsetof({name}, {field})",
                f"offsetof({name}, {field})",
                f"offsetof({name}, {field})",
            )
            add(
                f"sizeof({name}.{field})",
                f"sizeof((({name} *)0)->{field})",
                f"sizeof({kind.strip()})",
            )
    for name in re.findall(r"const (VK_\w+):", text):
        add(name, name, f"{name} as usize")
    c = work / "abi.c"
    c.write_text(
        "#include <stddef.h>\n#include <stdio.h>\n#include <vulkan/vulkan.h>\n"
        "int main(void) {\nconst size_t values[] = {\n"
        + ",\n".join(c_values)
        + "\n};\nsize_t i; for(i=0;i<sizeof(values)/sizeof(values[0]);++i) "
        '{if(printf("%zu\\n",values[i])<0)return 1;}\nreturn 0;\n}\n'
    )
    executable = work / "abi-c"
    run([*cc, *flags, c.name, "-o", executable.name], cwd=work)
    expected = b"".join(
        struct.pack("<Q", int(value)) for value in run([executable]).stdout.splitlines()
    )
    source = work / "abi.crs"
    source.write_text(
        'extern fn close(file:*u8)->i32="fclose";\n'
        'extern fn write(bytes:*u8,size:usize,count:usize,file:*u8)->usize="fwrite";\n'
        "fn main(argc:i32,argv:**u8)->i32{\n"
        "if argc!=2i32{return 2i32;}\n"
        f"var values:[usize;{len(names)}]=make [usize;{len(names)}]{{\n"
        + ",\n".join(crust_values)
        + '\n};\nvar file:*u8=file_open(argv[1usize],"wb");\n'
        "if file==null(*u8){return 2i32;}\n"
        f"var good:bool=write(&values as *u8,sizeof([usize;{len(names)}]),1usize,file)==1usize;\n"
        "if close(file)!=0i32{return 2i32;}\nif !good{return 1i32;}return 0i32;\n}\n"
    )
    manifest = work / "abi-package.crs"
    sources = (BINDINGS, source, BINDINGS.with_name("file_" + profile + ".crs"))
    manifest.write_text(
        "".join(
            f"stage_source(stage,{json.dumps(path(item), ensure_ascii=False)});\n"
            for item in sources
        )
        + 'stage_export(stage,"main");\n',
        encoding="utf-8",
    )
    executable = work / "abi-crust"
    compile_native(build, manifest, executable, ["-O2"], [])
    output = work / "abi.bin"
    run([executable, output])
    actual = output.read_bytes()
    assert len(expected) == len(actual) == len(names) * 8
    for index, name in enumerate(names):
        begin = index * 8
        assert actual[begin : begin + 8] == expected[begin : begin + 8], name
    print(f"Vulkan ABI: {len(records)} records, {len(names)} layout/constant checks passed")
