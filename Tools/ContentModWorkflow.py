# Copyright Callback LLP. All Rights Reserved.
"""Local ModKit cook jobs. Editor UI supplies only a feature and compatible game executable.

The canonical cooker and native installer retain ownership of packaging and installation.
A launch receipt proves process creation, never gameplay or multiplayer acceptance.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


@contextmanager
def cook_lock(project):
    # Windows releases the byte-range lock even if the cook process is terminated.
    import msvcrt
    path = Path(project) / "Saved/AtlasAuthoring/cook.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if lock.tell() == 0: lock.write(b"0"); lock.flush()
        lock.seek(0)
        try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc: raise ValueError("Another content cook is running for this ModKit. Inspect its build status before starting another.") from exc
        try: yield
        finally:
            lock.seek(0); msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def write(path, data):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def game_content_files(executable):
    """Locate packaged containers beside either the bootstrap or target executable."""
    roots = set()
    for parent in list(Path(executable).resolve(strict=True).parents)[:4]:
        for candidate in (parent / "Content/Paks", parent / "KLETKA/Content/Paks"):
            if candidate.is_dir(): roots.add(candidate.resolve())
    if len(roots) > 1:
        raise ValueError("Multiple game container directories match this executable.")
    return sorted(p for root in roots for p in root.iterdir()
                  if p.is_file() and p.suffix.lower() in (".pak", ".utoc", ".ucas"))


def game_content_fingerprint(executable):
    return {str(path): digest(path) for path in game_content_files(executable)}


def game_registry(executable, project=None, engine=None):
    executable = Path(executable).resolve(strict=True)
    if executable.suffix.lower() != ".exe":
        raise ValueError("Choose the installed game's Windows executable.")
    candidates = set()
    for parent in list(executable.parents)[:4]:
        for candidate in (parent / "AssetRegistry.bin", parent / "KLETKA/AssetRegistry.bin"):
            if candidate.is_file(): candidates.add(candidate.resolve())
    if len(candidates) == 1:
        return candidates.pop()
    if candidates:
        raise ValueError("Multiple game AssetRegistry.bin files match this executable.")
    if project is None or engine is None:
        raise ValueError("The game registry is packaged. Use Cook Mod in the ModKit editor to read it.")
    tool = Path(engine) / "Binaries/Win64/UnrealPak.exe"
    if not tool.is_file():
        raise ValueError("The editor's UnrealPak tool is unavailable: " + str(tool))
    packages = [p for p in game_content_files(executable) if p.suffix.lower() == ".pak"]
    if not packages:
        raise ValueError("No game packages found beside this executable. Choose KLETKA's packaged executable.")
    root = Path(project) / "Saved/AtlasAuthoring/GameRegistries" / uuid.uuid4().hex
    root.mkdir(parents=True)
    for index, package in enumerate(packages):
        destination = root / str(index)
        destination.mkdir()
        with (root / (str(index) + ".log")).open("w", encoding="utf-8") as log:
            result = subprocess.run([str(tool), str(package), "-Extract", str(destination),
                                     "-Filter=*AssetRegistry.bin"], stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise ValueError("Cannot read the packaged game registry. Diagnostics: " + str(root))
        for candidate in destination.rglob("AssetRegistry.bin"):
            if candidate.name == "AssetRegistry.bin" and candidate.resolve().is_relative_to(root.resolve()):
                candidates.add(candidate.resolve())
    hashes = {digest(p) for p in candidates}
    if len(hashes) != 1:
        raise ValueError("The game packages do not contain one unambiguous registry; a patch or encrypted package may require a matching ModKit release. Diagnostics: " + str(root))
    return sorted(candidates)[0]


def game_binary(executable):
    """Resolve KLETKA's packaged target when the user selected its bootstrap executable."""
    selected = Path(executable).resolve(strict=True)
    target_dir = selected.parent / "KLETKA/Binaries/Win64"
    if not target_dir.is_dir():
        return selected
    candidates = [target_dir / name for name in ("KLETKA.exe", "KLETKA-Win64-Shipping.exe")
                  if (target_dir / name).is_file()]
    if len(candidates) != 1:
        raise ValueError("Cannot identify one packaged game target. Select its executable in KLETKA/Binaries/Win64.")
    return candidates[0].resolve(strict=True)


