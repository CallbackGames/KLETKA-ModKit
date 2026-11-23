# Copyright Callback LLP. All Rights Reserved.
"""Owner-provided cosmetic starter. Creates only assets in the new mod mount."""
import unreal


def populate_template(plugin_name, content_id):
    folder = "/" + plugin_name + "/CosmeticExample"
    names = ("BP_ExampleCosmetic", "DA_ExampleCosmetic")
    for name in names:
        path = folder + "/" + name
        if unreal.EditorAssetLibrary.does_asset_exist(path) or unreal.find_object(None, path + "." + name):
            raise RuntimeError("Cosmetic starter destination already contains " + path)
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if feature is None or list(feature.get_editor_property("actions")):
        raise RuntimeError("Cosmetic starter requires a new empty Game Feature Data.")
    slot = unreal.GameplayTag()
    if not slot.import_text('(TagName="Cosmetic.Slot.Default")'):
        raise RuntimeError("The public default cosmetic slot is unavailable.")
    mesh = unreal.load_asset("/Engine/BasicShapes/Cone")
    if mesh is None:
        raise RuntimeError("The engine's example cone mesh is unavailable.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.AtlasCosmeticActor)
    actor = tools.create_asset(names[0], folder, unreal.Blueprint, factory)
    if actor is None:
        raise RuntimeError("Could not create the public cosmetic actor Blueprint.")
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    handles = sub.k2_gather_subobject_data_for_blueprint(actor)
    world_views = []
    for handle in handles:
        obj = lib.get_object_for_blueprint(lib.get_data(handle), actor)
        if obj is not None and obj.get_name() == "WorldView":
            world_views.append(handle)
    if len(world_views) != 1:
        raise RuntimeError("Expected one inherited WorldView presentation subtree.")
    handle, error = sub.add_new_subobject(unreal.AddNewSubobjectParams(
        parent_handle=world_views[0], new_class=unreal.StaticMeshComponent, blueprint_context=actor))
    if str(error):
        raise RuntimeError(str(error))
    sub.rename_subobject(handle, "ExampleMarker")
    marker = lib.get_object_for_blueprint(lib.get_data(handle), actor)
    marker.set_editor_property("static_mesh", mesh)
    marker.set_editor_property("relative_scale3d", unreal.Vector(0.2, 0.2, 0.25))
    marker.set_editor_property("relative_location", unreal.Vector(0, 0, 175))
    marker.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(actor):
        raise RuntimeError("Cosmetic actor Blueprint does not compile.")
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.AtlasCosmeticDefinition)
    definition = tools.create_asset(names[1], folder, unreal.AtlasCosmeticDefinition, factory)
    if definition is None:
        raise RuntimeError("Could not create the cosmetic definition.")
    definition.set_editor_property("slot_tag", slot)
    display = unreal.AtlasCosmeticDisplayData()
    display.set_editor_property("display_name", "Example mod cosmetic")
    display.set_editor_property("description", "A visible starter marker. Replace its mesh and fit its attachment to your character.")
    definition.set_editor_property("display_data", display)
    presentation = unreal.AtlasPresentationEntry()
    presentation.set_editor_property("actor_part_class", actor.generated_class())
    definition.set_editor_property("presentations", [presentation])
    action = unreal.new_object(unreal.AtlasGameFeatureAction_AddModCosmetics, outer=feature)
    action.set_editor_property("cosmetics", [definition])
    feature.set_editor_property("actions", [action])
    for asset in (actor, definition, feature):
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {"plugin": plugin_name, "id": content_id,
            "assets": [asset.get_path_name() for asset in (actor, definition, feature)]}
