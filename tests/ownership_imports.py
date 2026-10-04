#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise verified provider objects and bodyless ownership interfaces."""

import argparse
import hashlib
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TAG = b"crust-ownership-library-v2-linux-x64\n"


def command(args, *, env=None, success=True):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=120)
    if (result.returncode == 0) != success:
        raise AssertionError(f"{args}\nstatus {result.returncode}\n{result.stdout}{result.stderr}")
    if not success and (result.returncode < 0 or not result.stderr):
        raise AssertionError(f"failure must retain a diagnostic: {args}\n{result}")
    return result


def publish(driver, cache, sources, *options):
    result = command([driver, "publish", str(cache), *options, *map(str, sources)])
    artifact, digest = result.stdout.splitlines()
    assert hashlib.sha256(Path(artifact).read_bytes()).hexdigest() == digest
    return Path(artifact), digest


def unpack(data):
    assert data.startswith(TAG)
    offset = len(TAG) + 128
    interface_size, object_size = struct.unpack_from("<QQ", data, offset)
    start = offset + 24
    end = start + interface_size
    assert end + object_size == len(data)
    return start, end, data[start:end].decode()


def fixture(directory, name="program.crs"):
    tutorial = ROOT / "examples/intrusive"
    source = (tutorial / name).read_text()
    links = directory / "links.crs"
    library = directory / "provider.crs"
    consumer = directory / "client.crs"
    links.write_bytes((tutorial / "links.crs").read_bytes())
    library.write_text(
        "fn client_read(owner:read Owner)->read i64 access(read,Graph) from owner {return owner_value(read owner);}"
    )
    consumer.write_text(source)
    return links, library, consumer


def import_arguments(driver, cache, receipt, client, output, trusted=False):
    artifact, digest = receipt
    return [
        driver,
        "import-trusted" if trusted else "import",
        str(cache),
        str(artifact),
        digest,
        "-o",
        str(output),
        str(client),
    ]


def reject_import(args, environment, message):
    result = command(args, env=environment, success=False)
    assert message in result.stderr, result.stderr


def tamper_checks(args, environment, receipt):
    artifact, digest = receipt
    original = artifact.read_bytes()
    sidecar = artifact.with_name("checksum")
    original_checksum = sidecar.read_bytes()
    start, end, interface = unpack(original)
    assert "fn owner_drop" in interface and "fn ready_unlink" in interface
    assert "opaque" in interface and "scoped" in interface
    assert "domain Graph(Node, Owner, ReadyHead, ActiveHead, Cursor);" in interface
    assert "from owner" in interface
    assert "var " not in interface and "while " not in interface
    mutations = {
        "function contract": original.replace(b"access(read, Graph)", b"access(edit, Graph)", 1),
        "type layout": original.replace(b"value: i64", b"value: i32", 1),
        "trust contract": original[: len(TAG) + 144]
        + struct.pack("<Q", 0)
        + original[len(TAG) + 152 :],
        "object": original[:end] + bytes([original[end] ^ 1]) + original[end + 1 :],
        "truncated object": original[:-1],
        "trailing bytes": original + b"unbound bytes",
    }
    assert start < end < len(original)
    try:
        for name, data in mutations.items():
            assert data != original, name
            artifact.write_bytes(data)
            # A self-updated checksum is not evidence that this code was verified.
            sidecar.write_text(hashlib.sha256(data).hexdigest())
            reject_import(args, environment, "trusted digest receipt")
    finally:
        artifact.write_bytes(original)
        sidecar.write_bytes(original_checksum)
    bad_receipt = list(args)
    bad_receipt[4] = "0" * 64
    reject_import(bad_receipt, environment, "trusted digest receipt")
    assert hashlib.sha256(original).hexdigest() == digest
    return len(mutations) + 1


def changed_checker(directory, driver, args, environment):
    other = directory / "changed-checker"
    shutil.copy2(driver, other)
    with other.open("ab") as stream:
        stream.write(b"different compiler artifact")
    changed = [str(other), *args[1:]]
    reject_import(changed, environment, "checker host or loaded images changed")


def capture_race(directory, args, environment, receipt, output):
    artifact, _ = receipt
    before = artifact.read_bytes()
    tools = directory / "tools"
    tools.mkdir()
    marker = directory / "replaced"
    replacement = directory / "replacement"
    replacement.write_bytes(b"replaced after validation")
    gcc = shutil.which("gcc")
    assert gcc is not None
    wrapper = tools / "gcc"
    wrapper.write_text(
        "#!/usr/bin/python3\nimport os,sys\nfrom pathlib import Path\n"
        f"marker=Path({str(marker)!r})\n"
        "if not marker.exists():\n"
        f"    os.replace({str(replacement)!r}, {str(artifact)!r})\n"
        "    marker.touch()\n"
        f"os.execv({gcc!r}, [{gcc!r}, *sys.argv[1:]])\n"
    )
    wrapper.chmod(0o700)
    race_environment = dict(environment, PATH=str(tools) + os.pathsep + environment.get("PATH", ""))
    try:
        command(args, env=race_environment)
        assert marker.exists(), "GCC wrapper did not replace the published path"
        assert command([str(output)]).stdout == "OK\n"
    finally:
        artifact.write_bytes(before)


