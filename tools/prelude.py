# SPDX-License-Identifier: Apache-2.0

"""Embed the installed root interfaces and helper source in the launcher."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (
    "api/crust0.crs",
    "api/crust0_host.crs",
    "api/crust0_eval.crs",
    "api/crust0_run.crs",
    "stages/host_posix.crs",
    "stages/host.crs",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--api-root", type=Path, default=ROOT)
    parser.add_argument("--profile", choices=("linux_x64", "windows_x64"), default="linux_x64")
    args = parser.parse_args()
    inputs = list(INPUTS)
    if args.profile == "windows_x64":
        inputs[4] = "stages/host_windows.crs"
    lines = ["/* SPDX-License-Identifier: Apache-2.0 */", ""]
    for index, name in enumerate(inputs):
        base = args.api_root if name.startswith("api/") else ROOT
        data = (base / name).read_bytes()
        lines.append(f"static const unsigned char prelude_{index}[] = {{")
        for offset in range(0, len(data), 32):
            lines.append("    " + ",".join(str(byte) for byte in data[offset : offset + 32]) + ",")
        lines.append("};")
    lines.append("static const CrustSource installed_sources[] = {")
    for index, name in enumerate(inputs):
        lines.append(
            f'    {{"<installed {name}>", prelude_{index}, sizeof(prelude_{index}), {index + 1}}},'
        )
    lines.extend(["};", ""])
    args.output.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
