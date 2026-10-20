# Copyright Callback LLP. All Rights Reserved.
"""KLETKA ModKit installer. Only manifest-owned, unchanged files may be replaced."""
import argparse
import contextlib
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.request
from urllib.parse import urlsplit
import uuid
import zipfile

REPOSITORY = "CallbackGames/KLETKA-ModKit"
STATE = ".modkit-update"
MANIFEST = "Config/ModKitReleaseManifest.json"
MAX_ARCHIVE = 2 * 1024**3
MAX_EXPANDED = 8 * 1024**3


def sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def safe_name(name):
    if (not isinstance(name, str) or not name or any(c in name for c in '\\:*?"<>|')
            or name.startswith("/") or any(ord(c) < 32 for c in name)
            or any(p in ("", ".", "..") for p in name.split("/"))):
        raise ValueError("Unsafe package path")
    for p in name.split("/"):
        if (p.endswith((" ", ".")) or p.split(".")[0].upper() in
                {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                 *(f"LPT{i}" for i in range(1, 10))}):
            raise ValueError("Unsafe Windows filename")
    if name.split("/")[0].lower() in {STATE, ".git", ".p4config", "saved", "deriveddatacache"}:
        raise ValueError("Package must not manage user state")
    return name


def no_links(path):
    path = Path(os.path.abspath(path))
    for p in [*reversed(path.parents), path]:
        if p.exists() or p.is_symlink():
            info = p.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked/reparse path is not supported: " + str(p))
    return path


def child(root, name):
    return no_links(root / safe_name(name))


def atomic_json(path, data):
    no_links(path)
    fd, name = tempfile.mkstemp(prefix=".writing-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def fingerprint(path):
    no_links(path)
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError("Expected file: " + str(path))
    return {"size": path.stat().st_size, "sha256": sha(path)}


@contextlib.contextmanager
def locked(root):
    root = no_links(root)
    if root == root.parent:
        raise ValueError("Choose a dedicated ModKit directory")
    root.mkdir(parents=True, exist_ok=True)
    folder = no_links(root / STATE)
    folder.mkdir(exist_ok=True)
    lock = no_links(folder / "lock").open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if lock.read(1) == b"":
                lock.write(b"\0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield folder
    finally:
        lock.close()


def editor_closed():
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, check=True)
        rows = csv.reader(io.StringIO(result.stdout.decode(errors="replace")))
        if any(row and row[0].lower() in ("unrealeditor.exe", "unrealeditor-cmd.exe") for row in rows):
            raise ValueError("Close Unreal Editor before changing ModKit files")


def unpack(archive, asset, destination):
    if fingerprint(archive) != {"size": asset["size"], "sha256": asset["sha256"]}:
        raise ValueError("Archive SHA-256/size mismatch")
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if len(names) != len({n.casefold() for n in names}):
            raise ValueError("Duplicate package paths")
        for name in names:
            safe_name(name)
        raw = z.read(MANIFEST)
        if hashlib.sha256(raw).hexdigest() != asset["release_manifest_sha256"]:
            raise ValueError("Release inventory hash mismatch")
        manifest = json.loads(raw.decode("utf-8-sig"))
        if manifest.get("DistributionKind") != asset["kind"]:
            raise ValueError("Distribution kind mismatch")
        entries = manifest["Files"]
        if manifest.get("FileCount") != len(entries):
            raise ValueError("Invalid inventory count")
        files = {}
        for entry in entries:
            name = safe_name(entry["Path"])
            if (not isinstance(entry["Size"], int) or entry["Size"] < 0
                    or not re.fullmatch("[a-f0-9]{64}", entry["Sha256"])):
                raise ValueError("Invalid inventory entry")
            files[name] = {"size": entry["Size"], "sha256": entry["Sha256"]}
        if len(files) != len(entries):
            raise ValueError("Duplicate inventory paths")
        files[MANIFEST] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        if set(names) != set(files):
            raise ValueError("Unexpected or missing archive files")
        folded = {n.casefold() for n in files}
        for name in files:
            if any(str(p).casefold() in folded for p in PurePosixPath(name).parents if str(p) != "."):
                raise ValueError("File/directory collision")
        total = sum(item["size"] for item in files.values())
        if total > MAX_EXPANDED or shutil.disk_usage(destination.parent).free < total * 3 + 512 * 1024**2:
            raise ValueError("Insufficient free space or oversized package")
        for name, expected in files.items():
            info = z.getinfo(name)
            if (info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)
                    or info.file_size != expected["size"] or info.flag_bits & 1):
                raise ValueError("Invalid archive entry")
            file = child(destination, name)
            file.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, file.open("xb") as out:
                shutil.copyfileobj(src, out, 1024 * 1024)
            if fingerprint(file) != expected:
                raise ValueError("Extracted file checksum mismatch")
    return files


