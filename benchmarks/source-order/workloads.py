# SPDX-License-Identifier: Apache-2.0
"""Equivalent raw-language programs for the application compilation gate."""

from pathlib import Path


def program(directory, name, c, crust, functions, expected_stdout):
    paths = {"c": directory / (name + ".c"), "crust": directory / (name + ".crs")}
    paths["c"].write_text(c)
    paths["crust"].write_text(crust)
    return {
        "name": name,
        "paths": paths,
        "library": False,
        "functions": functions,
        "expected_stdout": expected_stdout,
    }


def arrays(directory):
    return program(
        directory,
        "arrays",
        """typedef unsigned long Word;
extern int puts(const char *text);
static Word sum(Word *values, Word count) {
    Word total = 0;
    for (Word i = 0; i < count; ++i) total += values[i] * (i + 1);
    return total;
}
int main(int argc, char **argv) {
    Word values[4] = {3, 5, 7, 11};
    if (sum(values, 4) != 78) return 1;
    if (puts("arrays: ok") < 0) return 2;
    return 0;
}
""",
        """extern fn puts(text:*u8)->i32="puts";
fn sum(values:*u64,count:usize)->u64 {
    var total:u64=0u64;
    var i:usize=0usize;
    while i<count { total=total+values[i]*(i as u64+1u64); i=i+1usize; }
    return total;
}
fn main(argc:i32,argv:**u8)->i32 {
    var values:[u64;4]=make [u64;4]{3u64,5u64,7u64,11u64};
    if sum(&values[0usize],4usize)!=78u64 {return 1i32;}
    if puts("arrays: ok")<0i32 {return 2i32;}
    return 0i32;
}
""",
        2,
        "arrays: ok\n",
    )


def branches(directory, count):
    c = [
        "typedef unsigned long Word;\nextern int puts(const char *);\n",
        "static Word work(Word value) {\n",
    ]
    crust = ['extern fn puts(text:*u8)->i32="puts";\n', "fn work(value:u64)->u64 {\n"]
    expected = 0
    for i in range(count):
        mask, add = i % 251 + 1, i % 37 + 1
        c.append(f"if ((value & {mask}ul) == 0) value += {add}ul; else value ^= {add}ul;\n")
        crust.append(
            f"if (value & {mask}u64)==0u64 {{value=value+{add}u64;}} else {{value=value ^ {add}u64;}}\n"
        )
        expected = expected + add if expected & mask == 0 else expected ^ add
    c.append(
        "return value; }\n"
        f"int main(int argc,char **argv) {{if (work(0)!={expected}ul) return 1; "
        'if (puts("branches: ok")<0) return 2; return 0;}\n'
    )
    crust.append(
        "return value;}\n"
        f"fn main(argc:i32,argv:**u8)->i32 {{if work(0u64)!={expected}u64 {{return 1i32;}} "
        'if puts("branches: ok")<0i32 {return 2i32;} return 0i32;}\n'
    )
    return program(directory, f"branches-{count}", "".join(c), "".join(crust), 2, "branches: ok\n")


def records(directory, count):
    c = ["typedef unsigned long Word;\nextern int puts(const char *);\n"]
    crust = ['extern fn puts(text:*u8)->i32="puts";\n']
    for i in range(count):
        c.append(
            f"struct Value{i} {{Word slots[4]; struct Value{i} *next;}};\n"
            f"Word get{i}(struct Value{i} *value) {{return value->slots[2];}}\n"
        )
        crust.append(
            f"record Value{i} {{slots:[u64;4]; next:*Value{i};}}\n"
            f"fn get{i}(value:*Value{i})->u64 {{return (*value).slots[2usize];}}\n"
        )
    last = count - 1
    c.append(
        f"int main(int argc,char **argv) {{struct Value{last} value={{{{1,2,3,4}},0}}; "
        f"if (get{last}(&value)!=3) return 1; "
        'if (puts("records: ok")<0) return 2; return 0;}\n'
    )
    crust.append(
        f"fn main(argc:i32,argv:**u8)->i32 {{var value:Value{last}=make Value{last}{{"
        f"slots:make [u64;4]{{1u64,2u64,3u64,4u64}},next:null(*Value{last})}}; "
        f"if get{last}(&value)!=3u64 {{return 1i32;}} "
        'if puts("records: ok")<0i32 {return 2i32;} return 0i32;}\n'
    )
    return program(
        directory, f"records-{count}", "".join(c), "".join(crust), count + 1, "records: ok\n"
    )


def generate(directory):
    directory = Path(directory)
    return [
        arrays(directory),
        *[branches(directory, count) for count in (32, 512)],
        *[records(directory, count) for count in (32, 512)],
    ]
