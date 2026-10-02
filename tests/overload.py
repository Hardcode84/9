#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check exact overload selection and the native source ABI boundary."""

import argparse
import fnmatch
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def c_backend_sources():
    return [
        ROOT / "api" / (name + ".crs") for name in ("crust0", "crust0_host", "crust0_stage")
    ] + [
        ROOT / "stages/c" / (name + ".crs")
        for name in ("model", "base", "types", "emit", "driver", "program", "main")
    ]


def program(body, declarations=""):
    return declarations + "\nfn main(argc:i32,argv:**u8)->i32 {\n" + body + "\nreturn 0i32;\n}\n"


def runtime_cases():
    scalars = ("bool", "u8", "i8", "u16", "i16", "u32", "i32", "u64", "i64", "usize", "isize")
    declarations = "\n".join(
        f"fn select(value:{kind})->i32 {{return {index}i32;}}" for index, kind in enumerate(scalars)
    )
    checks = "\n".join(
        f"if select({'true' if kind == 'bool' else '1' + kind})!={index}i32 {{return 1i32;}}"
        for index, kind in enumerate(scalars)
    )
    fields = " ".join(f"field{index:04}:{'u64' if index % 2 else 'u32'};" for index in range(1024))
    initializers = ",".join(
        f"field{index:04}:{index}{'u64' if index % 2 else 'u32'}" for index in range(1024)
    )
    long_name = "Record" + "x" * 8192
    return [
        (
            "long-nominal-type-keys",
            program(
                f"var a:*{long_name}A=null(*{long_name}A);"
                f"var b:*{long_name}B=null(*{long_name}B);"
                "if pick(a)!=1i32 || pick(b)!=2i32 || pick(a)!=1i32 {return 1i32;}",
                f"record {long_name}A{{value:u8;}} record {long_name}B{{value:u8;}}"
                f"fn pick(value:*{long_name}A)->i32{{return 1i32;}}"
                f"fn pick(value:*{long_name}B)->i32{{return 2i32;}}",
            ),
            b"",
        ),
        ("scalar-types-and-native-width-aliases", program(checks, declarations), b""),
        (
            "signed-minimum-and-group",
            program(
                "if tag(-128i8)!=8i32 || tag((-2147483648i32))!=32i32 {return 1i32;}",
                "fn tag(value:i8)->i32{return 8i32;} fn tag(value:i32)->i32{return 32i32;}",
            ),
            b"",
        ),
        (
            "arity",
            program(
                "if pick()!=0i32 || pick(1u8)!=1i32 || pick(1u8,2u8)!=2i32{return 1i32;}",
                "fn pick()->i32{return 0i32;} fn pick(a:u8)->i32{return 1i32;} "
                "fn pick(a:u8,b:u8)->i32{return 2i32;}",
            ),
            b"",
        ),
        (
            "same-layout-nominal-pointers",
            program(
                "var a:A=make A{x:3u64}; var b:B=make B{x:5u64}; "
                "if pick(&a)!=13u64 || pick(&b)!=25u64{return 1i32;}",
                "record A{x:u64;} record B{x:u64;} "
                "fn pick(p:*A)->u64{return (*p).x+10u64;} "
                "fn pick(p:*B)->u64{return (*p).x+20u64;}",
            ),
            b"",
        ),
        (
            "array-extent-and-pointer-depth",
            program(
                "if pick(null(*[u8;3]))!=3i32 || pick(null(*[u8;4]))!=4i32 "
                "|| pick(null(**u8))!=2i32{return 1i32;}",
                "fn pick(p:*[u8;3])->i32{return 3i32;} fn pick(p:*[u8;4])->i32{return 4i32;} "
                "fn pick(p:**u8)->i32{return 2i32;}",
            ),
            b"",
        ),
        (
            "array-index-field-cast-inference",
            program(
                "var values:[u8;2]=make [u8;2]{1u8,2u8}; var box:Box=make Box{x:3u32}; "
                "if pick(values[1usize])!=8i32 || pick(box.x)!=32i32 "
                "|| pick(7u64 as u8)!=8i32{return 1i32;}",
                "record Box{x:u32;} fn pick(value:u8)->i32{return 8i32;} "
                "fn pick(value:u32)->i32{return 32i32;}",
            ),
            b"",
        ),
        (
            "large-record-constructor-field-types",
            program(
                "var box:Many=make Many{" + initializers + "}; "
                "if pick(box.field0000)!=1000u64 || pick(box.field1023)!=3023u64{return 1i32;}",
                "record Many{" + fields + "} "
                "fn pick(value:u32)->u64{return (value as u64)+1000u64;} "
                "fn pick(value:u64)->u64{return value+2000u64;}",
            ),
            b"",
        ),
        (
            "function-type-result-key",
            program(
                "if pick(first)!=32i32 || pick(second)!=64i32{return 1i32;}",
                "fn first(x:u8)->u32{return x as u32;} fn second(x:u8)->u64{return x as u64;} "
                "fn pick(f:fn(u8)->u32)->i32{return 32i32;} "
                "fn pick(f:fn(u8)->u64)->i32{return 64i32;}",
            ),
            b"",
        ),
        (
            "function-values-expected-contexts",
            program(
                "var selected:fn(u64)->u64=increment; if selected(2u64)!=3u64{return 1i32;} "
                "selected=increment; if choose()(3u64)!=4u64 || apply(increment,4u64)!=5u64{return 2i32;}",
                "fn increment(x:u32)->u32{return x+1u32;} fn increment(x:u64)->u64{return x+1u64;} "
                "fn choose()->fn(u64)->u64{return increment;} "
                "fn apply(f:fn(u64)->u64,x:u64)->u64{return f(x);}",
            ),
            b"",
        ),
        (
            "function-values-in-constant-and-field",
            program(
                "var box:Callback=make Callback{call:increment}; "
                "if callback(3u64)!=4u64 || box.call(4u64)!=5u64{return 1i32;}",
                "record Callback{call:fn(u64)->u64;} "
                "fn increment(x:u32)->u32{return x+1u32;} fn increment(x:u64)->u64{return x+1u64;} "
                "const callback:fn(u64)->u64=increment;",
            ),
            b"",
        ),
        (
            "function-values-in-array",
            program(
                "var callbacks:[fn(u64)->u64;2]=make [fn(u64)->u64;2]{increment,increment}; "
                "if callbacks[1usize](4u64)!=5u64{return 1i32;}",
                "fn increment(x:u32)->u32{return x+1u32;} fn increment(x:u64)->u64{return x+1u64;}",
            ),
            b"",
        ),
        (
            "typed-function-argument-to-overloaded-call",
            program(
                "var selected:fn(u64)->u64=increment; if apply(selected,4u64)!=5u64{return 1i32;}",
                "fn increment(x:u32)->u32{return x+1u32;} fn increment(x:u64)->u64{return x+1u64;} "
                "fn apply(f:fn(u32)->u32,x:u32)->u32{return f(x);} "
                "fn apply(f:fn(u64)->u64,x:u64)->u64{return f(x);}",
            ),
            b"",
        ),
        (
            "recursion-and-forward-signatures",
            program(
                "if total(5u32)!=15u32 || total(5u64)!=15u64{return 1i32;}",
                "fn total(x:u32)->u32{if x==0u32{return 0u32;} return x+total(x-1u32);} "
                "fn total(x:u64)->u64{if x==0u64{return 0u64;} return x+total(x-1u64);}",
            ),
            b"",
        ),
        (
            "source-prototypes-coalesce",
            program(
                "if f(3u32)!=4u32 || f(3u64)!=5u64{return 1i32;}",
                "fn f(x:u32)->u32; fn f(renamed:u32)->u32; fn f(x:u64)->u64; "
                "fn f(value:u32)->u32{return value+1u32;} fn f(value:u64)->u64{return value+2u64;}",
            ),
            b"",
        ),
        (
            "explicit-native-overload",
            program(
                'if output(65i32)!=65i32{return 1i32;} output("native");',
                'extern fn output(text:*u8)->i32="puts"; '
                'extern fn output(value:i32)->i32="putchar";',
            ),
            b"Anative\n",
        ),
        (
            "matching-native-prototypes",
            program(
                'output("native alias");',
                'extern fn output(text:*u8)->i32="puts"; '
                'extern fn output(other:*u8)->i32="puts";',
            ),
            b"native alias\n",
        ),
        (
            "argument-evaluation-order",
            program(
                "select(left(),right());",
                'extern fn emit(code:i32)->i32="putchar"; '
                "fn left()->u32{emit(65i32);return 1u32;} fn right()->u64{emit(66i32);return 1u64;} "
                "fn select(a:u32,b:u64)->unit{emit(67i32);} fn select(a:u64,b:u32)->unit{emit(68i32);}",
            ),
            b"ABC",
        ),
        (
            "deep-valid-pointer-key",
            program(
                "if f(null(" + "*" * 128 + "u8))!=7i32{return 1i32;}",
                "fn f(value:" + "*" * 128 + "u8)->i32{return 7i32;}",
            ),
            b"",
        ),
    ]


