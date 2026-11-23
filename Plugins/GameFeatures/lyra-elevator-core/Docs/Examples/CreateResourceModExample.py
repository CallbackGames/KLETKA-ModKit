# Copyright Callback LLP. All Rights Reserved.
import importlib.util
from pathlib import Path
import unreal

def populate_template(plugin_name, content_id):
    spec = importlib.util.spec_from_file_location("_content_floor_recipe", Path(__file__).with_name("CreateFloorModExample.py"))
    recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recipe)
    result = recipe.populate_template(plugin_name, content_id)
    folder = "/" + plugin_name + "/ContentExample"
    if unreal.EditorAssetLibrary.does_directory_exist(folder):
        raise RuntimeError("Starter destination already exists.")
    floor = unreal.load_asset("/" + plugin_name + "/FloorExample/DA_Floor")
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = []
    def data(name, cls):
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", cls)
        asset = tools.create_asset(name, folder, cls, factory)
        if asset is None:
            raise RuntimeError("Could not create " + name)
        assets.append(asset)
        return asset

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.StaticMeshActor)
    actor = tools.create_asset("BP_ExampleResource", folder, unreal.Blueprint, factory)
    if actor is None or not unreal.BlueprintEditorLibrary.compile_blueprint(actor):
        raise RuntimeError("Resource actor could not be created or compiled.")
    assets.append(actor)
    defaults = unreal.get_default_object(actor.generated_class())
    defaults.set_editor_property("replicates", True)
    defaults.set_editor_property("replicate_movement", True)
    body = defaults.get_editor_property("static_mesh_component")
    body.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
    body.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
    body.set_editor_property("relative_scale3d", unreal.Vector(0.25, 0.25, 0.25))
    resource = data("DA_ExampleResource", unreal.AtlasResourceDefinition)
    resource.set_editor_property("item_identity_type", unreal.AtlasResourceItemIdentityType.ACTOR_CLASS)
    resource.set_editor_property("actor_class", actor.generated_class())
    resource.set_editor_property("spawn_type", unreal.AtlasResourceSpawnType.RANDOM)
    pack = data("DA_ExampleResourcePack", unreal.AtlasResourcePack)
    pack.set_editor_property("display_name", "Example resource pack")
    pack.set_editor_property("description", "One cube resource on the test floor; replace it with your actor or an inventory identity.")
    processor = unreal.new_object(unreal.AtlasResourceSpawnProcessor, outer=pack)
    # Kismet's lookup only returns IDs already registered in AssetManager. This feature is
    # still being authored, so use the definition's generated stable identity directly.
    resource_id = recipe.authored_primary_asset_id(resource, "Resource")
    processor.set_editor_property("resource_id", resource_id)
    processor.set_editor_property("default_spawn_chance", 100.0)
    processor.set_editor_property("add_spawn_chance_by_player", 0.0)
    processor.set_editor_property("spawn_chance_variation", 0.0)
    processor.set_editor_property("min_amount", 1)
    processor.set_editor_property("max_amount", 1)
    pack.set_editor_property("processors", [processor])
    fragment = unreal.new_object(unreal.LeFloorLootFragment, outer=floor)
    pack_id = recipe.authored_primary_asset_id(pack, "ResourcePack")
    fragment.set_editor_property("resource_pack_ids", [pack_id])
    floor.set_editor_property("fragments", list(floor.get_editor_property("fragments")) + [fragment])
    scans = list(feature.get_editor_property("primary_asset_types_to_scan"))
    for asset_type, cls, asset in (("Resource", unreal.AtlasResourceDefinition, resource),
                                   ("ResourcePack", unreal.AtlasResourcePack, pack)):
        scan = unreal.PrimaryAssetTypeInfo()
        scan.set_editor_property("primary_asset_type", asset_type)
        scan.set_editor_property("asset_base_class", cls)
        scan.set_editor_property("specific_assets", [unreal.SoftObjectPath(asset.get_path_name())])
        scans.append(scan)
    feature.set_editor_property("primary_asset_types_to_scan", scans)

    for asset in assets + [floor, feature]:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    result["content_assets"] = [a.get_path_name() for a in assets]
    result["assets"] = list(dict.fromkeys(result["assets"] + result["content_assets"]))
    return result
