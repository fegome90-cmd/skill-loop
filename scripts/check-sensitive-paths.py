import os
from pathlib import Path
import re
import subprocess
import sys


ENV_TEMPLATES = {".env.example", ".env.sample", ".env.template"}
PRIVATE_DIRECTORIES = {".ssh", ".aws", ".gnupg"}
PRIVATE_NAMES = {
    ".envrc", ".gitleaksignore", ".netrc", "_netrc", "credentials", "secrets",
    "id_rsa", "id_dsa", "id_ecdsa", "id_ecdsa_sk", "id_ed25519", "id_ed25519_sk",
}
KEY_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".ppk", ".jks", ".keystore")
CREDENTIAL_JSON = re.compile(r"(?:credentials|secrets|client[_-]secrets?|service[_-]account)(?:[-_.].+)?\.json\Z")


def git(*args):
    return subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)


def blocked_path(path):
    *directories, name = os.fsdecode(path).lower().split("/")
    return (
        not PRIVATE_DIRECTORIES.isdisjoint(directories)
        or name in PRIVATE_NAMES
        or name.endswith(KEY_SUFFIXES)
        or CREDENTIAL_JSON.fullmatch(name) is not None
        or ((name == ".env" or name.startswith(".env.")) and name not in ENV_TEMPLATES)
    )


def staged_entries():
    for entry in git("ls-files", "--stage", "-z").split(b"\0"):
        if entry:
            metadata, path = entry.split(b"\t", 1)
            mode, object_id, stage = metadata.split()
            if stage != b"0":
                raise ValueError("Unmerged index")
            yield mode, object_id, path


def history_paths():
    for revision in git("rev-list", "HEAD").decode("ascii").splitlines():
        yield from git("ls-tree", "-rz", "--name-only", revision).split(b"\0")


def reject_blocked(paths):
    blocked = {path for path in paths if path and blocked_path(path)}
    if blocked:
        print(f"Security check found {len(blocked)} disallowed Git filename(s).", file=sys.stderr)
        return 1
    return 0


def snapshot_index(destination):
    entries = list(staged_entries())
    if reject_blocked(path for _, _, path in entries):
        return 1

    for mode, object_id, path in entries:
        if mode == b"160000":
            # A submodule entry stores a commit reference rather than file content.
            continue
        target = destination / os.fsdecode(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write blobs as regular files, including the literal target of any symlink.
        with target.open("xb") as output:
            subprocess.run(
                ["git", "cat-file", "blob", object_id.decode("ascii")],
                stdout=output, stderr=subprocess.DEVNULL, check=True,
            )
    return 0


def main(args):
    try:
        if len(args) == 2 and args[0] == "staged":
            return snapshot_index(Path(args[1]))
        if args == ["history"]:
            return reject_blocked(history_paths())
    except (OSError, ValueError, subprocess.SubprocessError):
        print("Security check could not read Git filenames or objects.", file=sys.stderr)
        return 1
    print("Use check-secrets.sh staged|history.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
