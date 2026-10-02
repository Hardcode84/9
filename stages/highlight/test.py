# SPDX-License-Identifier: Apache-2.0

"""Check highlighting through the native tool, source runner, and user services."""

import argparse
import json
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class SourceText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_code = False
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag == "code":
            self.in_code = True

    def handle_endtag(self, tag):
        if tag == "code":
            self.in_code = False

    def handle_data(self, data):
        if self.in_code:
            self.text.append(data)


def run(*arguments, **kwargs):
    result = subprocess.run(
        [str(arg) for arg in arguments], cwd=ROOT, capture_output=True, **kwargs
    )
    if result.returncode:
        sys.stderr.buffer.write(result.stdout)
        sys.stderr.buffer.write(result.stderr)
        result.check_returncode()
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    build = args.build.resolve()
    work = build / "highlight-tests"
    work.mkdir(parents=True, exist_ok=True)
    tool = build / "crust-highlight"
    sources = [ROOT / "api/crust0.crs", ROOT / "api/crust0_host.crs"]
    sources += [ROOT / "stages/reader" / name for name in ("model.crs", "lex.crs")]
    sources += [
        ROOT / "stages/highlight" / name
        for name in ("model.crs", "scan.crs", "output.crs", "program.crs")
    ]
    flags = ["--cflag=-O1", "--cflag=-g"]
    if args.sanitize:
        flags += [
            "--cflag=-fsanitize=address,undefined",
            "--cflag=-fno-omit-frame-pointer",
            "--ldflag=-fsanitize=address,undefined",
        ]
        tool = work / "crust-highlight-sanitized"
        run(
            build / "crust-c",
            "-o",
            tool,
            *sources,
            ROOT / "stages/highlight/main.crs",
            *flags,
            "--ldflag",
            build / "libcrust0.a",
            "--ldflag",
            build / "libcrust0_host.a",
        )
    cases = {
        "empty": b"",
        "comments": b"// fn fake() & <script>\r\nfn /* no block comments */ real()->unit{}\n",
        "strings": 'const text:*u8="a\\n<&>😀é";\r\n'.encode(),
        "names": b"var read:u32=0u32; fn move()->unit{} record R{x:u32;} // defer\n",
        "else-if": b"fn choose()->unit{if true{}else if false{}else{}}",
        "broken-string": b'"unfinished\nfn after()->unit{}\n',
        "broken-escape": b'"bad\\q" fn after()->unit{}\n',
        "numbers": b"0 42u32 0xffu8 18446744073709551615u64 0x 4oops 18446744073709551616u64\n",
        "bytes": b'// bad \xff\x00\x1b\n"\xf0\x80\x80\x80"\x00\n',
        "unicode": '😀 fn f()->unit{} // 😀\r\n"é😀"\rvar v:u32=0u32;'.encode(),
    }
    results = {}
    for name, raw in cases.items():
        source = work / (name + ".crs")
        source.write_bytes(raw)
        result = json.loads(run(tool, "--tokens", source))
        assert result["version"] == 1 and result["byteLength"] == len(raw)
        previous = 0
        classified = []
        for begin, end, kind, modifiers in result["spans"]:
            assert previous <= begin < end <= len(raw)
            assert 0 <= kind < len(result["tokenTypes"]) and 0 <= modifiers <= 3
            classified.append((raw[begin:end], result["tokenTypes"][kind], modifiers))
            previous = end
        results[name] = classified
        html = run(tool, "--html", source).decode()
        assert "<script>" not in html
        extracted = SourceText()
        extracted.feed(html)
        displayed = "".join(extracted.text)
        if name == "bytes":
            assert "\\xff\\x00\\x1b" in displayed and "\\xf0\\x80\\x80\\x80" in displayed
        else:
            assert displayed == raw.decode(), (name, displayed)
    assert (b"read", "variable", 1) in results["names"]
    assert (b"move", "function", 1) in results["names"]
    assert [token for token in results["else-if"] if token[1] == "keyword"] == [
        (word, "keyword", 0) for word in (b"fn", b"if", b"true", b"else", b"if", b"false", b"else")
    ]
    for name in ("broken-string", "broken-escape"):
        assert results[name][0][1] == "invalid"
        assert (b"after", "function", 1) in results[name]
    assert [kind for _, kind, _ in results["numbers"]] == ["number"] * 4 + ["invalid"] * 3

    actual = ROOT / "examples/hello/main.crs"
    native = run(tool, "--tokens", actual)
    interpreted = run(build / "crust", "examples/highlight/main.crs", "--tokens", actual)
    assert native == interpreted
    custom = ROOT / "examples/reader-switch/main.crs"
    tokens = json.loads(
        run(build / "crust", "examples/highlight/reader-switch.crs", "--tokens", custom)
    )
    raw = custom.read_bytes()
    assert (b"Hello from a reader written in CRUST!", "string") in [
        (raw[begin:end], tokens["tokenTypes"][kind]) for begin, end, kind, _ in tokens["spans"]
    ]
    unresolved = json.loads(
        run(build / "crust", "examples/highlight/reader-switch.crs", "--tokens", actual)
    )
    assert unresolved["tokenTypes"][unresolved["spans"][0][2]] == "unresolved"
    effect = work / "must-not-exist"
    malicious = work / "effect.crs"
    malicious.write_text(f'crust0_host_write_file("{effect}","bad",3usize);\n')
    run(tool, "--tokens", malicious)
    assert not effect.exists(), "the highlighter executed its input"
    for operands in ([], ["--wrong", str(actual)], [str(work / "missing.crs")]):
        failure = subprocess.run([str(tool), *operands], capture_output=True)
        assert failure.returncode != 0 and failure.stderr and not failure.stdout
    with open("/dev/full", "wb") as stream:
        failure = subprocess.run([str(tool), str(actual)], stdout=stream, stderr=subprocess.PIPE)
        assert failure.returncode != 0 and b"cannot write" in failure.stderr

    budget = work / "budget.crs"
    budget.write_bytes(b";" * 500000)
    assert len(json.loads(run(tool, "--tokens", budget))["spans"]) == 500000
    budget.write_bytes(b";" * 500001)
    failure = subprocess.run([str(tool), "--tokens", str(budget)], capture_output=True)
    assert failure.returncode != 0 and not failure.stdout
    assert b"highlight span limit exceeded" in failure.stderr
    subprocess.run([str(tool), "--html", str(budget)], stdout=subprocess.DEVNULL, check=True)

    run(
        build / "crust-c",
        "-o",
        work / "library-tests",
        *sources,
        ROOT / "stages/highlight/test.crs",
        *flags,
        "--ldflag",
        build / "libcrust0.a",
        "--ldflag",
        build / "libcrust0_host.a",
    )
    large = work / "large.crs"
    large.write_text(
        "// allocation and output growth\n" + "fn sample()->u32{return 42u32;}\n" * 2000
    )
    production = [*sorted((ROOT / "api").glob("*.crs")), *sorted((ROOT / "stages").rglob("*.crs"))]
    run(work / "library-tests", large, *production)
    print(
        f"Highlighting: {len(cases)} boundary inputs, {len(production)} strict lexer comparisons, "
        "all allocation failures, 11 rejected API contracts, token budget, native/root equivalence, custom grammar, "
        "effect isolation, and I/O errors passed"
    )


if __name__ == "__main__":
    main()
