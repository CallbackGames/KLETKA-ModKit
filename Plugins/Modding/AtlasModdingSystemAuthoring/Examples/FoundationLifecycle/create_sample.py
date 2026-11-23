# Copyright Callback LLP. All Rights Reserved.
"""Run explicitly in an Unreal Editor Python console after building authoring.

Creates a new, local/offline Game Feature with Settings and Save contributions.
Never overwrites an existing sample. Does not activate, cook, install or publish it.
"""

import json
from pathlib import Path
import re
import uuid


def create_sample(plugin_name="AtlasFoundationLifecycleSample", target_save_id="Global"):
    import unreal

    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", plugin_name):
        raise ValueError("Use an ASCII plugin name starting with a letter.")
    if not target_save_id or target_save_id.lower() == "none":
        raise ValueError("Choose the host profile's permanent Save Id.")
    project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
    root = project / "Plugins" / "GameFeatures" / plugin_name
    if root.exists():
        raise FileExistsError(f"Choose a new plugin name; existing output is retained: {root}")

    # Resolve all reflected contracts before creating any mod files.
    class_paths = {
        "setting": "/Script/AtlasSettingsFrameworkRuntime.AtlasBoolSettingDefinition",
        "contributor": "/Script/AtlasSettingsFrameworkRuntime.AtlasContributor",
        "settings_action": "/Script/AtlasSettingsFrameworkRuntime.GameFeatureAction_AddAtlasDefinitions",
        "save_action": "/Script/AtlasSaveGameFrameworkRuntime.AtlasGameFeatureAction_AddModSaveDescriptor",
    }
    classes = {key: unreal.load_class(None, path) for key, path in class_paths.items()}
    missing = [class_paths[key] for key, value in classes.items() if value is None]
    if missing:
        raise RuntimeError(f"Enable/build the owner plugins first: {missing}")

    content_id = "sample." + plugin_name.lower()
    request = unreal.AMSNewModRequest()
    identity = unreal.AMSModAuthoringIdentity()
    identity.set_editor_property("template", unreal.AMSModTemplate.GAMEPLAY_GAME_FEATURE)
    identity.set_editor_property("content_id", content_id)
    identity.set_editor_property("plugin_name", plugin_name)
    identity.set_editor_property("required_plugin_names", ["AtlasSettingsFramework", "AtlasSaveGameFramework"])
    request.set_editor_property("identity", identity)
    presentation = unreal.AMSModAuthoringPresentation()
    presentation.set_editor_property("display_name", "Foundation Lifecycle Sample")
    presentation.set_editor_property("author", "Atlas sample")
    request.set_editor_property("presentation", presentation)
    policy = unreal.AMSModAuthoringPolicy()
    policy.set_editor_property("enabled_by_default", False)
    policy.set_editor_property("use_template_default_network_policy", False)
    policy.set_editor_property("multiplayer_scope", unreal.AtlasMultiplayerScope.OFFLINE_ONLY)
    request.set_editor_property("policy", policy)

    report_path = project / "Saved" / "AMS" / "FoundationSamples" / (uuid.uuid4().hex + ".json")
    report = {"SchemaVersion": 1, "Status": "Creating", "ModRoot": str(root), "Assets": []}

    def write_report():
        report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=2), encoding="utf-8")
        temporary.replace(report_path)

    write_report()
    try:
        # UE Python unwraps bool + one out-parameter to result or None (PyGenUtil.cpp).
        result = unreal.AMSModAuthoringBlueprintLibrary.create_mod_from_template(request)
        if result is None or not result.get_editor_property("success"):
            raise RuntimeError("Skeleton creation failed; inspect Saved/AMS/CreationAttempts and the editor log.")
        report["SkeletonReport"] = result.get_editor_property("creation_report_path")
        # Survives copying the folder to another workspace; Saved receipts are diagnostic only.
        marker = root / ".ams-sample-incomplete"
        marker.write_text(str(report_path), encoding="utf-8")
        feature = unreal.load_asset(f"/{plugin_name}/{plugin_name}")
        if feature is None:
            raise RuntimeError("The generated GameFeatureData could not be loaded.")
        if feature.get_editor_property("actions"):
            raise RuntimeError("The generated feature already has actions; refusing to replace them.")

        def data_asset(name, asset_class):
            factory = unreal.DataAssetFactory()
            factory.set_editor_property("data_asset_class", asset_class)
            asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                name, f"/{plugin_name}/Foundation", asset_class, factory)
            if asset is None:
                raise RuntimeError(f"Asset creation failed: {name}")
            report["Assets"].append(asset.get_path_name())
            write_report()
            return asset

        setting = data_asset("DA_SampleEnabled", classes["setting"])
        setting.set_editor_property("setting_id", content_id + ".Enabled")
        setting.set_editor_property("display_name", "Sample enabled (stored value only)")
        setting.set_editor_property("default_value", True)
        contributor = data_asset("DA_SampleSettings", classes["contributor"])
        contributor.set_editor_property("contributor_id", content_id)
        contributor.set_editor_property("definitions", [setting])
        settings_action = unreal.new_object(classes["settings_action"], outer=feature, name="SampleSettings")
        settings_action.set_editor_property("settings", contributor)
        fragment = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
            "BP_SampleProgress", f"/{plugin_name}/Foundation", unreal.Blueprint, unreal.AtlasSaveFragmentFactory())
        if fragment is None:
            raise RuntimeError("Save Fragment factory failed.")
        report["Assets"].append(fragment.get_path_name())
        write_report()
        integer_type = unreal.EdGraphPinType()
        if not integer_type.import_text('(PinCategory="int")'):
            raise RuntimeError("Could not resolve the Blueprint integer type.")
        if not unreal.BlueprintEditorLibrary.add_member_variable(fragment, "Visits", integer_type):
            raise RuntimeError("Could not create the sample's persistent Visits variable.")
        if not unreal.AtlasSaveFragmentFactory.set_variable_persistence(fragment, "Visits", True):
            raise RuntimeError("Could not mark Visits for persistence.")
        if not unreal.BlueprintEditorLibrary.compile_blueprint(fragment):
            raise RuntimeError("Save Fragment Blueprint compilation failed.")
        fragment_class = fragment.generated_class()
        defaults = unreal.get_default_object(fragment_class)
        defaults.set_editor_property("fragment_id", "Mods." + content_id + ".Progress")
        defaults.set_editor_property("schema_version", 1)
        contribution = unreal.AtlasModSaveFragmentContribution()
        contribution.set_editor_property("save_id", target_save_id)
        contribution.set_editor_property("fragment_class", fragment_class)
        contribution.set_editor_property("size_limit_bytes", 65536)
        save_action = unreal.new_object(classes["save_action"], outer=feature, name="SampleSave")
        save_action.set_editor_property("fragments", [contribution])
        feature.set_editor_property("actions", [settings_action, save_action])
        report["Assets"].append(feature.get_path_name())

        for asset in (setting, contributor, fragment, feature):
            if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
                raise RuntimeError(f"Asset save failed: {asset.get_path_name()}")
        report["Status"] = "Complete"
        write_report()
        marker.unlink()
        unreal.log(f"Foundation sample assets saved. Not activated or certified. Report: {report_path}")
        return str(report_path)
    except Exception as error:
        report["Status"] = "Failed"
        report["Error"] = str(error)
        write_report()
        raise


if __name__ == "__main__":
    create_sample()
