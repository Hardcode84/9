#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fetch official LLVM release tools or a main source snapshot into a local cache."""

import argparse
import fcntl
import hashlib
import http.client
import json
import platform
import re
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

API = "https://api.github.com/repos/llvm/llvm-project"
DEFAULT_DIRECTORY = Path(__file__).resolve().parents[1] / "build/toolchains/llvm"


def open_url(url):
    request = urllib.request.Request(url, headers={"User-Agent": "crust-llvm-fetch"})
    return urllib.request.urlopen(request, timeout=60)


def read_json(url):
    with open_url(url) as response:
        return json.load(response)


def resolve(channel):
    if channel == "main":
        revision = read_json(f"{API}/commits/main")["sha"]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("upstream main response has no full commit ID")
        return {
            "channel": channel,
            "revision": revision,
            "url": f"https://codeload.github.com/llvm/llvm-project/tar.gz/{revision}",
            "sha256": None,
        }
    release = read_json(f"{API}/releases/latest")
    tag = release["tag_name"]
    if release["draft"] or release["prerelease"] or not re.fullmatch(r"llvmorg-\d+\.\d+\.\d+", tag):
        raise ValueError("upstream response is not a stable LLVM release")
    name = f"LLVM-{tag.removeprefix('llvmorg-')}-Linux-X64.tar.xz"
    assets = [asset for asset in release["assets"] if asset["name"] == name]
    if len(assets) != 1:
        raise ValueError(f"release has no unique {name} asset")
    asset = assets[0]
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError(f"release asset {name} has no SHA-256 digest")
    return {
        "channel": channel,
        "revision": tag,
        "url": asset["browser_download_url"],
        "sha256": digest.removeprefix("sha256:"),
    }


def validate_pin(pin, channel):
    revision = r"[0-9a-f]{40}" if channel == "main" else r"llvmorg-\d+\.\d+\.\d+"
    if (
        set(pin) != {"channel", "revision", "url", "sha256"}
        or pin["channel"] != channel
        or not isinstance(pin["revision"], str)
        or not re.fullmatch(revision, pin["revision"])
        or not isinstance(pin["url"], str)
        or not pin["url"].startswith("https://")
        or not isinstance(pin["sha256"], str)
        or not re.fullmatch(r"[0-9a-f]{64}", pin["sha256"])
    ):
        raise ValueError("invalid LLVM pin; expected channel, revision, HTTPS URL and SHA-256")


def download(pin, destination):
    digest = hashlib.sha256()
    print(f"Downloading {pin['url']}", file=sys.stderr, flush=True)
    with open_url(pin["url"]) as response, destination.open("wb") as output:
        while block := response.read(1024 * 1024):
            output.write(block)
            digest.update(block)
    actual = digest.hexdigest()
    if pin["sha256"] is not None and actual != pin["sha256"]:
        raise ValueError(f"LLVM archive SHA-256 mismatch: expected {pin['sha256']}, got {actual}")
    return {**pin, "sha256": actual}


def unpack(archive, destination, channel):
    if not hasattr(tarfile, "data_filter"):
        raise ValueError("LLVM extraction requires Python with tarfile.data_filter")
    with tarfile.open(archive) as source:
        source.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir() or children[0].is_symlink():
        raise ValueError("LLVM archive must contain one top-level directory")
    tree = children[0]
    required = ("llvm/CMakeLists.txt",) if channel == "main" else ("bin/llc", "bin/opt")
    for path in required:
        if not (tree / path).is_file():
            raise ValueError(f"LLVM archive is missing {path}")
    return tree


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def fetch(channel, directory, locked=False):
    """Return an immutable snapshot path; publish its pin only after a successful fetch."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".fetch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return fetch_locked(channel, directory, locked)


def fetch_locked(channel, directory, locked):
    selection = directory / f"{channel}.json"
    if locked:
        pin = json.loads(selection.read_text())
        validate_pin(pin, channel)
    else:
        pin = resolve(channel)
    destination = directory / f"{channel}-{pin['revision']}"
    if destination.exists():
        stored = json.loads((destination / ".crust-fetch.json").read_text())
        validate_pin(stored, channel)
        expected = {**pin, "sha256": pin["sha256"] or stored["sha256"]}
        if stored != expected:
            raise ValueError(f"LLVM snapshot identity mismatch at {destination}")
        pin = stored
    else:
        with tempfile.TemporaryDirectory(prefix=".fetch-", dir=directory) as work:
            work = Path(work)
            archive = work / "archive"
            pin = download(pin, archive)
            print(f"Extracting {pin['revision']}", file=sys.stderr, flush=True)
            tree = unpack(archive, work / "unpacked", channel)
            save_json(tree / ".crust-fetch.json", pin)
            tree.rename(destination)
    with tempfile.TemporaryDirectory(prefix=".pin-", dir=directory) as work:
        temporary = Path(work) / "pin.json"
        save_json(temporary, pin)
        temporary.replace(selection)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", choices=("release", "main"))
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument(
        "--locked", action="store_true", help="reuse the recorded pin without resolving upstream"
    )
    parser.add_argument(
        "--crust", action="store_true", help="print a Crust LLVM_DIRECTORY constant"
    )
    args = parser.parse_args()
    if args.channel == "release" and (platform.system(), platform.machine()) != ("Linux", "x86_64"):
        parser.error("release tools currently require Linux x86-64")
    try:
        directory = fetch(args.channel, args.directory.resolve(), args.locked)
        if args.crust:
            quoted = "".join(f"\\x{byte:02x}" for byte in str(directory).encode())
            print("// SPDX-License-Identifier: Apache-2.0\n")
            print(f'const LLVM_DIRECTORY:*u8="{quoted}";')
        else:
            print(directory)
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        tarfile.TarError,
        http.client.HTTPException,
    ) as error:
        print(f"fetch LLVM: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