def select_base(project, executable, engine=None):
    registry = game_registry(executable, project, engine)
    game_hash = digest(registry)
    binary_hash = digest(game_binary(executable))
    releases = Path(project) / "Releases"
    matches = []
    for receipt in releases.glob("*/cooking-base.json"):
        data = read(receipt)
        if data.get("SchemaVersion") != 1 or data.get("Platform") != "Win64": continue
        for entry in data.get("Files", []):
            source = (receipt.parent / entry["Path"]).resolve(strict=True)
            if not source.is_relative_to(receipt.parent.resolve()) or digest(source) != entry["Sha256"]:
                raise ValueError("Delivered cooking base was changed: " + str(source))
        runtime = next((e for e in data.get("Files", []) if e["Path"] == "Windows/AssetRegistry.bin"), None)
        # The same asset list can accompany incompatible native builds. A base
        # must identify the packaged target as well as its runtime registry.
        builds = data.get("GameExecutables", [])
        matching_build = any(isinstance(build, dict) and build.get("Sha256") == binary_hash for build in builds)
        if runtime and runtime["Sha256"] == game_hash and matching_build:
            if data["Release"] != receipt.parent.name:
                raise ValueError("Cooking-base directory and release identity disagree.")
            matches.append((receipt, data))
    if len(matches) != 1:
        raise ValueError("This installed game binary and registry do not match exactly one delivered cooking base. Install the matching game/ModKit release; do not copy registries between releases.")
    return matches[0][1]["Release"], registry, game_hash


def source_fingerprint(plugin):
    root = Path(plugin).parent
    paths = [p for p in root.rglob("*") if p.is_file()
             and not {"Intermediate", "Saved", "Binaries", "DerivedDataCache"}.intersection(p.relative_to(root).parts)]
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(paths)}


def require_modkit(project):
    """Recognize the delivered product; the staging deletion marker is never shipped."""
    root = Path(project)
    receipt = root / "Config/ModKitReleaseManifest.json"
    if not (root / "KLETKA_ModKit.uproject").is_file() or not receipt.is_file():
        raise ValueError("Cook & Test requires a delivered ModKit project and its release manifest. The game workspace uses its release pipeline.")
    release = read(receipt)
    if release.get("SchemaVersion") != 1 or release.get("DistributionKind") not in ("NativeSdk", "BlueprintBinary", "SourceReference"):
        raise ValueError("Unsupported ModKit release manifest. Install the matching ModKit release.")


