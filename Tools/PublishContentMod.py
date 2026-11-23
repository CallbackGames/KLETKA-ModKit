# Copyright Callback LLP. All Rights Reserved.
"""Prepare store uploads from a verified cooked Game Feature. Never sends credentials or uploads."""
import argparse
import hashlib
import html
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import uuid
import zipfile

_metadata_spec = importlib.util.spec_from_file_location('steam_workshop_metadata', Path(__file__).with_name('SteamWorkshopMetadata.py'))
_metadata = importlib.util.module_from_spec(_metadata_spec); _metadata_spec.loader.exec_module(_metadata)
bind_manifest = _metadata.bind_manifest


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def contained(root, relative):
    if not isinstance(relative, str) or "\\" in relative or ":" in relative:
        raise ValueError("Expected a package-relative path: " + str(relative))
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or ".." in parts.parts or str(parts) != relative:
        raise ValueError("Path escapes or ambiguously names a package file: " + relative)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Package file escapes its root: " + relative)
    return path


def numeric_id(value, label, optional=False):
    value = str(value).strip()
    if optional and not value:
        return ""
    if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > 2**64-1:
        raise ValueError(label + " must be a positive numeric store ID.")
    return value


def validate_package(root):
    root = Path(root).resolve(strict=True)
    if any(p.name.startswith(".ams-") and "incomplete" in p.name for p in root.rglob("*")):
        raise ValueError("The package contains an incomplete-operation marker.")
    manifest = read(root / "ams_manifest.json")
    receipt = read(root / "ams_cooked.json")
    package = manifest["package"]
    content_id, name = manifest["contentId"], package["pluginName"]
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+", content_id) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError("Invalid canonical ContentId or plugin name.")
    if package.get("contentClass") != "CreatorContent" or package["runtimeFormat"] != "GameFeaturePlugin" or receipt.get("SchemaVersion") not in (2, 3) or receipt.get("Platform") != "Win64":
        raise ValueError("Publishing supports verified Windows content-only Game Features.")
    if receipt["SchemaVersion"] == 3:
        if not isinstance(receipt.get("CookFormat"), str) or not receipt["CookFormat"]:
            raise ValueError("The cooked mod has no serialization format.")
        required = receipt.get("RequiredPackages")
        if "ExactCatalogSha256" in receipt:
            exact = receipt["ExactCatalogSha256"]
            if "RequiredPackages" in receipt or not isinstance(exact, str) or not re.fullmatch("[a-fA-F0-9]{64}", exact):
                raise ValueError("The cooked mod has an invalid exact-base dependency record.")
        elif (not isinstance(required, dict) or not {"/Script/CoreUObject", "/Script/Engine", "/Script/GameFeatures"} <= required.keys()
                or any(not name.startswith("/") or not isinstance(value, str) or not re.fullmatch("[a-fA-F0-9]{64}", value)
                       for name, value in required.items())):
            raise ValueError("The cooked mod has an incomplete dependency record.")
        native = receipt.get("NativeImports")
        scripts = {"/Script/CoreUObject", "/Script/Engine", "/Script/GameFeatures"}
        if isinstance(required, dict):
            scripts.update(name for name in required if name.startswith("/Script/"))
        if (not isinstance(native, dict) or not scripts <= native.keys()
                or any(not name.startswith("/Script/") or not isinstance(value, str)
                       or not re.fullmatch("[a-fA-F0-9]{40}", value) for name, value in native.items())):
            raise ValueError("The cooked mod has incomplete authoring SDK fingerprints.")
    if receipt.get("ContentId") != content_id or receipt.get("PluginName") != name:
        raise ValueError("The cooked receipt belongs to another mod.")
    if not receipt.get("BaseRelease") or not re.fullmatch(r"[a-fA-F0-9]{64}", receipt.get("BaseRegistrySha256", "")):
        raise ValueError("The cooked package has no identifiable receiving game release.")
    if set(package["artifacts"]) != {"Win64"}:
        raise ValueError("A Windows package must not advertise unbuilt platform artifacts.")
    artifact = package["artifacts"]["Win64"]
    if artifact["relativeInstallPath"] != name + ".uplugin" or artifact["hashSha256"] != digest(root / "ams_cooked.json"):
        raise ValueError("The manifest does not match its cooked artifact.")
    files = {"ams_manifest.json", "ams_cooked.json"}
    payloads = set()
    for entry in receipt["Files"]:
        relative = entry["Path"]
        path = contained(root, relative)
        if relative in files or relative.casefold() in {v.casefold() for v in payloads}:
            raise ValueError("Duplicate or reserved cooked receipt path: " + relative)
        allowed = relative == name + ".uplugin" or (
            relative.startswith("Content/Paks/Windows/") and path.suffix.lower() in (".pak", ".utoc", ".ucas", ".sig")) or (
            relative.startswith("Config/Tags/") and len(PurePosixPath(relative).parts) == 3 and path.suffix.lower() == ".ini")
        if not allowed or digest(path) != entry["Sha256"]:
            raise ValueError("Unexpected or changed cooked payload: " + relative)
        payloads.add(relative)
    if name + ".uplugin" not in payloads or not all(any(p.endswith(ext) for p in payloads) for ext in (".pak", ".utoc", ".ucas")):
        raise ValueError("The cooked plugin descriptor or container set is incomplete.")
    descriptor = read(root / (name + ".uplugin"))
    if descriptor.get("Modules") or not descriptor.get("ExplicitlyLoaded") or not descriptor.get("CanContainContent"):
        raise ValueError("This publication route does not ship native game DLLs.")
    files.update(payloads)
    profile = manifest["profile"]
    card = profile["card"]
    if not all(isinstance(v, str) and v.strip() for v in (profile.get("displayName"), card.get("shortDescription"), manifest["release"].get("version"))):
        raise ValueError("Fill the mod title, short description and version in the Wizard, then cook again.")
    media = [card.get("iconPath", ""), card.get("bannerPath", ""), *card.get("previewImagePaths", [])]
    for relative in filter(None, media):
        path = contained(root, relative)
        if not relative.startswith("Media/") or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
            raise ValueError("Upload media must be local images under Media/: " + relative)
        files.add(relative)
    # Unknown editor files, credentials, source assets and symlinks are never silently shipped.
    for path in root.rglob("*"):
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise ValueError("Package links are unsupported: " + str(path))
        if path.is_file() and path.relative_to(root).as_posix() not in files:
            # Cook may retain alternative local card images; these are not uploaded.
            relative = path.relative_to(root).as_posix()
            if relative == 'Media/README.md':
                continue  # The Wizard's media-authoring note is not game content.
            if not relative.startswith("Media/") or path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                raise ValueError("Unexpected file in the cooked package: " + relative)
    return manifest, receipt, {relative: digest(contained(root, relative)) for relative in sorted(files)}


