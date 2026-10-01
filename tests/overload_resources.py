#!/usr/bin/env python3
"""Check overload selection with resource contracts and separate source imports."""

import argparse
import fnmatch
from pathlib import Path
import resource
import shutil
import sys
import tempfile

from resources import Failure, ROOT, Suite as ResourceSuite, program, source_report


def large_record_source(count=512):
    fields = " ".join(f"field{index:04}:u64;" for index in range(count))
    initializers = ",".join(f"field{index:04}:{index + 1}u64" for index in range(count))
    reads = " ".join(f"total=total+choose(value.field{index:04});" for index in range(count))
    return program(
        f"var value:Fields=make Fields {{{initializers}}}; var total:u64=0u64; "
        f"{reads} if total!={count * (count + 1) // 2}u64 {{return 1i32;}}",
        f"record Fields {{{fields}}} fn choose(item:u64)->u64 {{return item;}} "
        "fn choose(item:i32)->i32 {return item;}", common=False)


def runtime_cases():
    return [
        ("large-record-construction-and-selection", large_record_source(), b""),
        ("value-and-borrow-overloads", program(
            "var number:i32=10i32; "
            "if choose(number)!=11i32 || choose(read number)!=12i32 {return 1i32;} "
            "if choose(mut number)!=13i32 {return 2i32;} "
            "{var view:read i32=read number; if choose(view)!=14i32 {return 3i32;}}",
            "fn choose(value:i32)->i32 {return value+1i32;} "
            "fn choose(value:read i32)->i32 {return value+2i32;} "
            "fn choose(value:mut i32)->i32 {value=value+3i32; return value;}", common=False), b""),
        ("move-defer-and-borrow-overloads", program(
            "var value:Token=token(65i32); take(read value); take(mut value); "
            "{defer take(read value); emit(88i32);} take(move value); emit(89i32);",
            "fn take(item:read Token)->unit {unsafe {emit(item.id+32i32);}} "
            "fn take(item:mut Token)->unit {unsafe {item.id=item.id+1i32;}} "
            "fn take(item:Token)->unit {emit(33i32);}"), b"aXb!BY"),
        ("overloaded-drop-selection", program(
            "unsafe {var first:First=make First {id:65i32}; "
            "var second:Second=make Second {id:66i32}; emit(88i32);}",
            "extern fn putchar(code:i32)->i32=\"putchar\"; "
            "fn emit(code:i32)->unit {unsafe {putchar(code);}} "
            "resource First {id:i32;} drop cleanup; resource Second {id:i32;} drop cleanup; "
            "fn cleanup(item:mut First)->unit {unsafe {emit(item.id);}} "
            "fn cleanup(item:mut Second)->unit {unsafe {emit(item.id);}}", common=False), b"XBA"),
        ("typed-projection-callbacks", program(
            "var item:Item=make Item {code:41i32}; "
            "var callback:fn(read Item)->i32=project; "
            "if callback(read item)!=42i32 || invoke(read item,project)!=42i32 {return 1i32;} "
            "callback=selected(); if callback(read item)!=42i32 {return 2i32;} "
            "if callbacks.project(read item)!=42i32 || functions[0usize](read item)!=42i32 {return 3i32;}",
            "record Item {code:i32;} record Other {code:u64;} "
            "fn project(item:read Item)->i32 {return item.code+1i32;} "
            "fn project(item:read Other)->u64 {return item.code+2u64;} "
            "fn selected()->fn(read Item)->i32 {return project;} "
            "fn invoke(item:read Item,callback:fn(read Item)->i32)->i32 {return callback(read item);} "
            "record Callbacks {project:fn(read Item)->i32;} "
            "const callbacks:Callbacks=make Callbacks {project:project}; "
            "const functions:[fn(read Item)->i32;1]=make [fn(read Item)->i32;1] {project};", common=False), b""),
        ("borrowed-and-raw-place-projection", program(
            "var number:i32=41i32; var item:Item=make Item {code:41i32}; "
            "var values:[i32;1]=make [i32;1] {41i32}; "
            "if choose(*(read number))!=42i32 || choose((read item).code)!=42i32 || "
            "choose((read values)[0usize])!=42i32 {return 1i32;} "
            "unsafe {var pointer:*Item=&item; if choose(pointer.code)!=42i32 {return 2i32;}}",
            "record Item {code:i32;} fn choose(value:i32)->i32 {return value+1i32;} "
            "fn choose(value:u64)->u64 {return value+2u64;}", common=False), b""),
        ("forget-after-overloaded-construction", program(
            "var value:Token=make_token(65u64); unsafe {forget move value;} emit(88i32);",
            "fn make_token(code:i32)->Token {return token(code);} "
            "fn make_token(code:u64)->Token {return token(code as i32);}"), b"X"),
        ("matching-unsafe-prototype-and-definition", program(
            "unsafe {if choose(41i32)!=42i32 {return 1i32;}}",
            "unsafe fn choose(value:i32)->i32; "
            "fn choose(value:u64)->u64 {return value+2u64;} "
            "unsafe fn choose(value:i32)->i32 {return value+1i32;}", common=False), b""),
    ]


