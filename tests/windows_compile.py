# SPDX-License-Identifier: Apache-2.0
"""Compile source-selected test packages for native Windows execution."""

import os
import shutil
import subprocess
from pathlib import Path

from windows import ROOT, native_path


class WindowsCompiler:
    def __init__(self, build, cc):
        self.build, self.cc = build, cc

    def path(self, path):
        return native_path(path)

    def executable(self, value):
        path = Path(value)
        if path.with_suffix(".exe").is_file():
            return path.with_suffix(".exe")
        if path.is_file():
            return path
        found = shutil.which(str(value) + ".exe") or shutil.which(str(value))
        if found is None:
            raise FileNotFoundError(value)
        return Path(found)

    def run(self, command, *, expected=0, env=None, cwd=ROOT):
        arguments = [self.path(self.executable(command[0]))]
        for value in command[1:]:
            if isinstance(value, Path):
                if not value.suffix and value.with_suffix(".exe").is_file():
                    value = value.with_suffix(".exe")
                value = self.path(value)
            arguments.append(str(value))
        environment = (os.environ if env is None else env).copy()
        command = [str(self.build / "windows_limit.exe"), *arguments]
        result = subprocess.run(command, env=environment, cwd=cwd, capture_output=True, timeout=180)
        if result.returncode != expected:
            raise AssertionError(
                f"{command}: {result.returncode}, expected {expected}\n{result.stdout!r}\n{result.stderr!r}"
            )
        return result

    def emit_object(self, manifest, output, cflags, entry=False):
        source, symbols = output.with_suffix(".c"), output.with_suffix(".symbols")
        obj, renamed = output.with_suffix(".input.o"), output.with_suffix(".o")
        self.run(
            [self.build / "crust.exe", ROOT / "stages/build/emit.crs", manifest, source, symbols]
        )
        self.run(
            [*self.cc, "-std=c99", "-pedantic-errors", *cflags, "-c", source.name, "-o", obj.name],
            cwd=output.parent,
        )
        if entry:
            mappings = symbols.read_text(encoding="utf-8")
            symbols.write_text(mappings.replace('=main"\n', '=crust_run_main"\n'), encoding="utf-8")
        self.run(["objcopy", "@" + symbols.name, obj.name, renamed.name], cwd=output.parent)
        return renamed

    def entry_objects(self):
        return [self.build / "run_entry_windows.o", self.build / "windows_io.o"]

    def compile(self, build, manifest, output, cflags, ldflags):
        obj = self.emit_object(manifest, output, cflags, entry=True)
        self.run(
            [
                *self.cc,
                "-municode",
                obj.name,
                *self.entry_objects(),
                *ldflags,
                "-lbcrypt",
                "-o",
                output.with_suffix(".exe").name,
            ],
            cwd=output.parent,
        )
