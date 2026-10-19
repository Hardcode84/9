# SPDX-License-Identifier: Apache-2.0
"""Host process, linking, and failure fixtures for the Vulkan execution suite."""

import json
import os
import shutil
import subprocess
from pathlib import Path

from prepare import ROOT, compile_package
from windows import STRICT, native_path


class LinuxHost:
    profile = "linux"

    def __init__(self, build, work, cc, library):
        self.build, self.work, self.cc = build, work, cc
        self.library = library or "-Wl,-l:libvulkan.so.1"

    def path(self, path):
        return str(Path(path).resolve())

    def run(self, command, *, expected=0, env=None, cwd=ROOT):
        result = subprocess.run(
            list(map(str, command)), cwd=cwd, env=env, capture_output=True, timeout=120
        )
        if result.returncode != expected:
            raise AssertionError(
                f"{command}: status {result.returncode}, expected {expected}\n{result.stdout!r}\n{result.stderr!r}"
            )
        return result

    def compile(self, build, manifest, output, cflags, ldflags):
        compile_package(build, manifest, output, cflags, ldflags)

    def root(self, original):
        text = original.read_text(encoding="utf-8")
        text = text.replace('"../../', json.dumps(self.path(ROOT) + "/", ensure_ascii=False)[:-1])
        text = text.replace('"../.."', json.dumps(self.path(ROOT), ensure_ascii=False))
        root = self.work / "root.crs"
        root.write_text(text, encoding="utf-8")
        return root

    def failures(self, native):
        library = self.work / "faults.so"
        self.compile(
            self.build,
            ROOT / "tests/vulkan/faults-package.crs",
            library,
            ["-O2", "-fPIC"],
            ["-shared", self.library],
        )
        return native, {"LD_PRELOAD": str(library)}

    def failing_tool(self):
        directory = self.work / "failed-tools" / "bin"
        directory.mkdir(parents=True, exist_ok=True)
        tool = directory / "opt"
        tool.write_text("#!/bin/sh\n# SPDX-License-Identifier: Apache-2.0\nexit 1\n")
        tool.chmod(0o755)
        return tool


class WindowsHost(LinuxHost):
    profile = "windows"

    def __init__(self, build, work, cc, library):
        if library is None or not library.is_file():
            raise ValueError("Windows Vulkan requires --vulkan-library with an import library")
        super().__init__(build, work, cc, Path(library).resolve())

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
        if os.name != "nt":
            environment["WSLENV"] = environment.get("WSLENV", "") + ":CRUST_VULKAN_TEST_FAULT"
        return super().run(
            [self.build / "windows_limit.exe", *arguments],
            expected=expected,
            env=environment,
            cwd=cwd,
        )

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

    def failures(self, native):
        obj = self.emit_object(
            ROOT / "tests/vulkan/faults-package.crs", self.work / "faults", ["-O2"]
        )
        output = self.work / "fault-dispatch.exe"
        self.run(
            [
                *self.cc,
                "-municode",
                native.with_suffix(".o").name,
                obj.name,
                *self.entry_objects(),
                self.library,
                "-o",
                output.name,
            ],
            cwd=self.work,
        )
        return output, {}

    def failing_tool(self):
        directory = self.work / "failed-tools" / "bin"
        directory.mkdir(parents=True, exist_ok=True)
        source = directory / "failure.c"
        source.write_text("/* SPDX-License-Identifier: Apache-2.0 */\nint main(void){return 1;}\n")
        self.run([*self.cc, *STRICT, source.name, "-o", "opt.exe"], cwd=directory)
        return directory / "opt.exe"