def reject_cases():
    return [
        ("duplicate-record-field", program("", "record Fields {item:i32; item:u64;}",
            common=False), "duplicate record field"),
        ("duplicate-resource-field", program("",
            "resource Token {id:i32; id:u64;} drop cleanup; fn cleanup(item:mut Token)->unit {}",
            common=False), "duplicate record field"),
        ("selected-owner-still-needs-move", program(
            "var value:Token=token(65i32); consume(value);",
            "fn consume(item:Token)->unit {} fn consume(item:read Token)->unit {}"), "explicit move"),
        ("selected-borrow-still-reserves-owner", program(
            "var value:Token=token(65i32); defer access(read value); access(mut value);",
            "fn access(item:read Token)->unit {} fn access(item:mut Token)->unit {}"), "active borrow"),
        ("selected-unsafe-import", program("choose(1i32);",
            "unsafe fn choose(value:i32)->i32; fn choose(value:u64)->u64;", common=False), "call requires an unsafe region"),
        ("selected-unsafe-function-value", program("var callback:fn(i32)->i32=choose;",
            "unsafe fn choose(value:i32)->i32; fn choose(value:u64)->u64;", common=False), "unsafe function"),
        ("unsafe-prototype-contract-conflict", program("",
            "unsafe fn choose(value:i32)->i32; fn choose(value:i32)->i32 {return value;}", common=False), "different contracts"),
        ("native-extern-retains-unsafe-contract", program("choose(-1i32);",
            'extern fn choose(value:i32)->i32="abs"; fn choose(value:u64)->u64 {return value;}', common=False), "call requires an unsafe region"),
        ("native-extern-cannot-use-resource-abi", program("",
            'extern fn foreign(item:Token)->unit="foreign";'), "foreign signatures require explicit scalar ABI types"),
        ("imported-drop-explicit-safe-call", program(
            "var value:Token=token(65i32); cleanup(mut value);",
            "resource Token {id:i32;} drop cleanup; fn cleanup(item:mut Token)->unit; "
            "fn token(code:i32)->Token;", common=False), "call requires an unsafe region"),
        ("imported-drop-function-value", program("",
            "resource Token {id:i32;} drop cleanup; fn cleanup(item:mut Token)->unit; "
            "const callback:fn(mut Token)->unit=cleanup;", common=False), "constant initializer cannot retain an unsafe function"),
        ("unsafe-import-cannot-be-drop", program("",
            "resource Token {id:i32;} drop cleanup; unsafe fn cleanup(item:mut Token)->unit;", common=False), "resource drop must name a safe"),
        ("function-casts-retain-unsafe-rule", program(
            "var callback:fn(i32)->i32=choose as fn(i32)->i32;",
            "fn choose(value:i32)->i32 {return value;} fn choose(value:u64)->u64 {return value;}", common=False), "pointer and function casts require an unsafe region"),
        ("read-mut-function-constant-mismatch", program("",
            "fn choose(value:mut i32)->unit {} fn choose(value:u64)->unit {} "
            "const callback:fn(read i32)->unit=choose;", common=False), "no overload matches"),
        ("nested-borrow-type-still-rejected", program("",
            "fn choose(value:read read i32)->unit {} fn choose(value:i32)->unit {}", common=False), "borrow modes require a value type"),
    ]


