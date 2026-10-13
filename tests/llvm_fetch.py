#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check LLVM fetch pins, reuse, archive validation and failed publication."""

import hashlib
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("fetch_llvm", ROOT / "tools/fetch_llvm.py")
FETCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FETCH)


def archive(channel, payload=b"test", extra=None):
    output = io.BytesIO()
    files = ("llvm/CMakeLists.txt",) if channel == "main" else ("bin/llc", "bin/opt")
    with tarfile.open(fileobj=output, mode="w:gz") as stream:
        for name in files:
            member = tarfile.TarInfo(f"llvm/{name}")
            member.mode = 0o755
            member.size = len(payload)
            stream.addfile(member, io.BytesIO(payload))
        if extra is not None:
            stream.addfile(extra)
    return output.getvalue()


class FetchTests(unittest.TestCase):
    def setUp(self):
        (ROOT / "build").mkdir(exist_ok=True)
        self.work = tempfile.TemporaryDirectory(dir=ROOT / "build", prefix="llvm-fetch-test-")
        self.addCleanup(self.work.cleanup)
        self.directory = Path(self.work.name)
        self.routes = {}
        self.requests = []
        self.network = patch.object(FETCH, "open_url", self.open_url)
        self.network.start()
        self.addCleanup(self.network.stop)

    def open_url(self, url):
        self.requests.append(url)
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value)

    def upstream(self, channel, revision, payload=None):
        data = archive(channel) if payload is None else payload
        if channel == "release":
            name = f"LLVM-{revision.removeprefix('llvmorg-')}-Linux-X64.tar.xz"
            url = f"https://github.com/llvm/llvm-project/releases/download/{revision}/{name}"
            metadata = {
                "tag_name": revision,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {
                        "name": name,
                        "browser_download_url": url,
                        "digest": "sha256:" + hashlib.sha256(data).hexdigest(),
                    }
                ],
            }
            self.routes[f"{FETCH.API}/releases/latest"] = json.dumps(metadata).encode()
        else:
            self.routes[f"{FETCH.API}/commits/main"] = json.dumps({"sha": revision}).encode()
            url = f"https://codeload.github.com/llvm/llvm-project/tar.gz/{revision}"
        self.routes[url] = data
        return url

    def test_refresh_and_locked_reuse(self):
        for channel, revisions in (
            ("release", ("llvmorg-23.1.3", "llvmorg-23.1.4")),
            ("main", ("a" * 40, "b" * 40)),
        ):
            with self.subTest(channel=channel):
                self.upstream(channel, revisions[0])
                first = FETCH.fetch(channel, self.directory)
                pin = json.loads((self.directory / f"{channel}.json").read_text())
                self.assertEqual(pin["revision"], revisions[0])
                self.assertEqual(pin["sha256"], hashlib.sha256(archive(channel)).hexdigest())
                self.requests.clear()
                self.assertEqual(FETCH.fetch(channel, self.directory, locked=True), first)
                self.assertEqual(self.requests, [])
                self.assertEqual(FETCH.fetch(channel, self.directory), first)
                self.assertEqual(len(self.requests), 1)
                self.upstream(channel, revisions[1])
                second = FETCH.fetch(channel, self.directory)
                self.assertNotEqual(first, second)
                self.assertTrue(first.is_dir())
                self.assertTrue(second.is_dir())

    def test_failed_refresh_preserves_selection(self):
        self.upstream("release", "llvmorg-23.1.3")
        FETCH.fetch("release", self.directory)
        selection = self.directory / "release.json"
        old = selection.read_bytes()
        url = self.upstream("release", "llvmorg-23.1.4")
        self.routes[url] = b"corrupted"
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            FETCH.fetch("release", self.directory)
        self.assertEqual(selection.read_bytes(), old)
        self.assertFalse((self.directory / "release-llvmorg-23.1.4").exists())
        self.assertFalse(list(self.directory.glob(".fetch-*")))
        self.routes[url] = OSError("connection lost")
        with self.assertRaisesRegex(OSError, "connection lost"):
            FETCH.fetch("release", self.directory)
        self.assertEqual(selection.read_bytes(), old)

    def test_locked_redownload_verifies_main_digest(self):
        url = self.upstream("main", "a" * 40)
        tree = FETCH.fetch("main", self.directory)
        tree.rename(self.directory / "retained")
        del self.routes[f"{FETCH.API}/commits/main"]
        self.assertEqual(FETCH.fetch("main", self.directory, locked=True), tree)
        tree.rename(self.directory / "retained-again")
        self.routes[url] = archive("main", b"changed bytes")
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            FETCH.fetch("main", self.directory, locked=True)

    def test_reject_unsafe_archive(self):
        for name, target in (("../escape", ""), ("llvm/escape", "../../escape")):
            member = tarfile.TarInfo(name)
            if target:
                member.type = tarfile.SYMTYPE
                member.linkname = target
            self.upstream("main", "a" * 40, archive("main", extra=member))
            with self.assertRaises(tarfile.FilterError):
                FETCH.fetch("main", self.directory)
            self.assertFalse((self.directory / "main.json").exists())
            self.assertFalse((self.directory / "escape").exists())

    def test_reject_missing_tools_and_metadata(self):
        self.upstream("release", "llvmorg-23.1.3", archive("main"))
        with self.assertRaisesRegex(ValueError, "missing bin/llc"):
            FETCH.fetch("release", self.directory)
        key = f"{FETCH.API}/releases/latest"
        metadata = json.loads(self.routes[key])
        metadata["assets"][0]["digest"] = None
        self.routes[key] = json.dumps(metadata).encode()
        with self.assertRaisesRegex(ValueError, "no SHA-256"):
            FETCH.fetch("release", self.directory)
        with self.assertRaises(FileNotFoundError):
            FETCH.fetch("main", self.directory, locked=True)

    def test_cli_reports_failure(self):
        arguments = ["fetch_llvm.py", "main", "--locked", "--directory", str(self.directory)]
        with (
            patch.object(sys, "argv", arguments),
            patch("sys.stderr", new_callable=io.StringIO) as error,
        ):
            self.assertEqual(FETCH.main(), 1)
            self.assertIn("fetch LLVM:", error.getvalue())

    def test_reject_invalid_pin_and_snapshot_identity(self):
        selection = self.directory / "main.json"
        selection.write_text('{"revision":"../../escape"}')
        with self.assertRaisesRegex(ValueError, "invalid LLVM pin"):
            FETCH.fetch("main", self.directory, locked=True)
        self.assertEqual(self.requests, [])
        self.upstream("main", "a" * 40)
        tree = FETCH.fetch("main", self.directory)
        pin = json.loads(selection.read_text())
        pin["sha256"] = "0" * 64
        (tree / ".crust-fetch.json").write_text(json.dumps(pin))
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            FETCH.fetch("main", self.directory, locked=True)


if __name__ == "__main__":
    unittest.main()
