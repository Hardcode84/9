#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check native trusted providers, checked clients, receipts, and proof erasure."""

import argparse
import hashlib
from pathlib import Path

from generics_ownership_imports import CLIENT, HELPERS
from ownership_imports import fixture
from windows import ROOT, literal, native_path
from windows_bootstrap import Suite


class OwnershipSuite(Suite):
    def generic(self):
        package = self.work / "generic ownership package.crs"
        package.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + f"stage_include(stage,{literal(native_path(ROOT / 'stages/generics/ownership/sources.crs'))});"
            + f"stage_source(stage,{literal(native_path(ROOT / 'tests/generics_ownership_import_driver.crs'))});"
            + 'stage_export_as(stage,"main","ownership_main");\n',
            encoding="utf-8",
        )
        self.package = package
        objects = self.fresh_directory("generic ownership objects")
        provider = self.inputs / "generic provider.crs"
        client = self.inputs / "generic client.crs"
        provider.write_text(HELPERS, encoding="utf-8")
        client.write_text(CLIENT, encoding="utf-8")
        result = self.driver("publish", objects, provider)
        artifact, digest, trust = result.stdout.decode().splitlines()
        assert trust == "checked"
        cached = next(objects.glob("*/artifact.dll"))
        assert cached.read_bytes().startswith(
            b"crust-generic-ownership-v2-signature-contracts-windows-x64\n"
        )
        provider.unlink()
        source = self.work / "generic.c"
        symbols = self.work / "generic.rsp"
        self.driver("import", objects, artifact, digest, trust, source, symbols, client)
        commands = [
            ["gcc", "-std=c99", "-pedantic-errors", "-O2", "-c", "generic.c", "-o", "generic.o"],
            ["objcopy", "@generic.rsp", "generic.o", "generic-linked.o"],
            ["gcc", "generic-linked.o", "-o", "generic.exe"],
        ]
        body = (
            self.setup()
            + f"var directory:*u8={literal(native_path(self.work))};var status:u32=1u32;"
        )
        for index, command in enumerate(commands):
            body += (
                f"var args{index}:[*u8;{len(command)+1}]=make [*u8;{len(command)+1}]{{"
                + ",".join(map(literal, command))
                + ",null(*u8)};"
            )
            tool = "win_tool_in" if index == 1 else "win_gcc_tool_in"
            body += f"if !{tool}(run -> context,&args{index}[0usize],null(*u8),&status,directory)||status!=0u32{{return 1i32;}};"
        self.root("generic native output", body + "return 0i32;")
        assert self.run(self.work / "generic.exe").stdout == b"A"
        client.write_text(
            CLIENT.replace(
                "var second:Value=transfer!(Value)(move first);",
                "var second:Value=transfer!(Value)(move first);discard!(Value)(move first);",
            ),
            encoding="utf-8",
        )
        self.driver("import", objects, artifact, digest, trust, source, symbols, client, expected=1)
        print("Windows generic ownership independent import, cleanup, and move rejection passed")

    def prepare(self):
        self.cache = self.fresh_directory("ownership stage cache")
        self.objects = self.fresh_directory("ownership object cache")
        self.inputs = self.fresh_directory("ownership input")
        self.package = self.work / "ownership driver package.crs"
        paths = [
            ROOT / "stages/ownership/sources.crs",
            ROOT / "tests/ownership_input.crs",
            ROOT / "tests/ownership_import_driver.crs",
        ]
        self.package.write_text(
            "// SPDX-License-Identifier: Apache-2.0\n"
            + f"stage_include(stage,{literal(native_path(paths[0]))});"
            + "".join(f"stage_source(stage,{literal(native_path(path))});" for path in paths[1:])
            + 'stage_export_as(stage,"main","ownership_main");\n',
            encoding="utf-8",
        )

    def driver(self, *args, expected=0):
        body = self.setup() + self.session(self.cache)
        body += f"var library:*u8=stage_library(stages,{literal(native_path(self.package))});"
        body += """if library==null(*u8){return 1i32;};
extern fn ownership_main(argc:i32,argv:**u8)->i32="ownership_main";
if !host_bind(run,crust_run_open(run,library),"ownership_main"){return 1i32;};
"""
        args = ["ownership", *[native_path(arg) if isinstance(arg, Path) else arg for arg in args]]
        body += (
            f"var args:[*u8;{len(args)}]=make [*u8;{len(args)}]{{"
            + ",".join(map(literal, args))
            + "};"
        )
        body += f"return ownership_main({len(args)}i32,&args[0usize]);"
        return self.root("ownership run", body, expected=expected)

    def contracts(self):
        links, provider, client = fixture(self.inputs)
        result = self.driver("publish", self.objects, "trusted", links, provider)
        artifact, digest = result.stdout.decode().splitlines()
        # Receipts contain native paths even when this harness runs under WSL.
        cached = next(self.objects.glob("*/artifact.dll"))
        assert cached.read_bytes().startswith(b"crust-ownership-library-v2-windows-x64\n")
        assert hashlib.sha256(cached.read_bytes()).hexdigest() == digest
        output = self.work / "ownership client.exe"
        args = ["import-trusted", self.objects, artifact, digest, "-o", output, client]
        self.driver(*args)
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"OK\n"
        invalid = self.inputs / "invalid-client.crs"
        text = client.read_text(encoding="utf-8")
        changed = text.replace(
            "var second: Owner = owner_new(66i64);", "var second: Owner = first;", 1
        )
        assert changed != text
        invalid.write_text(changed, encoding="utf-8")
        bad = list(args)
        bad[-1] = invalid
        self.driver(*bad, expected=1)
        erasure = self.work / "ownership erasure package.crs"
        erasure.write_text(
            self.package.read_text(encoding="utf-8").replace(
                "ownership_import_driver.crs", "ownership_erasure.crs"
            ),
            encoding="utf-8",
        )
        saved = self.package
        self.package = erasure
        self.driver("trusted", links, client)
        self.package = saved
        # Import authority must survive removal of the original provider sources.
        links.unlink()
        provider.unlink()
        self.driver(*args)
        assert self.run(output).stdout.replace(b"\r\n", b"\n") == b"OK\n"
        bad = list(args)
        bad[3] = "0" * 64
        assert b"digest" in self.driver(*bad, expected=1).stderr
        bad = list(args)
        bad[0] = "import"
        assert b"trust" in self.driver(*bad, expected=1).stderr
        assert not list(self.objects.glob(".build-*"))
        print("Windows ownership provider, imports, lifetime rejection, and proof erasure passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build/windows"))
    parser.add_argument("--case", choices=("contracts", "generic"))
    args = parser.parse_args()
    suite = OwnershipSuite(args.build)
    suite.prepare()
    for case in (args.case,) if args.case else ("contracts", "generic"):
        getattr(suite, case)()


if __name__ == "__main__":
    main()
