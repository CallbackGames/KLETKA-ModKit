# Copyright Callback LLP. All Rights Reserved.
"""Create a minimal cosmetic, profile and preset through public owner factories.

Run in Editor Python. Configure an AtlasCosmetic Asset Manager scan for package_root
before restarting the editor. The generated ModKit already scans its example paths.
This creates assets only; it does not grant ownership or apply a player appearance.
"""
import re


def create_example(package_root="/Game/AtlasExamples/Cosmetics", prefix="Example"):
    import unreal

    if not re.fullmatch(r"/[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)+", package_root):
        raise ValueError("Use an absolute, ASCII content package directory.")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", prefix):
        raise ValueError("Use an ASCII asset prefix starting with a letter.")
    names = ("BP_" + prefix + "Part", "DA_" + prefix + "Cosmetic", "DA_" + prefix + "AppearanceProfile", "DA_" + prefix + "AppearancePreset")
    if any(unreal.EditorAssetLibrary.does_asset_exist(package_root + "/" + name) for name in names):
        raise FileExistsError("Choose a new directory; existing example assets are retained.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = []

    def create(name, cls, factory):
        asset = tools.create_asset(name, package_root, cls, factory)
        if asset is None:
            raise RuntimeError("Factory failed for " + name)
        assets.append(asset)
        return asset

    def tag(value):
        result = unreal.GameplayTag()
        if not result.import_text('(TagName="' + value + '")'):
            raise RuntimeError("Could not read registered tag " + value)
        return result

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.StaticMeshActor)
    part = create(names[0], unreal.Blueprint, factory)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(part):
        raise RuntimeError("Part Blueprint compilation failed.")
    mesh = unreal.load_asset("/Engine/BasicShapes/Cube")
    if mesh is None:
        raise RuntimeError("Engine BasicShapes/Cube is unavailable.")
    defaults = unreal.get_default_object(part.generated_class())
    defaults.get_editor_property("static_mesh_component").set_editor_property("static_mesh", mesh)

    cosmetic = create(names[1], unreal.AtlasCosmeticDefinition, unreal.AtlasCosmeticDefinitionFactory())
    cosmetic.set_editor_property("slot_tag", tag("Cosmetic.Slot.Default"))
    presentation = unreal.AtlasPresentationEntry()
    presentation.set_editor_property("actor_part_class", part.generated_class())
    cosmetic.set_editor_property("presentations", [presentation])
    display = unreal.AtlasCosmeticDisplayData()
    display.set_editor_property("display_name", "Example cube attachment")
    cosmetic.set_editor_property("display_data", display)

    profile = create(names[2], unreal.AtlasAppearanceProfile, unreal.AtlasAppearanceProfileFactory())
    rule = unreal.AtlasSourcePriorityRule()
    rule.set_editor_property("source_tag", tag("Cosmetic.Source.User"))
    rule.set_editor_property("priority", 100)
    profile.set_editor_property("source_priorities", [rule])

    preset = create(names[3], unreal.AtlasAppearancePreset, unreal.AtlasAppearancePresetFactory())
    # Read the saved owner's identity before Asset Manager registers the new asset.
    # SystemLibrary only resolves already registered assets and is invalid on first creation.
    if not unreal.EditorAssetLibrary.save_loaded_asset(cosmetic, only_if_is_dirty=False):
        raise RuntimeError("Could not save the cosmetic definition.")
    data = unreal.EditorAssetLibrary.find_asset_data(cosmetic.get_path_name())
    asset_type = str(data.get_tag_value("PrimaryAssetType"))
    asset_name = str(data.get_tag_value("PrimaryAssetName"))
    identity = unreal.PrimaryAssetId()
    if asset_type != "AtlasCosmetic" or asset_name in ("", "None") or not identity.import_text(asset_type + ":" + asset_name):
        raise RuntimeError("The cosmetic factory did not assign a valid stable identity.")
    entry = unreal.AtlasAppearancePresetEntry()
    entry.set_editor_property("cosmetic_id", identity)
    preset.set_editor_property("entries", [entry])
    preset.set_editor_property("preview_profile", profile)
    preset.set_editor_property("preview_source_tag", tag("Cosmetic.Source.User"))
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return [asset.get_path_name() for asset in assets]


if __name__ == "__main__":
    create_example()
