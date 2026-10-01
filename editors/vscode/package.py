# SPDX-License-Identifier: Apache-2.0

"""Package the local Linux x86-64 highlighter without a JavaScript build tool."""

import argparse
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    directory = Path(__file__).resolve().parent
    package = json.loads((directory / "package.json").read_text())
    manifest = ET.Element(
        "PackageManifest",
        Version="2.0.0",
        xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011",
    )
    metadata = ET.SubElement(manifest, "Metadata")
    ET.SubElement(
        metadata,
        "Identity",
        Language="en-US",
        Id=package["name"],
        Version=package["version"],
        Publisher=package["publisher"],
        TargetPlatform="linux-x64",
    )
    ET.SubElement(metadata, "DisplayName").text = package["displayName"]
    ET.SubElement(metadata, "Description").text = package["description"]
    ET.SubElement(metadata, "Categories").text = "Programming Languages"
    ET.SubElement(metadata, "License").text = "extension/LICENSE"
    properties = ET.SubElement(metadata, "Properties")
    for name, value in (
        ("Microsoft.VisualStudio.Code.Engine", package["engines"]["vscode"]),
        ("Microsoft.VisualStudio.Code.ExtensionKind", "workspace"),
    ):
        ET.SubElement(properties, "Property", Id=name, Value=value)
    targets = ET.SubElement(manifest, "Installation")
    ET.SubElement(targets, "InstallationTarget", Id="Microsoft.VisualStudio.Code")
    ET.SubElement(manifest, "Dependencies")
    assets = ET.SubElement(manifest, "Assets")
    ET.SubElement(
        assets,
        "Asset",
        Type="Microsoft.VisualStudio.Code.Manifest",
        Path="extension/package.json",
        Addressable="true",
    )
    types = ET.Element(
        "Types", xmlns="http://schemas.openxmlformats.org/package/2006/content-types"
    )
    for extension, content in (
        ("json", "application/json"),
        ("cjs", "application/javascript"),
        ("md", "text/markdown"),
        ("vsixmanifest", "text/xml"),
    ):
        ET.SubElement(types, "Default", Extension=extension, ContentType=content)
    ET.SubElement(
        types,
        "Override",
        PartName="/extension/LICENSE",
        ContentType="text/plain",
    )
    ET.SubElement(
        types,
        "Override",
        PartName="/extension/bin/crust-highlight",
        ContentType="application/octet-stream",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("extension.vsixmanifest", ET.tostring(manifest))
        archive.writestr("[Content_Types].xml", ET.tostring(types))
        for name in (
            "package.json",
            "extension.cjs",
            "adapter.cjs",
            "language-configuration.json",
            "README.md",
        ):
            archive.write(directory / name, "extension/" + name)
        archive.write(directory.parents[1] / "LICENSE", "extension/LICENSE")
        archive.write(args.binary, "extension/bin/crust-highlight")
    print(args.output)


if __name__ == "__main__":
    main()
