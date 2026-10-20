# SPDX-License-Identifier: Apache-2.0
"""Process operations shared by the native Linux and Windows test suites."""

import os
import shlex
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def api_path(build, name):
    return (Path(build) / "profile/api" if WINDOWS else ROOT / "api") / name


def disable_core_dumps():
    if not WINDOWS:
        import resource

        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def exit_status(status):
    # The emitted trap is an illegal instruction on both native targets.
    if WINDOWS:
        return {-4: 0xC000001D, -6: 3, -22: 3}.get(status, status)
    return status


def status_matches(actual, expected):
    if WINDOWS and expected in (-6, -22):
        return actual in (3, 0xC0000409)
    return actual == exit_status(expected)


def limit_stack():
    import resource

    resource.setrlimit(resource.RLIMIT_STACK, (131072, 131072))


@contextmanager
def failed_output():
    path, mode = (Path(__file__), "rb") if WINDOWS else ("/dev/full", "wb")
    with open(path, mode) as stream:
        yield stream


def executable(value):
    path = Path(value)
    if WINDOWS and not path.is_file() and Path(str(path) + ".exe").is_file():
        return str(path) + ".exe"
    return str(value)


def sanitizer_compiler():
    return os.environ.get("CRUST_SANITIZER_CC", "clang" if WINDOWS else "gcc")


def sanitizer_flags():
    flags = [
        "-O1",
        "-g1",
        "-fsanitize=address,undefined",
        "-fno-sanitize-recover=all",
        "-fno-omit-frame-pointer",
    ]
    if WINDOWS:
        # Generated foreign calls erase pointee types. Clang's C function-type
        # check is outside the scalar native ABI contract (and absent in GCC).
        flags.append("-fno-sanitize=function")
    else:
        flags += [
            "-fno-inline-functions-called-once",
            "--param=ggc-min-expand=10",
            "--param=ggc-min-heapsize=32768",
        ]
    return flags


def sanitizer_environment():
    return dict(
        os.environ,
        ASAN_OPTIONS=f"detect_leaks={0 if WINDOWS else 1}:halt_on_error=1",
        UBSAN_OPTIONS="halt_on_error=1",
    )


def host_sources(amalgamation=1):
    core = (
        [ROOT / "crust0_amalg.c"]
        if amalgamation
        else [ROOT / f"src/{name}.c" for name in ("core", "read", "check")]
    )
    profile, platform = ("windows_x64", "windows") if WINDOWS else ("linux_x64", "posix")
    result = [
        *core,
        ROOT / f"src/profile_{profile}.c",
        ROOT / "runtime/host.c",
        ROOT / f"runtime/host_{platform}.c",
    ]
    if WINDOWS:
        result.append(ROOT / "runtime/windows_io.c")
    return result


def run(arguments, *, text_output=False, **options):
    command = list(map(str, arguments))
    command[0] = executable(command[0])
    if WINDOWS:
        resolved = command[0] if Path(command[0]).is_file() else shutil.which(command[0])
        if resolved is None:
            raise FileNotFoundError(command[0])
        command[0] = resolved
    result = subprocess.run(command, **options)
    if WINDOWS and text_output:
        for stream in ("stdout", "stderr"):
            value = getattr(result, stream)
            if isinstance(value, bytes):
                setattr(result, stream, value.replace(b"\r\n", b"\n"))
    return result


def rename_symbols(symbols, source, output):
    """Apply the emitter response without Windows text-mode SUB truncation."""
    response = Path(symbols).read_bytes()
    if not WINDOWS or b"\x1a" not in response:
        run(["objcopy", "@" + str(symbols), source, output], check=True)
        return
    tokens = shlex.split(response.decode("utf-8"))
    if len(tokens) % 2 or any(token != "--redefine-sym" for token in tokens[::2]):
        raise ValueError("invalid symbol response")
    shutil.copyfile(source, output)
    for mapping in tokens[1::2]:
        run(["objcopy", "--redefine-sym", mapping, output], check=True)