class Suite(ResourceSuite):
    def __init__(self, args, work):
        super().__init__(args, work)
        self.compiler = self.build / "rmd-overload-resource"

    def object(self, name, *sources):
        output = self.work / (name + ".o")
        self.command([self.compiler, "--library", "--object", "-o", output,
                      *self.options, *sources])
        return output

    def separate(self, name):
        if name == "separate-source-resource-cleanup":
            interface = self.source(name + "-interface",
                'extern fn putchar(code:i32)->i32="putchar"; '
                'resource Token {id:i32;} drop cleanup; '
                'fn cleanup(item:mut Token)->unit; '
                'fn create(code:i32)->Token; fn create(code:u64)->Token; '
                'fn consume(item:Token)->unit; '
                'fn show(item:read Token)->unit; fn show(item:mut Token)->unit;')
            provider = self.source(name + "-provider",
                'fn cleanup(item:mut Token)->unit {unsafe {putchar(item.id);}} '
                'fn create(code:i32)->Token {unsafe {return make Token {id:code};}} '
                'fn create(code:u64)->Token {return create(code as i32);} '
                'fn consume(item:Token)->unit {unsafe {putchar(33i32);}} '
                'fn show(item:read Token)->unit {unsafe {putchar(item.id+32i32);}} '
                'fn show(item:mut Token)->unit {unsafe {item.id=item.id+1i32;}}')
            first = self.object(name + "-first", interface, provider)
            second = self.object(name + "-reordered", provider, interface)
            def symbols(path):
                output = self.command(["nm", "--defined-only", "--format=posix", path]).stdout
                return {line.split()[0] for line in output.splitlines()
                        if line.split()[0].startswith(b"rmd_ov1_")}
            names = symbols(first)
            if len(names) != 6 or names != symbols(second):
                raise Failure("source ABI symbols depend on input order or omit a definition")
            consumer = self.source(name + "-consumer", program(
                "var first:Token=create(65i32); var second:Token=create(66u64); "
                "show(read first); show(mut second); var callback:fn(read Token)->unit=show; "
                "defer callback(read second); unsafe {putchar(88i32);} "
                "consume(create(68i32));", common=False))
            output = self.work / name
            self.command([self.compiler, "-o", output, *self.options,
                          "--ldflag", first, interface, consumer])
            result = self.command([output])
            if result.stdout != b"aX!DcCA" or result.stderr:
                raise Failure(f"imported ownership or cleanup failed: {result.stdout!r} {result.stderr!r}")
        elif name == "separate-unsafe-effect-contract":
            interface = self.source(name + "-interface", "unsafe fn choose(value:i32)->i32;")
            provider = self.source(name + "-provider", "unsafe fn choose(value:i32)->i32 {return value+1i32;}")
            imported = self.object(name + "-provider", interface, provider)
            consumer = self.source(name + "-consumer", program(
                "unsafe {if choose(41i32)!=42i32 {return 1i32;}}", common=False))
            output = self.work / name
            self.command([self.compiler, "-o", output, *self.options,
                          "--ldflag", imported, interface, consumer])
            self.command([output])
            wrong = self.source(name + "-wrong", "fn choose(value:i32)->i32;")
            result = self.command([self.compiler, "-o", output, *self.options,
                                   "--ldflag", imported, wrong, consumer], expected=1)
            if b"undefined reference" not in result.stderr:
                raise Failure(f"unsafe source ABI mismatch did not fail at link: {result.stderr!r}")
        elif name == "separate-borrow-contract-mismatch":
            provider = self.source(name + "-provider",
                "fn change(value:mut i32)->i32 {value=value+1i32; return value;}")
            imported = self.object(name + "-provider", provider)
            consumer = self.source(name + "-consumer", program(
                "var value:i32=41i32; if change(read value)!=42i32 {return 1i32;}",
                "fn change(value:read i32)->i32;", common=False))
            result = self.command([self.compiler, "-o", self.work / name, *self.options,
                                   "--ldflag", imported, consumer], expected=1)
            if b"undefined reference" not in result.stderr:
                raise Failure(f"borrow mode mismatch did not fail at link: {result.stderr!r}")
        else:
            raise AssertionError(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--group", choices=("all", "runtime", "reject", "separate"), default="all")
    parser.add_argument("--case", action="append", default=[])
    parser.add_argument("--cflag", action="append", default=[])
    parser.add_argument("--ldflag", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    cases = [("runtime", *item) for item in runtime_cases()]
    cases += [("reject", *item) for item in reject_cases()]
    cases += [("separate", name, None, None) for name in
              ("separate-source-resource-cleanup", "separate-unsafe-effect-contract",
               "separate-borrow-contract-mismatch")]
    cases = [item for item in cases if (args.group == "all" or item[0] == args.group) and
             (not args.case or any(fnmatch.fnmatchcase(item[1], pattern) for pattern in args.case))]
    if not cases or args.timeout <= 0:
        parser.error("select at least one case and a positive timeout")
    if args.list:
        for group, name, _, _ in cases:
            print(f"{group}: {name}")
        return 0
    if not (args.build / "rmd-overload-resource").is_file():
        parser.error("build rmd-overload-resource before this test")
    work = Path(tempfile.mkdtemp(prefix="rmd-overload-resources-"))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    suite = Suite(args, work)
    passed = 0
    failures = 0
    try:
        for group, name, source, expected in cases:
            try:
                if group == "runtime":
                    suite.runtime(name, source, expected)
                elif group == "reject":
                    suite.reject(name, source, expected)
                else:
                    suite.separate(name)
                passed += 1
            except (Failure, OSError) as error:
                failures += 1
                print(f"FAIL {group}: {name}\n{error}", file=sys.stderr)
                if source is not None:
                    print("Source:\n" + source_report(source), file=sys.stderr)
                if not args.keep_going:
                    break
        print(f"Overload resource suite: {passed} cases passed; "
              f"{suite.commands} process checks; {failures} failures")
    finally:
        if failures:
            print(f"Failure inputs and artifacts retained in {work}", file=sys.stderr)
        else:
            shutil.rmtree(work)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
