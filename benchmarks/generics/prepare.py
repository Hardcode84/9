#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Capture compiled ownership and standalone generics measurement drivers."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
import generics_cost as pair_cost  # noqa: E402
import ownership_generics_cost as ownership_cost  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--build", type=Path, default=ROOT / "build")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--cflags", default="-O2 -g")
    parser.add_argument("--ldflags", default="")
    args = parser.parse_args()
    work = args.work.resolve()
    args.build = args.build.resolve()
    if work.exists() or not work.is_relative_to(ROOT / "build"):
        parser.error("select a new directory under build/")
    work.mkdir(parents=True)
    for name, module in (("ownership", ownership_cost), ("pair", pair_cost)):
        folder = work / name
        folder.mkdir()
        binary, preparation = module.prepare(args, folder)
        if name == "ownership":
            module.capture(folder)
        else:
            module.inputs(folder)
        backend = args.build / "crust-c"
        preparation["sha256"][str(backend)] = pair_cost.fingerprint(backend)
        snapshot = folder / "snapshot"
        for original, digest in preparation["sha256"].items():
            source = Path(original)
            if not source.is_relative_to(ROOT):
                raise RuntimeError(f"measurement input is outside the checkout: {source}")
            target = snapshot / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            if pair_cost.fingerprint(target) != digest:
                raise RuntimeError(f"input changed during preparation: {source}")
        preparation["driver_sha256"] = pair_cost.fingerprint(binary)
        (folder / "preparation.json").write_text(json.dumps(preparation, indent=2) + "\n")
    print(work)


if __name__ == "__main__":
    main()
