#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Measure the paired ownership clients and check their reviewed source budget."""

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

from ownership_support import ROOT, command

BASELINE = ROOT / "tests/ownership_ergonomics.json"
CASES = ("ownership-basics", "intrusive", "ownership-graphs", "ownership-index")
# This is a token counter for the selected sources, not a language parser.
TOKEN = re.compile(
    r'(?P<skip>\s+|//[^\n]*|/\*.*?\*/)|"(?:\\.|[^"\\])*"|'
    r"'[A-Za-z_][A-Za-z_0-9]*|[A-Za-z_][A-Za-z_0-9]*|\d+|&&|\|\||->|::|[^\s]",
    re.DOTALL,
)


def tokens(path):
    return [m[0] for m in TOKEN.finditer(path.read_text()) if m.lastgroup != "skip"]


def functions(source):
    """Separate function definitions from type and module declarations."""
    result = {}
    outside = []
    position = 0
    while position < len(source):
        if source[position] != "fn":
            outside.append(source[position])
            position += 1
            continue
        begin = position
        name = source[position + 1]
        while source[position] not in ("{", ";"):
            position += 1
        if source[position] == ";":
            outside.extend(source[begin : position + 1])
            position += 1
            continue
        depth = 1
        position += 1
        while depth:
            depth += (source[position] == "{") - (source[position] == "}")
            position += 1
        if name in result:
            raise ValueError(f"duplicate function {name}: extend the explicit function mapping")
        result[name] = source[begin:position]
    result["<declarations>"] = outside
    return result


def measure(source, language):
    counts = dict(loans=0, moves=0, cleanup=0, contracts=0, access=0, unsafe=0, pin=0)
    scopes = {}
    position = 0
    while position < len(source):
        word = source[position]
        following = source[position + 1 : position + 3]
        if (
            language == "crs"
            and word in ("domain", "read", "edit")
            and len(following) == 2
            and following[1] == "{"
        ):
            counts["access"] += 2  # mode and domain name
            scopes[word] = scopes.get(word, 0) + 1
            position += 2
            continue
        if language == "crs" and word in ("from", "access"):
            counts["contracts"] += 1
            position += 1
            while source[position] != "{":
                if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", source[position]):
                    counts["contracts"] += 1
                position += 1
            continue
        if word in ("read", "mut", "&"):
            counts["loans"] += 1
        elif word == "move":
            counts["moves"] += 1
        elif word in ("drop", "defer", "forget", "Drop"):
            # Count a destructor declaration, but not the name of its fn body.
            if position == 0 or source[position - 1] != "fn":
                counts["cleanup"] += 1
        elif word in (
            "resource",
            "owns",
            "opaque",
            "stable",
            "scoped",
            "initializes",
        ) or word.startswith("'"):
            counts["contracts"] += 1
        elif word == "unsafe":
            counts["unsafe"] += 1
        elif word == "pin" and following and following[0] == "!":
            counts["pin"] += 1
        position += 1
    result = {"annotations": {key: value for key, value in counts.items() if value}}
    if scopes:
        result["access_scopes"] = scopes
    return result


def report():
    result = {}
    for case in CASES:
        pair = {}
        for language in ("crs", "rs"):
            path = ROOT / "examples" / case / f"program.{language}"
            source = tokens(path)
            pair[language] = {
                "audit_sha256": hashlib.sha256("\n".join(source).encode()).hexdigest(),
                "functions": {
                    name: measure(body, language) for name, body in functions(source).items()
                },
            }
            provider = path.with_name(
                "links.crs" if case == "intrusive" and language == "crs" else f"provider.{language}"
            )
            if provider.exists():
                pair[language]["provider_sha256"] = hashlib.sha256(
                    "\n".join(tokens(provider)).encode()
                ).hexdigest()
        result[case] = pair
    return result


def check_budget(actual):
    baseline = json.loads(BASELINE.read_text())
    if actual != baseline["sources"]:
        changed = [
            f"{case}/program.{language} (or its provider)"
            for case, pair in actual.items()
            for language, source in pair.items()
            if source != baseline["sources"][case][language]
        ]
        raise RuntimeError(
            f"ownership budget changed: {', '.join(changed)}; run with --report, "
            "review per-function counts and restructuring audit, then update tests/ownership_ergonomics.json"
        )
    for case, pair in actual.items():
        scopes = pair["crs"]["functions"]["main"].get("access_scopes", {})
        extra = scopes.get("read", 0) + scopes.get("edit", 0)
        if extra != baseline["audit"]["extra_access_scopes"][case]:
            raise RuntimeError(f"{case}: access-scope audit disagrees with source")
    intrusive = actual["intrusive"]["rs"]["functions"]["main"]["annotations"]
    for category, key in (
        ("unsafe", "rust_intrusive_unsafe_operations"),
        ("pin", "rust_intrusive_pin_bindings"),
    ):
        if intrusive[category] != baseline["audit"][key]:
            raise RuntimeError(f"intrusive: {category} audit disagrees with source")