def reject_cases():
    return [
        (
            "return-only-overload",
            "fn f(x:u8)->u8{return x;} fn f(x:u8)->u64{return 0u64;}",
            ("result", "return", "signature"),
        ),
        (
            "duplicate-definitions",
            "fn f(x:u8)->u8{return x;} fn f(x:u8)->u8{return x;}",
            ("definition", "duplicate"),
        ),
        (
            "conflicting-import-result",
            "fn f(x:u8)->u8; fn f(x:u8)->u64;",
            ("result", "return", "signature"),
        ),
        (
            "conflicting-native-names",
            'extern fn f(x:i32)->i32="one"; extern fn f(x:i32)->i32="two";',
            ("native", "conflict", "duplicate"),
        ),
        (
            "source-native-abi-conflict",
            'fn f(x:i32)->i32; extern fn f(x:i32)->i32="f";',
            ("ABI", "native", "source"),
        ),
        (
            "native-reserved-prefix",
            'extern fn f()->unit="crust_ov1_private";',
            ("reserved", "prefix"),
        ),
        (
            "no-integer-promotion",
            "fn f(x:u64)->u64{return x;} fn g()->u64{return f(1u32);}",
            ("type", "overload"),
        ),
        (
            "no-arity-match",
            "fn f(x:u64)->u64{return x;} fn g()->u64{return f();}",
            ("argument", "parameter", "arity"),
        ),
        (
            "return-context-does-not-select",
            "fn f(x:u32)->u32{return x;} fn f(x:u64)->u64{return x;} fn g()->u64{return f(1u32);}",
            ("type", "return"),
        ),
        (
            "unresolved-function-argument",
            "fn f(x:u32)->u32{return x;} fn f(x:u64)->u64{return x;} "
            "fn apply(cb:fn(u32)->u32,x:u32)->u32{return cb(x);} fn apply(cb:fn(u64)->u64,x:u64)->u64{return cb(x);} "
            "fn g()->u64{return apply(f,1u64);}",
            ("type", "overload", "ambiguous"),
        ),
        (
            "missing-function-value-result",
            "fn f(x:u32)->u32{return x;} fn f(x:u64)->u64{return x;} "
            "fn g()->unit{var selected:fn(u64)->u32=f;}",
            ("result", "type", "overload"),
        ),
        (
            "local-cannot-hide-source-family",
            "fn f(x:u32)->u32{return x;} fn g()->unit{var f:u32=1u32;}",
            ("hide", "shadow", "name", "duplicate"),
        ),
        (
            "parameter-cannot-hide-source-family",
            "fn f(x:u32)->u32{return x;} fn g(f:u32)->u32{return f;}",
            ("hide", "shadow", "name", "duplicate"),
        ),
        (
            "record-function-name-collision",
            "record f{x:u32;} fn f(x:u32)->u32{return x;}",
            ("name", "duplicate", "global"),
        ),
        (
            "constant-function-name-collision",
            "const f:u32=0u32; fn f(x:u32)->u32{return x;}",
            ("name", "duplicate", "global"),
        ),
        ("duplicate-record-field", "record Box{x:u32;x:u64;}", ("field", "duplicate")),
        (
            "duplicate-constructor-field",
            "record Box{x:u32;} fn f()->unit{var box:Box=make Box{x:1u32,x:2u32};}",
            ("field", "duplicate"),
        ),
        (
            "unknown-constructor-field",
            "record Box{x:u32;} fn f()->unit{var box:Box=make Box{missing:1u32};}",
            ("field", "unknown"),
        ),
        (
            "unselected-body-still-checked",
            "fn f(x:u32)->u32{return x;} fn f(x:u64)->u64{return missing;}",
            ("unknown", "name"),
        ),
        (
            "missing-nominal-type",
            "fn f(x:*Missing)->u32{return 0u32;}",
            ("unknown", "type", "name"),
        ),
        (
            "aggregate-signature-keeps-seed-rule",
            "record Box{x:u32;} fn f(x:Box)->u32{return x.x;}",
            ("scalar", "parameter", "ABI"),
        ),
        ("type-depth", "fn f(x:" + "*" * 400 + "u8)->unit{}", ("depth", "nesting", "limit")),
        (
            "function-type-depth",
            "fn f(x:" + "fn()->" * 400 + "u8)->unit{}",
            ("depth", "nesting", "limit"),
        ),
        (
            "flat-expression-depth",
            "fn f()->u32{return " + "+".join(["1u32"] * 20000) + ";}",
            ("depth", "nesting", "limit"),
        ),
        (
            "constant-expression-depth",
            "const value:u32=" + "+".join(["1u32"] * 20000) + ";",
            ("depth", "nesting", "limit"),
        ),
    ]


