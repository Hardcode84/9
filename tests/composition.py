#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check ordered reader and source services through ownership and native output."""

import argparse
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(argv, expected=0):
    result = subprocess.run([str(arg) for arg in argv], cwd=ROOT, capture_output=True, timeout=60)
    if result.returncode != expected:
        raise AssertionError((argv, result.returncode, result.stdout, result.stderr))
    return result


def rejections():
    common = (ROOT / "examples/composition/program.crs").read_text().split("fn main(")[0]
    main = "fn main(argc:i32,argv:**u8)->i32{"
    owner = "var ticket:Ticket=make Ticket{value:65i32};"
    yield "use-after-move", common + main + owner + "var other:Ticket=move ticket;choose(read ticket);return 0i32;}", "value is uninitialized or has been moved"
    yield "exclusive-conflict", common + main + owner + "var view:read Ticket=read ticket;choose(mut ticket);drop view;return 0i32;}", "active"
    yield "wrong-overload", common + main + "choose(1i32);return 0i32;}", "no overload matches"
    yield "unverified-import", common + "fn external(value:read Ticket)->unit;" + main + owner + "external(read ticket);return 0i32;}", "verified interface or explicit root trust"
    yield "result-contract", common + "fn borrow(a:read Ticket,b:read Ticket)->read Ticket from a;fn borrow(a:read Ticket,b:read Ticket)->read Ticket from b{return read b;}" + main + "return 0i32;}", "different contracts"
    yield "access-contract", common + "domain D(Plain);fn touch(p:mut Plain)->unit access(edit,D);fn touch(p:mut Plain)->unit access(reclaim,D){}" + main + "return 0i32;}", "different contracts"
    yield "initializes-contract", common + "fn init(p:mut Plain)->unit initializes(p);fn init(p:mut Plain)->unit{}" + main + "return 0i32;}", "different contracts"
    yield "modifies-contract", common + "domain D(Plain);fn edit(p:mut Plain)->unit access(edit,D) modifies(Plain.value);fn edit(p:mut Plain)->unit access(edit,D) modifies(){}" + main + "return 0i32;}", "different contracts"
    yield "native-contract", common + 'extern fn consume(v:isize)->unit foreign(scalar)="consume";extern fn consume(v:isize)->unit foreign(move v:Handle.id)="consume";' + main + "return 0i32;}", "different contracts"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    build = args.build.resolve()
    compiler = build / "composition-test"
    with tempfile.TemporaryDirectory(prefix="composition-", dir=build) as directory:
        work = Path(directory)
        target = work / "target"
        example = (ROOT / "examples/composition/program.crs").read_text()
        # Matching interfaces can rename parameters. Contract identity uses positions.
        prototype = "\nfn choose(other:read Ticket)->i32;\n"
        cases = [
            example,
            example + prototype,
            prototype + example,
            example + "\nfn borrow(a:read Ticket)->read Ticket from a;"
            "fn borrow(b:read Ticket)->read Ticket from b{return read b;}\n",
        ]
        for index, text in enumerate(cases):
            source = work / f"positive-{index}.crs"
            source.write_text(text)
            run([compiler, source, target])
            result = run([target])
            assert result.stdout == b"!B", result
        for name, text, diagnostic in rejections():
            source = work / f"{name}.crs"
            source.write_text(text)
            target.unlink(missing_ok=True)
            result = run([compiler, source, target], expected=1)
            assert diagnostic.encode() in result.stderr, (name, result.stderr)
            assert not target.exists(), name
    print("Composition: 4 sanitized runtime cases and 9 rejections passed")


if __name__ == "__main__":
    main()