def restore(root, tx, allow_partial=False):
    meta = read(no_links(tx / "transaction.json"))
    # Validate everything before rolling back even one file.
    for name, operation in meta["operations"].items():
        current = fingerprint(child(root, name))
        allowed = [operation["after"]]
        if allow_partial:
            allowed.append(operation["before"])
        if current not in allowed:
            raise ValueError("Rollback conflict; user file retained: " + name)
        if operation["before"] is not None:
            if fingerprint(child(tx / "backup", name)) != operation["before"]:
                raise ValueError("Rollback backup damaged: " + name)
    # A crash during rollback is recoverable by the same journal as an interrupted update.
    atomic_json(root / STATE / "pending.json", {"transaction": tx.name})
    for name, operation in reversed(list(meta["operations"].items())):
        target = child(root, name)
        if fingerprint(target) == operation["before"]:
            continue
        if operation["before"] is None:
            target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            # Do not consume the backup, so interrupted rollback can be retried.
            replacement = child(tx / "payload", name)
            replacement.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(child(tx / "backup", name), replacement)
            os.replace(replacement, target)
    atomic_json(root / STATE / "state.json", meta["before_state"])
    pending = root / STATE / "pending.json"
    if pending.exists():
        pending.unlink()
    clean_payload(tx)


def clean_payload(tx):
    """Delete only our verified extraction directory, never a ModKit/user directory."""
    tx = no_links(tx)
    payload = no_links(tx / "payload")
    if (tx.parent.name != "transactions" or tx.parent.parent.name != STATE
            or not re.fullmatch("[a-f0-9]{32}", tx.name)
            or payload.parent != tx):
        raise ValueError("Invalid staging directory")
    if payload.exists():
        for directory, dirs, files in os.walk(payload):
            for name in dirs + files:
                no_links(Path(directory) / name)
        shutil.rmtree(payload)


def install(root, archive, asset, release, fault=None):
    root = no_links(root)
    with locked(root) as folder:
        pending = folder / "pending.json"
        if pending.exists():
            raise ValueError("Interrupted update: run with --recover first")
        old = read(folder / "state.json") if (folder / "state.json").exists() else {}
        if old and old.get("kind") != asset["kind"]:
            raise ValueError("Use a separate directory for a different distribution kind")
        tx_id = uuid.uuid4().hex
        tx = no_links(folder / "transactions" / tx_id)
        payload = tx / "payload"
        payload.mkdir(parents=True)
        new_files = unpack(Path(archive), asset, payload)
        old_files = old.get("files", {})
        operations = {}
        for name in sorted(set(old_files) | set(new_files)):
            target = child(root, name)
            current, before, after = fingerprint(target), old_files.get(name), new_files.get(name)
            if name in old_files:
                if current != before:
                    raise ValueError("Locally changed SDK file retained: " + name)
            elif current is not None and current != after:
                raise ValueError("User file would be overwritten; update stopped: " + name)
            if current != after:
                operations[name] = {"before": current, "after": after}
        if not operations and old:
            clean_payload(tx)
            return {"unchanged": True, "release": old["release"], "preserved_user_files": True}
        for name, operation in operations.items():
            if operation["before"] is not None:
                backup = child(tx / "backup", name)
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child(root, name), backup)
                if fingerprint(backup) != operation["before"]:
                    raise ValueError("SDK changed while creating backup")
        meta = {"before_state": old, "operations": operations}
        atomic_json(tx / "transaction.json", meta)
        # Recheck after potentially slow extraction/copying and before changing root files.
        for name, operation in operations.items():
            if fingerprint(child(root, name)) != operation["before"]:
                raise ValueError("SDK changed while preparing update")
        atomic_json(pending, {"transaction": tx_id})
        try:
            for i, (name, operation) in enumerate(operations.items()):
                target = child(root, name)
                if operation["after"] is None:
                    target.unlink()
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(child(payload, name), target)
                if fault:
                    fault(i)
            new_state = {"schema_version": 1, "repository": REPOSITORY, "kind": asset["kind"],
                         "release": release, "archive_sha256": asset["sha256"],
                         "files": new_files, "last_transaction": tx_id}
            atomic_json(folder / "state.json", new_state)
            pending.unlink()
        except Exception:
            restore(root, tx, allow_partial=True)
            raise
        clean_payload(tx)
        return {"installed": True, "release": release, "managed_files": len(new_files),
                "preserved_user_files": True, "backup": str(tx / "backup")}