FORMAT_INTERFACE = (
    "fn format(value:u64)->i32; fn format(value:i32)->i32; fn format(text:*u8)->i32;\n"
)
FORMAT_PROVIDER = r"""
extern fn native_write(fd:i32,buffer:*u8,size:usize)->isize="write";
fn bytes(data:*u8,size:usize)->i32 {
    var offset:usize=0usize;
    while offset<size {
        var count:isize=native_write(1i32,data+(offset as isize),size-offset);
        if count<=0isize{return 1i32;}
        offset=offset+(count as usize);
    }
    return 0i32;
}
fn digits(value:u64)->i32 {
    var storage:[u8;20]=uninit;
    var data:*u8=(&storage) as *u8;
    var begin:usize=20usize;
    while true {
        begin=begin-1usize;
        data[begin]=48u8+((value%10u64) as u8);
        value=value/10u64;
        if value==0u64{break;}
    }
    return bytes(data+(begin as isize),20usize-begin);
}
fn format(value:u64)->i32 {
    if digits(value)!=0i32{return 1i32;}
    return bytes("\n",1usize);
}
fn format(value:i32)->i32 {
    var magnitude:u64=value as u64;
    if value<0i32 {
        if bytes("-",1usize)!=0i32{return 1i32;}
        magnitude=0u64-((value as isize) as u64);
    }
    return format(magnitude);
}
fn format(text:*u8)->i32 {
    var count:usize=0usize;
    while text[count]!=0u8{count=count+1usize;}
    if bytes(text,count)!=0i32{return 1i32;}
    return bytes("\n",1usize);
}
"""
FORMAT_CALLER = program(
    'if format("numbers")!=0i32{return 1i32;} '
    "if format(0u64)!=0i32{return 1i32;} "
    "if format(18446744073709551615u64)!=0i32{return 1i32;} "
    "if format(-2147483648i32)!=0i32{return 1i32;} "
    "if format(2147483647i32)!=0i32{return 1i32;}"
)
FORMAT_OUTPUT = b"numbers\n0\n18446744073709551615\n-2147483648\n2147483647\n"