STEAM_HELPER = r'''# Run locally after inspecting PUBLISH.html. Never put a password in this script.
param([string]$SteamCmdPath = 'steamcmd', [string]$Login = '', [switch]$ConfirmUpload, [switch]$UseSteamCmdFallback)
$ErrorActionPreference = 'Stop'
$Bundle = $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $Bundle '.ams-publish-incomplete')) { throw 'Publish preparation is incomplete; prepare a new bundle.' }
$Metadata = Get-Content -LiteralPath (Join-Path $Bundle 'publish.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Metadata.Provider -ne 'SteamWorkshop') { throw 'This bundle is not a Steam upload.' }
$PackageRoot = Join-Path $Bundle 'Package'
foreach ($Entry in Get-ChildItem -LiteralPath $PackageRoot -Recurse -Force) {
    if ($Entry.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Upload package contains a link.' }
    if (-not $Entry.PSIsContainer) {
        $Relative = $Entry.FullName.Substring($PackageRoot.Length + 1).Replace('\', '/')
        if ($Relative -cnotin $Metadata.Files.PSObject.Properties.Name) { throw "Unexpected upload file: $Relative. Prepare a new bundle." }
    }
}
foreach ($File in $Metadata.Files.PSObject.Properties) {
    $Root = [IO.Path]::GetFullPath((Join-Path $Bundle 'Package')) + [IO.Path]::DirectorySeparatorChar
    $Path = [IO.Path]::GetFullPath((Join-Path $Root $File.Name))
    if (-not $Path.StartsWith($Root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid upload file path.' }
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $File.Value) { throw "Upload file changed: $($File.Name). Prepare a new bundle." }
}
$ItemId = [string]$Metadata.ExistingItemId
$VdfPath = Join-Path $Bundle 'steam_workshop_item.vdf'
if (Test-Path -LiteralPath $VdfPath) {
    $PreviousVdf = Get-Content -LiteralPath $VdfPath -Raw -Encoding UTF8
    if ($PreviousVdf -match '"publishedfileid"\s+"([1-9][0-9]*)"') {
        if ($ItemId -and $ItemId -ne $Matches[1]) { throw 'Recorded Workshop item differs from the chosen update target.' }
        $ItemId = $Matches[1]
    }
}
if (-not $ItemId) { $ItemId = '0' }
if (-not $ConfirmUpload) { throw "Review PUBLISH.html, then rerun with -ConfirmUpload. Target item: $ItemId; visibility: $($Metadata.Visibility)." }
$Python = [string]$Metadata.PythonRuntime
$MetadataTool = Join-Path $Bundle 'SteamWorkshopMetadata.py'
if (-not $UseSteamCmdFallback) {
    & $Python $MetadataTool --bundle $Bundle --upload --confirm-update
    if ($LASTEXITCODE -ne 0) { throw 'Workshop upload is incomplete. Keep this bundle and its recorded item ID; inspect the exact error above before retrying.' }
    return
}
if ($Metadata.Visibility -eq 'Preserve') { throw 'Use the native uploader to preserve visibility when updating a release.' }
& $Python $MetadataTool --bundle $Bundle --item-id $ItemId --check --require-private
if ($LASTEXITCODE -ne 0) { throw 'Steam client/account/metadata preflight failed. No content upload was started.' }
function EscapeVdf([string]$Value) { return $Value.Replace('\', '\\').Replace('"', '\"').Replace("`r", '').Replace("`n", '\n') }
$Fields = [ordered]@{appid=[string]$Metadata.GameId; publishedfileid=$ItemId; contentfolder=(Join-Path $Bundle 'Package'); visibility='2'; title=$Metadata.Title; description=$Metadata.Description; changenote=$Metadata.Changelog}
if ($ItemId -ne '0') { $Fields.Remove('visibility') }
if ($Metadata.Preview) { $Fields.previewfile=Join-Path (Join-Path $Bundle 'Package') $Metadata.Preview }
$Lines = @('"workshopitem"', '{')
foreach ($Key in $Fields.Keys) { $Lines += ('  "' + $Key + '" "' + (EscapeVdf $Fields[$Key]) + '"') }
$Lines += '}'
[IO.File]::WriteAllText($VdfPath, ($Lines -join "`n"), [Text.UTF8Encoding]::new($false))
if ([string]::IsNullOrWhiteSpace($Login)) { $Login=Read-Host 'Steam login (SteamCMD asks for password/Steam Guard if needed)' }
& $SteamCmdPath +login $Login +workshop_build_item $VdfPath +quit
if ($LASTEXITCODE -ne 0) { throw "SteamCMD failed: exit $LASTEXITCODE. Keep this bundle and inspect SteamCMD logs before retrying." }
$Updated = Get-Content -LiteralPath $VdfPath -Raw -Encoding UTF8
if ($Updated -notmatch '"publishedfileid"\s+"([1-9][0-9]*)"') { throw 'SteamCMD returned without an item ID. Publication is unconfirmed; inspect its logs.' }
$PublishedId=$Matches[1]
& $Python $MetadataTool --bundle $Bundle --item-id $PublishedId --bind-package
if ($LASTEXITCODE -ne 0) { throw 'Workshop returned an item ID, but the package reference could not be bound. Keep this VDF; do not create another item.' }
$Binding = Get-Content -LiteralPath (Join-Path $Bundle 'binding-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Binding.Changed) {
    # A new item gets its immutable ID only after the first upload. Submit the bound
    # manifest to that same private item so joins/saves can find its download source.
    & $SteamCmdPath +login $Login +workshop_build_item $VdfPath +quit
    if ($LASTEXITCODE -ne 0) { throw 'The item ID was retained, but the bound package upload failed. Retry this same bundle.' }
}
& $Python $MetadataTool --bundle $Bundle --item-id $PublishedId --confirm-update
if ($LASTEXITCODE -ne 0) { throw "Content upload completed for $PublishedId, but Atlas metadata is unconfirmed. Keep the item Private and this VDF; use the same Steam account in Steam and SteamCMD, then retry this bundle." }
@{Status='upload-metadata-verified'; ContentId=$Metadata.ContentId; PublishedFileId=$PublishedId; Url="https://steamcommunity.com/sharedfiles/filedetails/?id=$PublishedId"; GameplayAcceptance='requires-fresh-download-and-playtest'} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Bundle 'upload-result.json') -Encoding UTF8
Write-Host "Uploaded item $PublishedId and verified Atlas metadata. Open its page, inspect Private visibility and test a fresh download. Keep this VDF for retries; enter this ID when preparing future updates."
'''