def check_ports(build, directory, sanitize):
    for case in CASES:
        source = ROOT / "examples" / case
        expected = b"BC\n" if case == "ownership-basics" else b"OK\n"
        trusted = []
        if case != "ownership-basics":
            provider = source / ("links.crs" if case == "intrusive" else "provider.crs")
            trusted = ["trusted", provider]
        for optimization in ("0", "2"):
            crust = directory / f"{case}-crust-{optimization}"
            rust = directory / f"{case}-rust-{optimization}"
            cflags = [f"--cflag=-O{optimization}"]
            rustflags = []
            if sanitize:
                cflags += [
                    "--cflag=-fsanitize=address,undefined",
                    "--cflag=-fno-sanitize-recover=all",
                    "--ldflag=-fsanitize=address,undefined",
                    "--ldflag=-no-pie",
                ]
                rustflags += ["-Zsanitizer=address"]
            command(
                [
                    build / "crust-ownership-test",
                    *trusted,
                    "-o",
                    crust,
                    *cflags,
                    source / "program.crs",
                ]
            )
            rust_command = [
                "rustc",
                "--edition=2024",
                "-Dwarnings",
                f"-Copt-level={optimization}",
                *rustflags,
                source / "program.rs",
                "-o",
                rust,
            ]
            # The installed stable toolchain includes the ASan pass behind this flag.
            if sanitize:
                rust_command = ["env", "RUSTC_BOOTSTRAP=1", *rust_command]
            command(rust_command)
            for arguments in ([], ["one", "two"]):
                for binary in (crust, rust):
                    result = command([binary, *arguments])
                    if result.stdout != expected or result.stderr:
                        raise RuntimeError(f"{binary.name}: {result.stdout!r} {result.stderr!r}")


def check_rust_rejections(directory):
    cases = {
        "tree-drop": (
            "ownership-graphs",
            'let tree=tree_new(1); let cursor=tree_left(&tree); drop(tree); println!("{}",tree_value(&cursor));',
            "E0505",
        ),
        "tree-edit": (
            "ownership-graphs",
            'let mut tree=tree_new(1); let cursor=tree_left(&tree); let child=tree_new(2); tree_attach_left(&mut tree,child); println!("{}",tree_value(&cursor));',
            "E0502",
        ),
        "index-drop": (
            "ownership-index",
            'let index=index_new(); let selected=index_select(&index,1); drop(index); println!("{}",selection_present(&selected));',
            "E0505",
        ),
        "index-remove": (
            "ownership-index",
            'let mut index=index_new(); let selected=index_select(&index,1); index_remove(&mut index,1); println!("{}",selection_present(&selected));',
            "E0502",
        ),
        "intrusive-cursor": (
            "intrusive",
            "let head=std::pin::pin!(Head::new()); let cursor=ready_first(head.as_ref()); let _value=cursor_value(&cursor);",
            "E0133",
        ),
    }
    for name, (case, body, diagnostic) in cases.items():
        path = directory / f"{name}.rs"
        provider = ROOT / "examples" / case / "provider.rs"
        path.write_text(f'#[path="{provider}"] mod provider; use provider::*; fn main(){{{body}}}')
        result = command(
            ["rustc", "--edition=2024", "--emit=metadata", "-o", directory / f"{name}.rmeta", path],
            expected=1,
        )
        if diagnostic not in result.stderr.decode():
            raise RuntimeError(f"{name}: missing {diagnostic}: {result.stderr.decode()}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument(
        "--report", action="store_true", help="print current counts without accepting them"
    )
    parser.add_argument("--counts-only", action="store_true")
    parser.add_argument("--sanitize", action="store_true")
    options = parser.parse_args()
    actual = report()
    if options.report:
        print(json.dumps(actual, indent=2))
        return
    check_budget(actual)
    if not options.counts_only:
        build = options.build.resolve()
        with tempfile.TemporaryDirectory(prefix="ergonomics-", dir=build) as temporary:
            directory = Path(temporary)
            check_ports(build, directory, options.sanitize)
            check_rust_rejections(directory)
    print("ownership ergonomics: reviewed counts and requested checks passed")


if __name__ == "__main__":
    main()