class Failure(Exception):
    pass


class Suite:
    def __init__(self, args, work):
        self.build = args.build.resolve()
        self.compiler = self.build / "crust-overload"
        self.work = work
        self.timeout = args.timeout
        self.flags = [
            "--cflag=-O2",
            *["--cflag=" + flag for flag in args.cflag],
            *["--ldflag=" + flag for flag in args.ldflag],
        ]
        self.commands = 0

    def command(self, command, expected=0):
        result = subprocess.run(
            list(map(str, command)),
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
        )
        self.commands += 1
        correct = result.returncode == expected if expected is not None else result.returncode > 0
        if not correct:
            raise Failure(
                f"{shlex.join(list(map(str, command)))}: status {result.returncode}; expected {expected}\n"
                f"{result.stdout.decode(errors='replace')}\n{result.stderr.decode(errors='replace')}"
            )
        return result

    def source(self, name, source):
        path = self.work / (name + ".crs")
        path.write_text(source)
        return path

    def compile(self, sources, output, options=()):
        return self.command([self.compiler, *self.flags, *options, "-o", output, *sources])

    def execute(self, output, expected):
        result = self.command([output])
        if result.stdout != expected or result.stderr:
            raise Failure(
                f"{output.name}: expected {expected!r}, got {result.stdout!r}; stderr {result.stderr!r}"
            )

    def runtime(self, name, source, expected):
        path = self.source(name, source)
        self.command([self.compiler, "--check", path])
        self.command([self.compiler, "--prepare", path])
        output = self.work / name
        self.compile([path], output)
        self.execute(output, expected)

    def reject(self, name, source, expected):
        path = self.source(name, source)
        for endpoint in ("--check", "--prepare"):
            result = self.command([self.compiler, endpoint, "--library", path], expected=1)
            if (
                result.stdout
                or str(path).encode() not in result.stderr
                or not any(word.lower().encode() in result.stderr.lower() for word in expected)
            ):
                raise Failure(
                    f"{name}: expected located diagnostic with {expected!r}; got {result.stderr!r}"
                )

    def symbols(self, path, defined=True):
        result = self.command(
            [
                "nm",
                "-g",
                "--defined-only" if defined else "--undefined-only",
                "--format=posix",
                path,
            ]
        )
        return {
            line.split()[0]
            for line in result.stdout.decode().splitlines()
            if line.split() and (not defined or line.split()[1] in ("T", "D", "R", "B"))
        }

    def boundary(self, name):
        if name == "compile-c-backend":
            backend = self.work / "compiled-c-backend"
            libraries = [
                "--ldflag=" + str(self.build / name) for name in ("libcrust0.a", "libcrust0_host.a")
            ]
            self.compile(c_backend_sources(), backend, libraries)
            target = self.work / "compiled-intrusive"
            self.command(
                [
                    backend,
                    *self.flags,
                    "-o",
                    target,
                    ROOT / "examples/intrusive/program.crs",
                    "--ldflag=" + str(self.build / "libcrust0_host.a"),
                ]
            )
            self.execute(target, b"intrusive: ok\n")
        elif name == "private-definitions-across-libraries":
            for tool in ("crust-overload", "crust-overload-resource"):
                compiler = self.build / tool
                objects, libraries = [], []
                for function, value in (("left", 65), ("right", 66)):
                    source = self.source(
                        tool + "-" + function,
                        f"fn {function}()->i32; "
                        f"fn helper()->i32 {{return {value}i32;}} "
                        f"fn {function}()->i32 {{return helper();}}",
                    )
                    obj = self.work / (tool + "-" + function + ".o")
                    self.command(
                        [
                            compiler,
                            "--library",
                            "--object",
                            "--cflag=-fPIC",
                            "--cflag=-fno-inline",
                            "-o",
                            obj,
                            source,
                        ]
                    )
                    objects.append(obj)
                    library = obj.with_suffix(".so")
                    self.command(["gcc", "-shared", obj, "-o", library])
                    libraries.append(library)
                caller = self.source(
                    tool + "-caller",
                    program(
                        "if left()!=65i32 || right()!=66i32 {return 1i32;}",
                        "fn left()->i32; fn right()->i32;",
                    ),
                )
                for label, inputs in (("shared", libraries), ("static", objects)):
                    output = self.work / (tool + "-" + label)
                    self.command(
                        [
                            compiler,
                            "-o",
                            output,
                            caller,
                            *("--ldflag=" + str(path) for path in inputs),
                        ]
                    )
                    self.execute(output, b"")
                for obj in objects:
                    if len(self.symbols(obj)) != 1:
                        raise Failure("only the interface declaration may export a definition")
        elif name == "formatter-separate-objects":
            interface = self.source("format-interface", FORMAT_INTERFACE)
            provider = self.source("format-provider", FORMAT_PROVIDER)
            caller = self.source("format-caller", FORMAT_CALLER)
            combined = self.work / "format-combined"
            self.compile([interface, provider, caller], combined)
            self.execute(combined, FORMAT_OUTPUT)
            provider_object = self.work / "format-provider.o"
            caller_object = self.work / "format-caller.o"
            self.compile([interface, provider], provider_object, ["--library", "--object"])
            self.compile([interface, caller], caller_object, ["--object"])
            provider_symbols = self.symbols(provider_object)
            caller_imports = self.symbols(caller_object, defined=False)
            if len(provider_symbols & caller_imports) != 3:
                raise Failure("the separate caller must import the three provider overload symbols")
            output = self.work / "format-separate"
            self.compile([interface, caller], output, ["--ldflag=" + str(provider_object)])
            self.execute(output, FORMAT_OUTPUT)
            if "write" not in self.symbols(provider_object, defined=False):
                raise Failure("explicit native write symbol was changed")
            mismatch = self.source(
                "format-wrong-import",
                "fn format(value:u32)->i32;\n" + program("return format(7u32);"),
            )
            result = self.command(
                [
                    self.compiler,
                    *self.flags,
                    "-o",
                    self.work / "must-not-link",
                    mismatch,
                    "--ldflag=" + str(provider_object),
                ],
                expected=1,
            )
            if not result.stderr:
                raise Failure("source ABI import mismatch did not report the link failure")
        elif name == "stable-native-mangles":
            provider = self.source(
                "stable-provider",
                "record Tag{x:u64;} "
                "fn sample(value:*Tag)->u64; fn sample(value:u64)->u64; "
                "fn sample(value:*Tag)->u64{return (*value).x;} "
                "fn sample(value:u64)->u64{return value;}",
            )
            unrelated = self.source(
                "stable-unrelated", "fn unrelated()->u32; fn unrelated()->u32{return 8u32;}"
            )
            paths = []
            for label, sources in (
                ("alone", [provider]),
                ("first", [provider, unrelated]),
                ("last", [unrelated, provider]),
            ):
                path = self.work / ("stable-" + label + ".o")
                self.compile(sources, path, ["--library", "--object"])
                paths.append(path)
            original, first, last = map(self.symbols, paths)
            if len(original) != 2 or not original < first or first != last:
                raise Failure(f"source order changed native names: {original}, {first}, {last}")
            renamed_parameters = self.source(
                "stable-parameters", provider.read_text().replace("value", "argument")
            )
            path = self.work / "stable-parameters.o"
            self.compile([renamed_parameters], path, ["--library", "--object"])
            if self.symbols(path) != original:
                raise Failure("parameter spelling changed native names")
        elif name == "exact-native-label-and-export":
            source = self.source(
                "native-label",
                'extern fn unusual(value:u64)->u64=".LFE0"; '
                "fn relay(value:u64)->u64{return unusual(value);}",
            )
            path = self.work / "native-label.o"
            self.compile([source], path, ["--library", "--object", "--export", "relay"])
            if self.symbols(path) != {"relay"} or ".LFE0" not in self.symbols(path, defined=False):
                raise Failure("native label or explicit export name changed")
        elif name == "ambiguous-export":
            source = self.source(
                name, "fn api(x:u32)->u32{return x;} fn api(x:u64)->u64{return x;}"
            )
            result = self.command(
                [
                    self.compiler,
                    "--library",
                    "--object",
                    "--export",
                    "api",
                    "-o",
                    self.work / "ambiguous.o",
                    source,
                ],
                expected=1,
            )
            if not any(
                word in result.stderr.lower() for word in (b"overload", b"ambiguous", b"export")
            ):
                raise Failure(f"missing ambiguous export diagnostic: {result.stderr!r}")
        elif name == "entry-signature-selection":
            source = self.source(
                name,
                "fn start(value:u32)->u32{return value;} "
                "fn start(argc:i32,argv:**u8)->i32{return 0i32;}",
            )
            output = self.work / name
            self.compile([source], output, ["--entry", "start"])
            self.execute(output, b"")
        elif name == "driver-diagnostics":
            cases = {
                "result": "fn start(argc:i32,argv:**u8)->u32{return 0u32;}",
                "arity": "fn start(value:u32)->u32{return value;}",
                "pointer": "fn start(argc:i32,argv:*u8)->i32{return 0i32;}",
                "prototype": "fn start(argc:i32,argv:**u8)->i32;",
                "native": 'extern fn start(argc:i32,argv:**u8)->i32="external_entry";',
                "constant": "const start:u32=1u32;",
                "missing": "fn other()->unit{}",
            }
            for tool in ("crust-overload", "crust-overload-resource"):
                for case, text in cases.items():
                    source = self.source(name + "-" + case, text)
                    for endpoint in ("--prepare", "--emit-c"):
                        result = self.command(
                            [self.build / tool, endpoint, "--entry", "start", source], expected=1
                        )
                        message = (
                            b"entry function was not found"
                            if case == "missing"
                            else b"entry must be a defined fn(i32, **u8) -> i32"
                        )
                        if (tool + ": error: ").encode() + message not in result.stderr:
                            raise Failure(f"incorrect entry diagnostic: {result.stderr!r}")
                source = self.source(name + "-gcc", program(""))
                result = self.command(
                    [
                        self.build / tool,
                        "--object",
                        "--cflag=-fcrust-deliberately-invalid",
                        "-o",
                        self.work / "failed.o",
                        source,
                    ],
                    expected=1,
                )
                if (tool + ": error: gcc failed with status 1").encode() not in result.stderr:
                    raise Failure(f"incorrect driver name: {result.stderr!r}")
            for borrow in ("read", "mut"):
                source = self.source(
                    name + "-" + borrow,
                    f"fn start(argc:i32,argv:{borrow} *u8)->i32{{return 0i32;}}",
                )
                for endpoint in ("--prepare", "--emit-c"):
                    result = self.command(
                        [
                            self.build / "crust-overload-resource",
                            endpoint,
                            "--entry",
                            "start",
                            source,
                        ],
                        expected=1,
                    )
                    if b"entry must be a defined fn(i32, **u8) -> i32" not in result.stderr:
                        raise Failure(f"lowered ABI accepted a borrowed entry: {result.stderr!r}")
        elif name in ("source-root-hello", "source-root-separate", "source-root-resources"):
            example = name.removeprefix("source-root-")
            package = self.work / name
            interface = "resource_api.crs" if example == "resources" else "api.crs"
            examples = (ROOT / "examples/overload" / example).glob("*.crs")
            for relative in (
                Path("api/crust0_stage.crs"),
                Path("stages/overload") / interface,
                *[path.relative_to(ROOT) for path in examples],
            ):
                destination = package / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, destination)
            library = package / "build/selected backend.plugin"
            library.parent.mkdir()
            original_library = (
                "crust-overload-resource-library.so"
                if example == "resources"
                else "crust-overload-library.so"
            )
            shutil.copyfile(self.build / original_library, library)
            source = package / "examples/overload" / example / "main.crs"
            source.write_text(source.read_text().replace(original_library, library.name))
            result = self.command([self.build / "crust", source])
            if result.stdout or result.stderr:
                raise Failure(
                    f"source root produced unexpected output: {result.stdout!r}, {result.stderr!r}"
                )
            output = package / "build" / ("overload-" + example)
            expected = {
                "hello": b"A typed function value.\nHello, overloads!\n",
                "separate": b"types: 42\n",
                "resources": b"Owned overloads.\nDeferred overload.\n",
            }[example]
            self.execute(output, expected)
            symbols = self.symbols(output)
            if any(
                symbol in symbols
                for symbol in (
                    "overload_build",
                    "overload_program",
                    "overload_resource_build",
                    "crust_run_main",
                )
            ):
                raise Failure("target executable contains host compilation entry points")
        else:
            raise AssertionError(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--group", choices=("all", "runtime", "reject", "boundary"), default="all")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--ldflag", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    cases = [("runtime", *case) for case in runtime_cases()]
    cases += [("reject", *case) for case in reject_cases()]
    cases += [
        ("boundary", name, None, None)
        for name in (
            "compile-c-backend",
            "formatter-separate-objects",
            "private-definitions-across-libraries",
            "stable-native-mangles",
            "exact-native-label-and-export",
            "ambiguous-export",
            "entry-signature-selection",
            "driver-diagnostics",
            "source-root-hello",
            "source-root-separate",
            "source-root-resources",
        )
    ]
    cases = [
        case
        for case in cases
        if (args.group == "all" or case[0] == args.group)
        and (not args.case or any(fnmatch.fnmatchcase(case[1], pattern) for pattern in args.case))
    ]
    if not cases:
        parser.error("no test cases selected")
    if args.list:
        for group, name, _, _ in cases:
            print(f"{group}: {name}")
        return 0
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    if not (args.build / "crust-overload").is_file():
        parser.error("build/crust-overload must be built before these tests")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    work = Path(tempfile.mkdtemp(prefix="crust-overload-"))
    suite = Suite(args, work)
    failures = 0
    counts = dict(runtime=0, reject=0, boundary=0)
    try:
        for group, name, source, expected in cases:
            try:
                if group == "runtime":
                    suite.runtime(name, source, expected)
                elif group == "reject":
                    suite.reject(name, source, expected)
                else:
                    suite.boundary(name)
                counts[group] += 1
            except (Failure, OSError, subprocess.TimeoutExpired) as error:
                failures += 1
                print(f"FAIL {group}: {name}\n{error}", file=sys.stderr)
                if not args.keep_going:
                    break
        print(
            f"Overload suite: {counts['runtime']} runtime, {counts['reject']} rejection, "
            f"{counts['boundary']} boundary cases passed; {suite.commands} process checks; {failures} failures"
        )
    finally:
        if failures:
            print(f"Failure inputs and artifacts retained in {work}", file=sys.stderr)
        else:
            shutil.rmtree(work)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