def source_checks(directory, driver, cache, links, library, client, environment, receipt):
    original = library.read_text()
    bad = directory / "bad-provider.crs"
    bad.write_text(
        original
        + "fn invalid()->Owner access(reclaim,Graph) {var a:Owner=owner_new(1i64);return a;}"
    )
    command([driver, "publish", str(cache), "trusted", str(links), str(bad)], success=False)
    changed = directory / "changed-provider.crs"
    changed.write_text(original + "\nfn additional(value:i32)->i32 { return value; }\n")
    new_receipt = publish(driver, cache, [changed], "trusted", str(links))
    first = receipt[0].read_bytes()
    second = new_receipt[0].read_bytes()
    assert first[len(TAG) + 64 : len(TAG) + 128] != second[len(TAG) + 64 : len(TAG) + 128]
    args = import_arguments(
        driver, cache, (new_receipt[0], receipt[1]), client, directory / "mismatched", trusted=True
    )
    reject_import(args, environment, "trusted digest receipt")
    # Interface text has no authority when copied into ordinary application input.
    _, _, interface = unpack(first)
    forged = directory / "unverified-interface.crs"
    forged.write_text(interface + client.read_text())
    command([driver, "publish", str(cache), str(forged)], success=False)
    bad_client = directory / "bad-client.crs"
    bad_client.write_text(
        client.read_text().replace(
            "var second: Owner = owner_new(66i64);", "var second: Owner = first;", 1
        )
    )
    args = import_arguments(
        driver, cache, receipt, bad_client, directory / "bad-client", trusted=True
    )
    command(args, env=environment, success=False)
    return 4


def run(build):
    driver = str(build / "crust-ownership-import-test")
    scratch = build / "ownership-contracts"
    scratch.mkdir(exist_ok=True)
    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(prefix="imports-", dir=scratch) as temporary:
        directory = Path(temporary)
        cache = directory / "cache"
        cache.mkdir(mode=0o700)
        links, library, client = fixture(directory)
        receipt = publish(driver, cache, [library], "trusted", str(links))
        rejected = source_checks(
            directory, driver, cache, links, library, client, environment, receipt
        )
        links.unlink()
        library.unlink()
        output = directory / "client"
        args = import_arguments(driver, cache, receipt, client, output, trusted=True)
        command(args, env=environment)
        assert command([str(output)]).stdout == "OK\n"
        retagged = directory / "retagged.crs"
        retagged.write_text("domain Other(Owner);\n" + client.read_text())
        retagged_args = import_arguments(
            driver, cache, receipt, retagged, directory / "retagged", trusted=True
        )
        reject_import(retagged_args, environment, "record cannot belong to multiple domains")
        rejected += 1
        wrong_trust = [args[0], "import", *args[2:]]
        reject_import(wrong_trust, environment, "trust contract differs")
        rejected += 1
        for mode in ("--object", "--emit-c", "--prepare"):
            options = [*args[:5], str(client), mode]
            reject_import(options, environment, "loses imported dependencies")
            rejected += 1
        rejected += tamper_checks(args, environment, receipt)
        changed_checker(directory, driver, args, environment)
        rejected += 1
        capture_race(directory, args, environment, receipt, output)
        allocation_provider = directory / "allocation-provider.crs"
        allocation_provider.write_text(
            "// SPDX-License-Identifier: Apache-2.0\nfn value()->i32 { return 0i32; }\n"
        )
        swept = command([driver, "sweep", "publish", str(cache), str(allocation_provider)])
        artifact, digest = swept.stdout.splitlines()
        allocation_client = directory / "allocation-client.crs"
        allocation_client.write_text(
            "// SPDX-License-Identifier: Apache-2.0\nfn main(argc:i32,argv:**u8)->i32 { return value(); }\n"
        )
        command(
            [
                driver,
                "sweep",
                "import",
                str(cache),
                artifact,
                digest,
                "--check",
                str(allocation_client),
            ],
            env=environment,
        )
        assert not list(cache.glob(".build-*")), "private import/publication files leaked"
    print(
        f"ownership imports: source-free provider/client, captured linking, {rejected} rejections passed"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", default="build")
    args = parser.parse_args()
    run((ROOT / args.build).resolve())


if __name__ == "__main__":
    main()
