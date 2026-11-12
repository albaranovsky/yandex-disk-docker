"""Read a Debian Packages index from stdin and prepare an upstream update."""
from email.parser import Parser
import json
import os
from pathlib import Path
import re
import sys


def validate(version, sha256):
    if not isinstance(version, str) or not re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", version):
        raise ValueError("Missing or invalid package version")
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha256):
        raise ValueError("Missing or invalid package SHA256")


def prepare_update(raw_info):
    records = [Parser().parsestr(block) for block in re.split(r"\n\s*\n", raw_info.strip())]
    packages = [record for record in records
                if record["Package"] == "yandex-disk" and record["Architecture"] == "amd64"]
    if len(packages) != 1:
        raise ValueError("Expected exactly one yandex-disk amd64 record")
    version, sha256 = packages[0]["Version"], packages[0]["SHA256"]
    validate(version, sha256)
    sha256 = sha256.lower()

    tracked_path = Path(".upstream.json")
    current_version, current_sha256 = "", ""
    if tracked_path.exists():
        tracked = json.loads(tracked_path.read_text())
        if not isinstance(tracked, dict) or tracked.get("package") != "yandex-disk":
            raise ValueError("Invalid .upstream.json package metadata")
        current_version, current_sha256 = tracked.get("version"), tracked.get("sha256")
        validate(current_version, current_sha256)
        current_sha256 = current_sha256.lower()

    print(f"Upstream version: {version}; SHA256: {sha256}")
    print(f"Currently tracked version: {current_version}")
    if version == current_version:
        if sha256 != current_sha256:
            raise ValueError(f"SHA256 changed without a version change ({version}); review the package manually")
        print("Repository is up to date with upstream.")
        return {"has_update": "false"}

    # Prepare and validate all replacements before changing repository files.
    dockerfile_path = Path("Dockerfile")
    dockerfile = dockerfile_path.read_text()
    for name, value in (("YADISK_VERSION", version), ("YADISK_SHA256", sha256)):
        dockerfile, count = re.subn(rf"^ARG {name}=.*$", lambda _: f"ARG {name}={value}",
                                    dockerfile, flags=re.MULTILINE)
        if count != 1:
            raise ValueError(f"Expected exactly one ARG {name}= assignment in Dockerfile")
    changes = {dockerfile_path: dockerfile}
    for name in ("README.md", "DOCKERHUB.md"):
        path = Path(name)
        contents = path.read_text()
        changes[path] = contents.replace(current_version, version) if current_version else contents
    changes[tracked_path] = json.dumps(
        {"package": "yandex-disk", "version": version, "sha256": sha256}, indent=2) + "\n"
    for path, contents in changes.items():
        path.write_text(contents)

    return {"has_update": "true", "old_version": current_version,
            "new_version": version, "new_sha256": sha256}


if __name__ == "__main__":
    try:
        output_path = Path(os.environ["GITHUB_OUTPUT"])
        outputs = prepare_update(sys.stdin.read())
        with output_path.open("a") as output:
            for name, value in outputs.items():
                output.write(f"{name}={value}\n")
    except (OSError, ValueError, KeyError) as error:
        print(f"::error::{error}", file=sys.stderr)
        sys.exit(1)