def start(project, plugin, engine, executable):
    project, plugin, engine, executable = (Path(p).resolve(strict=True) for p in (project, plugin, engine, executable))
    require_modkit(project)
    if not plugin.is_relative_to(project / "Plugins/GameFeatures") or plugin.suffix != ".uplugin":
        raise ValueError("Choose a Game Feature belonging to this ModKit.")
    with cook_lock(project): pass
    release, registry, registry_hash = select_base(project, executable, engine)
    binary = game_binary(executable)
    python = engine / "Binaries/ThirdParty/Python3/Win64/python.exe"
    if not python.is_file(): raise ValueError("The selected editor's bundled Python runtime is unavailable.")
    output = project / "Saved/AtlasAuthoring/Builds" / (plugin.stem + "-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    job = dict(SchemaVersion=1, Status="starting", Project=str(project), Plugin=str(plugin),
               Engine=str(engine.parent), GameExecutable=str(executable), GameExecutableSha256=digest(executable),
               GameBinary=str(binary), GameBinarySha256=digest(binary),
               GameRegistry=str(registry), GameRegistrySha256=registry_hash, BaseRelease=release,
               GameContentFingerprint=game_content_fingerprint(executable),
               SourceFingerprint=source_fingerprint(plugin), CookRoot=str(output / "Cook"))
    path = output / "job.json"
    write(path, job)
    command = [str(python), "-X", "utf8", str(project / "Tools/ContentModWorkflow.py"), "--job", str(path)]
    try:
        with (output / "worker.log").open("w", encoding="utf-8") as log:
            subprocess.Popen(command, cwd=project, stdout=log, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        job.update(Status="failed", Error=str(exc)); write(path, job); raise
    return path


def worker(path):
    path = Path(path).resolve(strict=True)
    job = read(path)
    if job["Status"] != "starting": raise ValueError("This job has already started; retain it and create a new attempt.")
    project = Path(job["Project"])
    try:
        job.update(Status="cooking", WorkerPid=os.getpid()); write(path, job)
        descriptors = list(project.glob("*.uproject"))
        if len(descriptors) != 1: raise ValueError("Expected one ModKit project descriptor.")
        command = [sys.executable, "-X", "utf8", str(project / "Tools/CookContentMod.py"),
                   "--sdk-project", str(descriptors[0]), "--plugin", job["Plugin"],
                   "--engine-root", job["Engine"], "--base-release-root", str(project / "Releases"),
                   "--base-release", job["BaseRelease"], "--output", job["CookRoot"]]
        with cook_lock(project):
            code = subprocess.call(command)
        if code != 0: raise ValueError("Cook failed; inspect " + str(path.parent / "worker.log") + " and cook diagnostics.")
        report = read(Path(job["CookRoot"]) / "result.json")
        if not report["Success"]: raise ValueError("Cook report rejected the package: " + job["CookRoot"])
        if source_fingerprint(job["Plugin"]) != job["SourceFingerprint"]:
            raise ValueError("Source files changed during cook. Save the feature and start a new build.")
        job.update(Status="cooked", Package=str(Path(job["CookRoot"]) / "Package"))
    except Exception as exc:
        job.update(Status="failed", Error=str(exc))
    write(path, job)
    return job["Status"] == "cooked"


def release_summary(project, manifest, receipt=None, job=None):
    """Player-facing consequences and evidence for this artifact only."""
    package = manifest["package"]
    network = package.get("network", {})
    limits = package.get("compatibility", {})
    dependencies = package.get("dependencies", [])
    required = {content_id: "type unknown" for content_id in dependencies}
    if required:
        for path in (Path(project) / "Plugins/GameFeatures").glob("*/ams_manifest.json"):
            try:
                descriptor = read(path)
            except (ValueError, OSError):
                continue
            content_id = descriptor.get("contentId")
            if content_id in required:
                policy = descriptor.get("package", {})
                required[content_id] = "{} ({})".format(policy.get("entitlementType", "type unknown"),
                                                         policy.get("joinEntitlementPolicy", "ownership unknown"))
    receipt = receipt or {}
    target = receipt.get("Platform")
    artifacts = package.get("artifacts", {})
    platforms = sorted({"Win64", "Linux", "PS4", "PS5", "XB1", "XSX", "Switch"} | set(artifacts) | ({target} if target else set()))
    mode = ("dependency fingerprints checked at load" if "RequiredPackages" in receipt
            and "ExactCatalogSha256" not in receipt else "exact base required")
    listed = lambda values: ", ".join(values) or "none"
    return {
        "Platforms": listed(f"{p} ({'cooked' if p == target else 'declared only' if p in artifacts else 'no artifact'})"
                            for p in platforms),
        "Cook compatibility": f"{receipt.get('BaseRelease')} / {mode}" if receipt else "pending cook",
        "Game build limits": "{} to {}; branches: {}".format(limits.get("minGameBuild") or "unbounded",
            limits.get("maxGameBuild") or "unbounded", listed(limits.get("supportedBranches", [])) if limits.get("supportedBranches") else "any"),
        "Runtime format": package.get("runtimeFormat", "unspecified"),
        "Required content / DLC": listed(f"{k}: {v}" for k, v in sorted(required.items())),
        "Conflicts": listed(package.get("conflicts", [])),
        "Multiplayer": "{}; required on server: {}; required on client: {}; crossplay-safe declaration: {}".format(
            package.get("multiplayerScope", "unspecified"), network.get("bServerRequired", False),
            network.get("bClientRequired", False), network.get("bCrossplaySafe", False)),
        "Saves / progression": "Test reload with this content present and missing. The active game session sets achievement policy.",
        "Private gameplay test": (job or {}).get("AuthorPlaytest", {}).get("Verdict", "unverified"),
    }


def record_playtest(path, passed):
    job = check_ready(path)
    if job["Status"] != "launched-unverified" or not job.get("LastLaunch"):
        raise ValueError("Launch this cook's isolated test copy before recording a result.")
    launch_path = Path(job["LastLaunch"])
    if not launch_path.is_file() or not launch_path.resolve().is_relative_to(Path(path).resolve().parent):
        raise ValueError("Launch evidence unavailable. Launch the test copy again.")
    previous = read(launch_path)
    if previous.get("Status") != "launched-unverified":
        raise ValueError("Invalid launch evidence. Launch the test copy again.")
    job["AuthorPlaytest"] = {"Verdict": "author reported pass" if passed else "author reported failure",
                             "ReceiptSha256": digest(Path(job["Package"]) / "ams_cooked.json"),
                             "Launch": str(launch_path)}
    write(path, job)
    return job["AuthorPlaytest"]["Verdict"]


def current_job(project, plugin):
    root = Path(project).resolve() / "Saved/AtlasAuthoring/Builds"
    candidates = []
    for path in root.glob("*/job.json"):
        data = read(path)
        if Path(data.get("Plugin", "")).resolve() == Path(plugin).resolve(): candidates.append(path)
    if not candidates: raise ValueError("No build exists for this feature. Save it and choose Cook Mod first.")
    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def installed_fingerprint(root):
    root = Path(root).resolve(strict=True)
    result = {}
    for entry in root.rglob("*"):
        if entry.is_file():
            if not entry.resolve().is_relative_to(root):
                raise ValueError("Installed test copy contains a link outside its directory: " + str(entry))
            result[entry.relative_to(root).as_posix()] = digest(entry)
    if not result: raise ValueError("Installed test copy is empty; install it again.")
    return result


def check_ready(path):
    job = read(path)
    if job["Status"] not in ("cooked", "installed", "launched-unverified"):
        raise ValueError(job.get("Error", "Build is " + job["Status"] + "; open " + str(path)))
    if source_fingerprint(job["Plugin"]) != job["SourceFingerprint"]:
        raise ValueError("Saved mod sources changed since cooking; build them again.")
    if digest(job["GameExecutable"]) != job["GameExecutableSha256"] or digest(job["GameRegistry"]) != job["GameRegistrySha256"]:
        raise ValueError("The selected game changed since cooking; select a matching cooking base and build again.")
    binary = game_binary(job["GameExecutable"])
    if str(binary) != job.get("GameBinary") or digest(binary) != job.get("GameBinarySha256"):
        raise ValueError("The packaged game binary changed or was not verified by this cook job; build the mod again against its matching release.")
    if game_content_fingerprint(job["GameExecutable"]) != job.get("GameContentFingerprint"):
        raise ValueError("The installed game containers changed since cooking; build the mod again against its matching release.")
    package = Path(job["Package"])
    manifest = read(package / "ams_manifest.json")
    receipt = package / "ams_cooked.json"
    if digest(receipt) != manifest["package"]["artifacts"]["Win64"]["hashSha256"]:
        raise ValueError("Cooked receipt differs from the manifest.")
    for entry in read(receipt)["Files"]:
        source = (package / entry["Path"]).resolve(strict=True)
        if not source.is_relative_to(package.resolve()) or digest(source) != entry["Sha256"]:
            raise ValueError("Cooked package changed: " + str(source))
    if job["Status"] in ("installed", "launched-unverified"):
        if installed_fingerprint(job["InstalledModRoot"]) != job.get("InstalledFingerprint"):
            raise ValueError("Installed test copy changed. Cook and install a new test copy before launching.")
    return job


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    sys.exit(0 if worker(parser.parse_args().job) else 1)