def rollback(root, recover=False):
    root = no_links(root)
    with locked(root) as folder:
        if recover:
            tx_id = read(folder / "pending.json")["transaction"]
        else:
            if (folder / "pending.json").exists():
                raise ValueError("Run --recover before rollback")
            tx_id = read(folder / "state.json")["last_transaction"]
        if not re.fullmatch("[a-f0-9]{32}", tx_id):
            raise ValueError("Invalid transaction ID")
        restore(root, no_links(folder / "transactions" / tx_id), allow_partial=recover)
        return {"restored": True, "preserved_user_files": True}


def allowed_url(url):
    u = urlsplit(url)
    if (u.scheme != "https" or u.username or u.password or u.port not in (None, 443)
            or u.hostname not in {"api.github.com", "github.com", "release-assets.githubusercontent.com",
                                  "objects.githubusercontent.com"}):
        raise ValueError("Unexpected download host")
    return url


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        allowed_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, destination, limit):
    request = urllib.request.Request(allowed_url(url), headers={"User-Agent": "KLETKA-ModKit-Updater/1"})
    opener = urllib.request.build_opener(Redirect)
    with opener.open(request, timeout=60) as response, Path(destination).open("xb") as output:
        count = 0
        while block := response.read(1024 * 1024):
            count += len(block)
            if count > limit:
                raise ValueError("Download exceeds expected size")
            output.write(block)


def remote_release(channel, tag, directory):
    if not re.fullmatch("[A-Za-z0-9._-]{1,120}", channel):
        raise ValueError("Invalid release channel")
    if tag:
        if not re.fullmatch("[A-Za-z0-9._-]{1,120}", tag):
            raise ValueError("Invalid release tag")
        url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{tag}"
    else:
        url = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=100"
    file = directory / "github.json"
    download(url, file, 8 * 1024**2)
    releases = [read(file)] if tag else read(file)
    prefix = "kletka-" + channel + "-"
    for release in releases:
        if release.get("draft") or not release.get("tag_name", "").startswith(prefix):
            continue
        selected = release["tag_name"]
        if not re.fullmatch("[A-Za-z0-9._-]{1,120}", selected):
            raise ValueError("Invalid remote tag")
        matching = [a for a in release["assets"] if a["name"] == "modkit-release.json"]
        if len(matching) != 1:
            raise ValueError("Missing release manifest")
        url = f"https://github.com/{REPOSITORY}/releases/download/{selected}/modkit-release.json"
        manifest = directory / "release.json"
        download(url, manifest, 2 * 1024**2)
        result = read(manifest)
        if (result.get("schema_version") != 2 or result.get("product") != "KLETKA"
                or result.get("repository") != REPOSITORY or result.get("tag") != selected
                or result.get("channel") != channel):
            raise ValueError("Release identity mismatch")
        return result
    raise ValueError("No published ModKit for this channel; choose an available release explicitly")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--kind", choices=("BlueprintBinary", "NativeSdk"), default="BlueprintBinary")
    parser.add_argument("--channel", default="public")
    parser.add_argument("--tag")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--rollback", action="store_true")
    mode.add_argument("--recover", action="store_true")
    args = parser.parse_args()
    editor_closed()
    if args.rollback or args.recover:
        result = rollback(Path(args.directory), args.recover)
    else:
        with tempfile.TemporaryDirectory(prefix="kletka-download-") as temporary:
            temp = Path(temporary)
            release = remote_release(args.channel, args.tag, temp)
            candidates = [a for a in release["assets"] if a["kind"] == args.kind]
            if len(candidates) != 1:
                raise ValueError("Selected distribution is not available")
            asset = candidates[0]
            if (not re.fullmatch("[A-Za-z0-9._-]+\\.zip", asset["file"])
                    or not isinstance(asset["size"], int) or not 0 < asset["size"] < MAX_ARCHIVE):
                raise ValueError("Invalid archive metadata")
            archive = temp / asset["file"]
            download(f"https://github.com/{REPOSITORY}/releases/download/{release['tag']}/{asset['file']}",
                     archive, asset["size"])
            result = install(Path(args.directory), archive, asset, release["tag"])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