def prepare(job_path, provider, existing_item_id="", confirm_existing=False, *, create_modio=False, update_release=False):
    if provider not in ("SteamWorkshop", "ModIo", "Manual"):
        raise ValueError("Choose Steam Workshop, mod.io or Manual.")
    spec = importlib.util.spec_from_file_location("content_mod_workflow", Path(__file__).with_name("ContentModWorkflow.py"))
    workflow = importlib.util.module_from_spec(spec); spec.loader.exec_module(workflow)
    job_path = Path(job_path).resolve(strict=True)
    job = workflow.check_ready(job_path)
    source = Path(job["Package"])
    manifest, receipt, files = validate_package(source)
    author_manifest = read(Path(job["Plugin"]).parent / "ams_manifest.json")
    summary = workflow.release_summary(job["Project"], author_manifest, receipt, job)
    author_manifest["package"]["artifacts"] = {"Win64": author_manifest["package"]["artifacts"]["Win64"]}
    author_manifest["package"]["artifacts"]["Win64"]["hashSha256"] = digest(source / "ams_cooked.json")
    author_manifest["package"]["artifacts"]["Win64"]["relativeInstallPath"] = Path(job["Plugin"]).name
    # CookContentMod derives the network contract from the feature during tag preflight.
    if author_manifest["package"].get("compatibilityHash") != manifest["package"].get("compatibilityHash"):
        cook_report = read(source.parent / "result.json")
        network_contract = cook_report.get("TagPreflight", {}).get("NetworkContract")
        if cook_report.get("Success") and network_contract:
            author_manifest["package"]["compatibilityHash"] = network_contract
    if author_manifest != manifest:
        raise ValueError("Cooked metadata differs from the saved source used for this build. Cook the mod again.")
    existing = numeric_id(existing_item_id, "Existing item ID", optional=True)
    if update_release and (not existing or not confirm_existing or provider == "Manual"):
        raise ValueError("Updating a release requires a confirmed existing store item.")
    artifact = manifest["package"]["artifacts"]["Win64"]
    references = manifest["package"].get("providerReferences", []) + artifact.get("providerReferences", []) + [artifact]
    # Match the spellings accepted by the runtime providers, including older manifests.
    aliases = {"ModIo": {"mod.io", "modio", "mod_io", "mod-io"},
               "SteamWorkshop": {"steamworkshop", "steam", "workshop"}}.get(provider, set())
    bound = {numeric_id(ref["providerId"], "Manifest store item ID") for ref in references
             if str(ref.get("provider", "")).strip().casefold() in aliases and ref.get("providerId")}
    if len(bound) > 1 or (existing and bound and existing not in bound):
        raise ValueError("The chosen store item differs from this mod's existing provider reference.")
    if bound and not existing:
        raise ValueError("This mod already declares item " + next(iter(bound)) + ". Enter that ID and confirm an update instead of creating a duplicate.")
    if provider == 'ModIo' and not existing and not create_modio:
        raise ValueError('Create a Private KLETKA mod page at https://mod.io/g/kletka first. Enter its numeric mod ID and confirm the target here, then prepare the ZIP. This binds the download source for joining sessions and restoring saves.')
    if existing and not confirm_existing:
        raise ValueError("Confirm that this existing store item belongs to the selected mod before preparing an update.")
    settings = read(Path(job["Project"]) / "Config/ModKitPublishing.json")
    if settings.get("SchemaVersion") != 1:
        raise ValueError("Unsupported ModKit publishing configuration.")
    game_id = numeric_id(settings[provider]["GameId"], "Store game ID") if provider != "Manual" else ""
    card = manifest["profile"]["card"]
    preview = card.get("iconPath", "")
    if provider == "ModIo":
        preview = card.get("bannerPath", "") or preview
    if provider != "Manual" and not preview:
        raise ValueError("Add a store preview image in the Wizard and cook again before publication.")
    steam = {}
    if provider == "SteamWorkshop":
        libraries = {p.resolve() for parent in list(Path(job['GameExecutable']).resolve().parents)[:4]
                     for p in parent.glob('Engine/Binaries/ThirdParty/Steamworks/Steamv164/Win64/steam_api64.dll')}
        python = Path(job['Engine'])/'Engine/Binaries/ThirdParty/Python3/Win64/python.exe'
        if len(libraries) != 1 or not python.is_file():
            raise ValueError('The selected game must include Steamworks 1.64 and the selected Unreal installation must include Python. They finalize Workshop release metadata; prepare this bundle again after installing them.')
        library = libraries.pop()
        steam = dict(SteamApiLibrary=str(library), SteamApiSha256=digest(library), PythonRuntime=str(python))
    # Never share a project-wide default item ID across unrelated mods.
    records = Path(job["Project"]) / "Saved/AtlasAuthoring/Publishing"
    for path in records.glob("*/publish.json"):
        prior = read(path)
        prior_ids = {prior.get("ExistingItemId")}
        upload_result = path.with_name("upload-result.json")
        if upload_result.is_file():
            prior_ids.add(read(upload_result).get("PublishedFileId"))
        if existing and prior.get("Provider") == provider and existing in prior_ids and prior.get("ContentId") != manifest["contentId"]:
            raise ValueError("This store item ID is already bound to another mod in this ModKit.")
    bundle = records / (manifest["package"]["pluginName"] + "-" + uuid.uuid4().hex)
    bundle.mkdir(parents=True)
    marker = bundle / ".ams-publish-incomplete"
    marker.write_text("Preparation is incomplete; do not upload this directory.\n", encoding="utf-8")
    target = bundle / "Package"
    for relative, expected in files.items():
        destination = target / relative; destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(contained(source, relative), destination)
        if digest(destination) != expected:
            raise ValueError("Package changed while preparing publication: " + relative)
    if existing and provider in ('ModIo','SteamWorkshop'):
        write(target/'ams_manifest.json',bind_manifest(manifest,provider,existing))
        files['ams_manifest.json']=digest(target/'ams_manifest.json')
    metadata = dict(SchemaVersion=1, Status="prepared-not-uploaded", Provider=provider, GameId=game_id,
                    ExistingItemId=existing, ContentId=manifest["contentId"], Version=manifest["release"]["version"],
                    Title=manifest["profile"]["displayName"], Summary=card["shortDescription"],
                    Description=card.get("description", "") or card["shortDescription"],
                    Changelog=manifest["release"].get("changelog", ""), Preview=preview,
                    Visibility="Preserve" if update_release else "Private", Platforms=["windows"], BaseRelease=receipt["BaseRelease"],
                    BaseRegistrySha256=receipt["BaseRegistrySha256"], Files=files,
                    SourceJob=str(job_path), GameplayAcceptance="not-certified-by-preparation",
                    ReleaseSummary=summary, **steam)
    if provider in ("ModIo", "Manual"):
        archive = bundle / (manifest["package"]["pluginName"] + "-Windows.zip")
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, allowZip64=True) as output:
            for relative in files:
                output.write(target / relative, relative)
        with zipfile.ZipFile(archive) as output:
            if output.testzip() is not None or set(output.namelist()) != set(files):
                raise ValueError("Prepared archive verification failed.")
        metadata.update(Archive=archive.name, ArchiveSha256=digest(archive))
    if provider == "SteamWorkshop":
        (bundle / "upload_steam_workshop.ps1").write_text(STEAM_HELPER, encoding="utf-8")
        shutil.copy2(Path(__file__).with_name('SteamWorkshopMetadata.py'), bundle/'SteamWorkshopMetadata.py')
    if provider == "ModIo":
        metadata["MetadataBlob"] = json.dumps({"content_id": metadata["ContentId"], "version": metadata["Version"]}, separators=(",", ":"))
    write(bundle / "publish.json", metadata)
    esc = html.escape
    if provider == "SteamWorkshop":
        instructions = '''<ol><li>Start Steam and sign in with the account that owns this mod's Workshop item. The installed game's Steamworks library uploads the content and Atlas metadata; no separate SDK, SteamCMD installation or developer key is required.</li>
<li>Run <code>upload_steam_workshop.ps1 -ConfirmUpload</code> from this folder. It uses the already signed-in Steam client. No password belongs in the ModKit. New item IDs are recorded before uploading; retry this same folder after an interruption.</li>
<li>The helper checks the Steam client before uploading, then writes and reads back <code>content_id</code> and <code>ams_version</code>. Keep the item Private if this fails; retry this same folder. SteamCMD completion alone is not a successful Atlas publication.</li>
<li>Open the item URL recorded in <code>upload-result.json</code>. Confirm the upload, accept any Workshop agreement yourself and inspect visibility. The helper creates new items privately. Update Existing Release retains the visibility of an existing page.</li>
<li>Retain <code>workshop-target.json</code> and <code>upload-result.json</code>; use the recorded item ID when preparing future versions.</li>
<li>Advanced fallback: <code>-UseSteamCmdFallback -SteamCmdPath "path/to/steamcmd.exe"</code> uses SteamCMD. A new item needs two transfers to bind its returned ID; retain its VDF. The normal route above binds the ID before its first content upload.</li></ol>'''
        store = "https://steamcommunity.com/app/" + game_id + "/workshop/"
    elif provider == "ModIo":
        store = settings["ModIo"]["CreatorUrl"]
        if not store.startswith("https://mod.io/"):
            raise ValueError("The ModKit mod.io creator link must use https://mod.io/.")
        instructions = f'''<ol><li>Open the mod.io link below and sign in with the mod owner's account. {'Open existing item ' + esc(existing) + '; do not create another item.' if existing else 'Create a mod page for KLETKA, using the title, summary and preview from publish.json.'}</li>
<li>{("Keep the current page visibility." if update_release else "Choose Private visibility.")} In the file manager, upload <code>{esc(metadata['Archive'])}</code> as one file, version <code>{esc(metadata['Version'])}</code>, platform <strong>Windows only</strong>. The archive already contains the manifest at its root; do not zip this whole handoff folder.</li>
<li>In the mod page's <strong>Metadata</strong> tab, paste <code>{esc(metadata['MetadataBlob'])}</code> into <strong>Metadata blob</strong> and save it. This publishes the stable ContentId used by in-game catalog discovery; the numeric mod.io ID and the title cannot replace it.</li>
<li>Wait for upload and processing to finish. Check the file version, Windows availability and mod visibility on the website. Record the numeric mod ID for future updates. Authentication, processing and moderation can fail independently of this local preparation.</li>
<li>A Steam-only page is not a mod.io mirror. Keep the same canonical ContentId when publishing the same mod on both services; each platform needs its own compatible cooked artifact.</li></ol>'''
    else:
        store = ""
        instructions = f"<p>Deliver <code>{esc(metadata['Archive'])}</code> to your tester. It contains only the verified game package. Manual handoff does not make the mod available in online store catalogs.</p>"
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Publish {esc(metadata['Title'])}</title>
<style>body{{background:#17191d;color:#eee;font:17px/1.6 system-ui;max-width:960px;margin:48px auto;padding:0 24px}}a{{color:#8ac6ff}}code{{background:#292e36;padding:2px 5px;overflow-wrap:anywhere}}li{{margin:12px 0}}.state{{border-left:4px solid #e5b34f;padding:12px 20px;background:#24272d}}</style>
<h1>{esc(metadata['Title'])} — {esc(provider)}</h1><p class="state"><strong>Prepared locally. Not uploaded.</strong> The build's files and archive were checked. Playing the mod, downloading it from the store and joining a session are separate checks.</p>
<p>Content ID: <code>{esc(metadata['ContentId'])}</code><br>Version: <code>{esc(metadata['Version'])}</code><br>Game base: <code>{esc(metadata['BaseRelease'])}</code><br>Update target: <code>{esc(existing) if existing else 'New item'}</code></p>
<h2>Release summary</h2><dl>{''.join('<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>' for k,v in metadata['ReleaseSummary'].items())}</dl>
<h2>Upload</h2>{instructions}{('<p><a href="' + esc(store, quote=True) + '">Open store</a></p>') if store else ''}
<h2>Before making it public</h2><ol><li>Install and enable it in the matching game; play its actual content.</li><li>Download it to a clean test installation from the intended store. A local copy does not prove the online upload works.</li><li>Test hosting and joining with the required mods, and save/reload with this mod enabled and missing.</li><li>Check update version and dependency compatibility. Keep previous mod.io files if older saves still need them; Workshop usually supplies the current item, so an old save may not have a downloadable exact version.</li></ol>
<h2>Publishing the same mod to both stores</h2><p>Prepare both publications from the same successful cook job for this platform. Keep the same ContentId, version and cooked payload; each store assigns its own numeric item ID. Workshop's uploader publishes the searchable <code>atlas_content_id</code> key automatically. For mod.io, save the Metadata blob above. Record both item references in future source manifests.</p>
<p>After the player approves downloading, the game can try another permitted store by stable ID if the first source is unavailable. It verifies the required version and target-platform checksum before activation. Missing files, private access restrictions, ambiguous IDs and incompatible versions remain explicit failures. A console cannot use a Windows artifact or Steam Workshop. Do not change a release's payload while reusing its version label.</p>
<p>Only Windows was built. Do not mark this file as a console build. After the checks, change store visibility deliberately. Keep <code>publish.json</code>, the archive and the upload result for this version.</p></html>'''
    (bundle / "PUBLISH.html").write_text(page, encoding="utf-8")
    # Recheck before marking complete. No new helper files enter the game payload.
    _, _, copied_files = validate_package(target)
    if copied_files != files:
        raise ValueError("Prepared payload no longer matches its verified input.")
    marker.unlink()
    return dict(Bundle=str(bundle), Guide=str(bundle / "PUBLISH.html"), **metadata)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True, type=Path)
    parser.add_argument("--provider", required=True, choices=("SteamWorkshop", "ModIo", "Manual"))
    parser.add_argument("--existing-item-id", default="")
    parser.add_argument("--confirm-existing", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.job, args.provider, args.existing_item_id, args.confirm_existing), indent=2))
