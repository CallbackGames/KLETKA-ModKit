# Copyright Callback LLP. All Rights Reserved.
"""Cook one content-only Game Feature against a named KLETKA base release.

Uses Unreal's DLC cooker and IoStore writer. A successful cook alone is not
runtime certification; retain the receipt and test the result in its base game.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record_dependencies(base, platform, direct, cooked_imports, author_native, receipt):
    catalog_path = base.parent / "ModCompatibility.json"
    if not catalog_path.is_file():
        return "This cooking base predates dependency catalogs; the original exact-base receipt was retained."
    catalog = read(catalog_path)
    if (catalog.get("SchemaVersion") != 1 or catalog["Platform"] != platform
            or catalog["BaseRegistrySha256"] != receipt["BaseRegistrySha256"] or not catalog["CookFormat"]):
        raise ValueError("Mod compatibility catalog does not match the selected platform and base registry.")
    required = {}
    native = {}
    missing = set()
    # Released development registries carry editor-only imported-class metadata
    # even for runtime assets. Actual cooked imports are checked separately.
    editor_metadata = "/Script/UnrealEd"
    if editor_metadata in cooked_imports:
        raise ValueError("A cooked mod package imports /Script/UnrealEd. Remove the editor-only reference from the mod.")
    pending = (set(direct) | {"/Script/CoreUObject", "/Script/Engine", "/Script/GameFeatures"}) - {editor_metadata}
    while pending:
        name = pending.pop()
        if name in required or name in missing:
            continue
        if name.startswith("/Script/"):
            observed = author_native.get(name)
            if not isinstance(observed, str) or not re.fullmatch("[0-9A-Fa-f]{40}", observed) or observed != catalog["NativePackages"].get(name):
                raise ValueError("The ModKit native layout does not match this cooking base: " + name
                                 + ". Use the SDK released with the base. The mod was not packaged for delivery.")
            native[name] = observed
        value = catalog["Packages"].get(name)
        if not value:
            missing.add(name)
            continue
        if not re.fullmatch("[0-9a-fA-F]{64}", value):
            raise ValueError("Invalid released package fingerprint for " + name)
        required[name] = value
        pending.update(edge for edge in catalog["Dependencies"].get(name, []) if edge != editor_metadata)
    receipt.update(SchemaVersion=3, CookFormat=catalog["CookFormat"], NativeImports=dict(sorted(native.items())))
    if missing:
        receipt["ExactCatalogSha256"] = sha(catalog_path)
        return "Exact-base only; no released fingerprint for " + ", ".join(sorted(missing))
    receipt["RequiredPackages"] = dict(sorted(required.items()))
    return "Recorded %d released game and native dependencies." % len(required)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk-project", type=Path, required=True)
    parser.add_argument("--plugin", type=Path, required=True)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--base-release-root", type=Path, required=True)
    parser.add_argument("--base-release", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--platform", choices=("Win64", "Linux"), default="Win64",
                        help="Target platform; requires that platform's matching base release and manifest artifact")
    args = parser.parse_args()
    project = args.sdk_project.resolve(strict=True)
    plugin = args.plugin.resolve(strict=True)
    engine = args.engine_root.resolve(strict=True)
    releases = args.base_release_root.resolve(strict=True)
    output = args.output.resolve()
    assert not output.exists(), "Choose a new output directory; previous evidence is retained"
    assert plugin.is_relative_to(project.parent / "Plugins/GameFeatures"), "Plugin must belong to this SDK"
    descriptor = read(plugin)
    assert not descriptor.get("Modules"), "This route delivers cooked content, not native game DLLs"
    assert descriptor.get("ExplicitlyLoaded") and descriptor.get("CanContainContent"), "Expected a content Game Feature"
    release = project.parent / "Config/ModKitReleaseManifest.json"
    sdk = read(release)
    # Verify the delivered SDK without treating user-authored extra plugins as SDK files.
    for entry in sdk["Files"]:
        path = project.parent / entry["Path"]
        assert path.resolve().is_relative_to(project.parent), "SDK inventory escapes its project"
        assert sha(path) == entry["Sha256"], "SDK delivery changed: " + entry["Path"]
    cook_platform = {"Win64": "Windows", "Linux": "Linux"}[args.platform]
    base = (releases / args.base_release / cook_platform / "AssetRegistry.bin").resolve(strict=True)
    assert base.is_relative_to(releases), "Base release name escapes its root"
    assert (base.parent / "Metadata/DevelopmentAssetRegistry.bin").is_file(), "IoStore requires the base development registry"
    source_manifest = plugin.parent / "ams_manifest.json"
    manifest = read(source_manifest)
    assert manifest["package"]["pluginName"] == plugin.stem, "Manifest and descriptor names differ"
    assert args.platform in manifest["package"]["artifacts"], "Author an explicit artifact for the selected target platform first"
    # Only narrowly validated tag configuration belongs to an external cooked mod.
    tag_files = sorted((plugin.parent / "Config/Tags").glob("*.ini"))
    config_files = [p for p in (plugin.parent / "Config").rglob("*") if p.is_file()]
    assert set(config_files) == set(tag_files), "Only direct Config/Tags/*.ini files are delivered; move gameplay configuration into owner assets/actions"
    output.mkdir(parents=True)
    report = {"SchemaVersion": 1, "Success": False, "PluginName": plugin.stem,
              "SdkReleaseManifestSha256": sha(release), "BaseRelease": args.base_release, "Platform": args.platform,
              "BaseRegistrySha256": sha(base), "SdkProject": str(project), "Output": str(output)}
    try:
        # The editor and runtime share the same native validator; do not maintain a
        # second parser in this cooker. Its output is required before starting UAT.
        declared_contract = manifest["package"].get("compatibilityHash")
        preflight = output / "tag-preflight.json"
        script = output / "tag-preflight.py"
        script.write_text("import json, unreal\nfrom pathlib import Path\n"
            + "result = unreal.AMSManifestValidationBlueprintLibrary.validate_manifest_file(" + repr(str(source_manifest)) + ")\n"
            + "valid = result is not None and result.valid\n"
            + "messages = [str(m.message) for m in result.messages] if result else ['Native manifest validation failed.']\n"
            + "scanned_contract = unreal.AMSManifestValidationBlueprintLibrary.compute_plugin_network_contract(" + repr(plugin.stem) + ") if valid else ''\n"
            + "registry = unreal.AssetRegistryHelpers.get_asset_registry()\nregistry.search_all_assets(True)\n"
            + "validator = unreal.get_editor_subsystem(unreal.EditorValidatorSubsystem)\n"
            + "direct = set()\n"
            + "options = unreal.AssetRegistryDependencyOptions(include_soft_package_references=True, include_hard_package_references=True, include_game_package_references=True, include_editor_only_package_references=False, include_searchable_names=False, include_soft_management_references=False, include_hard_management_references=False)\n"
            + "assets = registry.get_assets_by_path(" + repr('/'+plugin.stem) + ", recursive=True) if scanned_contract else []\n"
            + "if not assets:\n    messages.append('No mod assets could be scanned. Confirm that the feature contains a saved Game Feature Data asset.')\n    valid = False\n"
            + "for asset in assets:\n"
            + "    direct.add(str(asset.asset_class_path.package_name))\n"
            + "    direct.update(str(p) for p in registry.get_dependencies(asset.package_name, options) or [])\n"
            + "    if str(asset.asset_class_path.asset_name) == 'World': continue\n"
            + "    state, errors, warnings = validator.is_asset_valid(asset, unreal.DataValidationUsecase.MANUAL)\n"
            + "    messages.extend(str(asset.package_name) + ': ' + str(e) for e in errors)\n"
            + "    valid = valid and state != unreal.DataValidationResult.INVALID and not errors\n"
            + "report = {'Success': bool(valid), 'Messages': messages, 'AssetCount': len(assets), 'Dependencies': sorted(p for p in direct if not p.startswith(" + repr('/'+plugin.stem+'/') + "))}\n"
            + ("contract = " + repr(declared_contract) + "\n" if declared_contract else
               "contract = scanned_contract\n")
            + "report['NetworkContract'] = contract\n"
            + "Path(" + repr(str(preflight)) + ").write_text(json.dumps(report, indent=2), encoding='utf-8')\n"
            + "assert valid, 'Mod preflight failed: ' + str(report)\n", encoding="utf-8")
        # Unreal reparses the quoted -script value and interprets Windows sequences such as \t as escapes.
        command = [str(engine / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"), str(project),
                   "-run=pythonscript", "-script=" + script.as_posix(), "-unattended", "-nullrhi", "-RenderOffScreen",
                   "-UserDir=" + str(output / "EditorUser"), "-nosound", "-nop4"]
        with (output / "tag-preflight.log").open("w", encoding="utf-8") as log:
            code = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT)
        report["TagPreflight"] = read(preflight) if preflight.is_file() else {"Success": False}
        assert code == 0 and report["TagPreflight"]["Success"], "Manifest/asset preflight failed; inspect tag-preflight.log/json"
        tag_hashes = {str(path): sha(path) for path in tag_files}
        cmd = [str(engine / "Engine/Build/BatchFiles/RunUAT.bat"), "BuildCookRun", "-WaitForUATMutex",
               "-project=" + str(project), "-platform=" + args.platform,
               "-clientconfig=Development", "-cook", "-stage", "-pak", "-iostore",
               "-unrealexe=" + str(engine / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"),
               "-skipbuildeditor", "-unattended", "-nop4", "-utf8output", "-nodebuginfo",
               "-dlcname=" + str(plugin), "-basedonreleaseversion=" + args.base_release,
               "-basedonreleaseversionroot=" + str(releases),
               "-stagingdirectory=" + str(output / "Stage"), "-cookoutputdir=" + str(output / "Cook" / cook_platform),
               # Keep tag config only in its individually hashed loose delivery.
               # UAT otherwise also stages plugin Config inside the PAK.
               '-ini:PakFileRules:[AtlasModLooseTags]:bExcludeFromPaks=true,[AtlasModLooseTags]:bOverrideChunkManifest=true,[AtlasModLooseTags]:Files=.../Config/Tags/*.ini',
               '-AdditionalCookerOptions=-CookAgainstFixedBase -SkipZenStore -CookSkipRequests -CookDir="'
               + str(plugin.parent / "Content") + '" -NoLogTimes -nullrhi -RenderOffScreen -unattended -UserDir="'
               # UAT strips a trailing quote from this whole option value. Keep a
               # final standalone flag so the inner UserDir quote remains paired.
               + str(output / "CookerUser") + '" -NoSplash']
        report["Command"] = cmd
        with (output / "uat.log").open("w", encoding="utf-8") as log:
            code = subprocess.call(cmd, stdout=log, stderr=subprocess.STDOUT)
        report["ExitCode"] = code
        assert code == 0, "Unreal DLC cook/stage failed; inspect uat.log"
        critical = re.compile(r"Failed to find script package|Failed to load Outer|LogBlueprint.*Error:|LogCook.*Error:|No files found to cook", re.I)
        report["CriticalDiagnostics"] = [line.rstrip() for line in (output / "uat.log").read_text(
            encoding="utf-8", errors="replace").splitlines() if critical.search(line)]
        assert not report["CriticalDiagnostics"], "Cook returned success with unresolved assets; inspect critical diagnostics"
        content_prefix = project.stem + "/Plugins/GameFeatures/" + plugin.parent.name + "/Content/"
        cooked_assets = [path.relative_to(output / "Cook" / cook_platform).as_posix()
                         for path in (output / "Cook" / cook_platform).rglob("*")
                         if path.suffix in (".uasset", ".umap")]
        report["CookedAssets"] = sorted(cooked_assets)
        assert cooked_assets and all(path.startswith(content_prefix) for path in cooked_assets), (
            "DLC cooked assets outside its owning plugin; refuse to ship another mod or base content")
        dependencies = set(report["TagPreflight"]["Dependencies"])
        cooked_imports = set()
        author_native = {}
        if (base.parent / "ModCompatibility.json").is_file():
            imports_path = output / "cooked-imports.json"
            inspect = [str(engine / "Engine/Binaries/Win64/UnrealEditor-Cmd.exe"), str(project), "-run=AtlasModCookContract",
                       "-CookedContent=" + str(output / "Cook" / cook_platform / content_prefix),
                       "-PluginName=" + plugin.stem, "-Output=" + str(imports_path), "-UserDir=" + str(output / "EditorUser"),
                       "-ini:Engine:[ConsoleVariables]:s.AllowUnversionedContentInEditor=1",
                       "-nullrhi", "-RenderOffScreen", "-unattended", "-nosound", "-nop4"]
            with (output / "cooked-imports.log").open("w", encoding="utf-8") as log:
                subprocess.run(inspect, stdout=log, stderr=subprocess.STDOUT, check=True)
            imports = read(imports_path)
            if imports["CookedPackages"] != len(cooked_assets):
                raise ValueError("Cooked import inspection did not cover every exported package.")
            cooked_imports.update(imports["Imports"])
            dependencies.update(cooked_imports)
            author_native = imports["NativePackages"]
        compatibility = {"BaseRegistrySha256": sha(base)}
        report["CookCompatibility"] = record_dependencies(base, args.platform, dependencies, cooked_imports,
                                                            author_native, compatibility)
        stage = output / "Stage"
        paks = list(stage.rglob("*.pak"))
        assert len(paks) == 1, "Expected exactly one plugin container; inspect staging before export"
        pak = paks[0]
        assert pak.with_suffix(".utoc").is_file() and pak.with_suffix(".ucas").is_file(), "IoStore container pair missing"
        # Keep an ordinary installed Game Feature descriptor. The cooked payload
        # is rebased by the AMS owner to this plugin's actual installation root.
        package = output / "Package"
        package.mkdir()
        shutil.copy2(plugin, package / plugin.name)
        if (plugin.parent / "Media").is_dir():
            shutil.copytree(plugin.parent / "Media", package / "Media")
        target_paks = package / "Content/Paks" / cook_platform
        target_paks.mkdir(parents=True)
        payloads = [package / plugin.name]
        for source in sorted(pak.parent.iterdir()):
            if not re.fullmatch(re.escape(pak.stem) + r"(?:_s\d+)?\.(?:pak|utoc|ucas|sig)", source.name):
                continue
            target = target_paks / source.name
            shutil.copy2(source, target)
            payloads.append(target)
        assert all(sha(path) == tag_hashes[str(path)] for path in tag_files), "Tag files changed during cook; rerun preflight/cook"
        for source in tag_files:
            target = package / "Config/Tags" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            payloads.append(target)
        cooked = {"SchemaVersion": 2, "ContentId": manifest["contentId"], "PluginName": plugin.stem, "Platform": args.platform,
                  "BaseRelease": args.base_release, "BaseRegistrySha256": sha(base),
                  "SdkReleaseManifestSha256": sha(release),
                  "Files": [{"Path": path.relative_to(package).as_posix(), "Sha256": sha(path)}
                            for path in sorted(payloads)]}
        receipt = package / "ams_cooked.json"
        cooked.update(compatibility)
        receipt.write_text(json.dumps(cooked, indent=2) + "\n", encoding="utf-8")
        manifest["package"]["compatibilityHash"] = report["TagPreflight"]["NetworkContract"]
        artifact = manifest["package"]["artifacts"][args.platform]
        artifact["relativeInstallPath"] = plugin.name
        artifact["hashSha256"] = sha(receipt)
        # Each archive delivers only the selected platform; keep other targets in the author's source.
        manifest["package"]["artifacts"] = {args.platform: artifact}
        (package / "ams_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        report.update(Success=True, Package=str(package), CookedReceiptSha256=sha(receipt), Files=cooked["Files"])
    except Exception as exc:
        report["Failure"] = str(exc)
        raise
    finally:
        (output / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(output / "result.json", flush=True)


if __name__ == "__main__":
    main()
