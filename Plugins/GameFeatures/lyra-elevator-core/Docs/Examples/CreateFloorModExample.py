# Copyright Callback LLP. All Rights Reserved.
"""Create a new floor/biome/quest Game Feature using only public owners.

Creates an isolated map without switching or saving the current editor world.
The Wizard and command-line example share the same populate_template recipe.
Destinations must be new. The starter quest completes immediately; extend its
Quest Flow in the owner editor before designing a real objective.
"""
import json
from pathlib import Path
import unreal


def authored_primary_asset_id(asset, expected_type):
    """Read the saved object's own identity before its new Game Feature is registered.

    AssetManager's object lookup only sees already registered assets. Registry tags are
    emitted by the native GetPrimaryAssetId implementation and preserve generated IDs.
    """
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError("Could not save " + asset.get_path_name())
    data = unreal.EditorAssetLibrary.find_asset_data(asset.get_path_name())
    asset_type = data.get_tag_value("PrimaryAssetType")
    asset_name = data.get_tag_value("PrimaryAssetName")
    if asset_type != expected_type or not asset_name or asset_name == "None":
        raise RuntimeError("Missing authored primary identity: " + asset.get_path_name())
    identity = unreal.PrimaryAssetId()
    text = asset_type + ":" + asset_name
    if not identity.import_text(text) or identity.export_text() != text:
        raise RuntimeError("Invalid authored primary identity: " + text)
    return identity


def create_example(plugin_name="AtlasFloorExample", content_id="atlas.floor.example", additional_required_plugins=()):
    identity = unreal.AMSModAuthoringIdentity()
    identity.set_editor_property("template", unreal.AMSModTemplate.GAMEPLAY_GAME_FEATURE)
    identity.set_editor_property("content_id", content_id)
    identity.set_editor_property("plugin_name", plugin_name)
    identity.set_editor_property("required_plugin_names", list(dict.fromkeys(["ElevatorCore", "AtlasQuestSystem", *additional_required_plugins])))
    request = unreal.AMSNewModRequest()
    request.set_editor_property("identity", identity)
    presentation = unreal.AMSModAuthoringPresentation()
    presentation.set_editor_property("author", "Callback floor authoring example")
    request.set_editor_property("presentation", presentation)
    result = unreal.AMSModAuthoringBlueprintLibrary.create_mod_from_template(request)
    if result is None or not result.get_editor_property("success"):
        raise RuntimeError("Mod Wizard rejected the destination; inspect its validation messages.")
    created = populate_template(plugin_name, content_id)
    created.update(root=result.get_editor_property("mod_root"), manifest=result.get_editor_property("manifest_path"))
    return created


def quest_asset_name(plugin_name):
    # Quest identities use the generated class basename. A shared BP_FloorQuest
    # basename collides when two independently authored mods are registered.
    return "BP_" + plugin_name + "_FloorQuest"


def populate_template(plugin_name, content_id, _create_map=None):
    """Populate a new mounted Game Feature; preserve every existing editor world."""
    folder = "/" + plugin_name + "/FloorExample"
    names = ("BP_FloorLayout", quest_asset_name(plugin_name), "DA_Floor", "DA_Bundle", "DA_Biome", "L_ExampleFloor")
    if any(unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name) or
           unreal.find_object(None, folder + "/" + name + "." + name) for name in names):
        raise RuntimeError("Floor starter destination already contains assets.")
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if feature is None or list(feature.get_editor_property("actions")):
        raise RuntimeError("Floor starter requires a new empty Game Feature Data.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = []

    def create(name, cls, factory=None):
        if factory is None:
            factory = unreal.DataAssetFactory()
            factory.set_editor_property("data_asset_class", cls)
        asset = tools.create_asset(name, folder, cls, factory)
        if asset is None:
            raise RuntimeError("Could not create " + folder + "/" + name)
        assets.append(asset)
        return asset

    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    anchor_bp = create("BP_FloorLayout", unreal.Blueprint, factory)
    subobjects = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = subobjects.k2_gather_subobject_data_for_blueprint(anchor_bp)
    params = unreal.AddNewSubobjectParams()
    params.set_editor_property("parent_handle", handles[0])
    params.set_editor_property("new_class", unreal.LeFloorLayoutComponent)
    params.set_editor_property("blueprint_context", anchor_bp)
    handle, error = subobjects.add_new_subobject(params)
    if str(error):
        raise RuntimeError("Cannot add public floor layout: " + str(error))
    subobjects.rename_subobject(handle, "FloorLayout")
    if not subobjects.make_new_scene_root(handles[0], handle, anchor_bp):
        raise RuntimeError("Cannot make the public static layout the Blueprint root.")
    if not unreal.BlueprintEditorLibrary.compile_blueprint(anchor_bp):
        raise RuntimeError("Public layout Blueprint does not compile.")

    quest = create(quest_asset_name(plugin_name), unreal.AtlasQuestBlueprint, unreal.AtlasQuestDefinitionFactory())
    quest_defaults = unreal.get_default_object(quest.generated_class())
    quest_defaults.set_editor_property("display_name", "Visit the example floor")
    quest_defaults.set_editor_property("description", "Starter flow: completes on activation. Add objectives in Quest Flow.")
    quest_defaults.set_editor_property("requires_explicit_acceptance", False)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(quest):
        raise RuntimeError("Owner-created quest does not compile.")
    floor = create("DA_Floor", unreal.LeFloorDataAsset)
    quests = unreal.new_object(unreal.LeFloorQuestFragment, outer=floor)
    candidate = unreal.LeQuestFloorCandidate()
    candidate.set_editor_property("quest_class", quest.generated_class())
    quests.set_editor_property("quest_candidates", [candidate])
    title = unreal.new_object(unreal.LeFloorPresentationFragment, outer=floor)
    title.set_editor_property("display_name", "ModKit example floor")
    floor.set_editor_property("fragments", [title, quests])
    entry = unreal.LeBiomeFloorData()
    entry.set_editor_property("floor_data_asset", floor)
    bundle = create("DA_Bundle", unreal.LeFloorBundleDataAsset)
    bundle.set_editor_property("floors", [entry])
    biome = create("DA_Biome", unreal.LeBiomeDataAsset)
    biome.set_editor_property("floors_from_other_bundles", [bundle])
    biome_title = unreal.new_object(unreal.LeFloorPresentationFragment, outer=biome)
    biome_title.set_editor_property("display_name", "ModKit example biome")
    biome.set_editor_property("fragments", [biome_title])

    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    action_class = unreal.load_class(None, "/Script/ElevatorCoreContent.LeGameFeatureAction_AddFloorContent")
    if feature is None or action_class is None:
        raise RuntimeError("Floor owner action or generated Game Feature Data is unavailable.")
    action = unreal.new_object(action_class, outer=feature)
    slot_tag = unreal.GameplayTag()
    if not slot_tag.import_text('(TagName="Floor.Flow.Slot.Endless")'):
        raise RuntimeError("Public Endless insertion slot is not registered.")
    slot = unreal.LeFloorContentPlacement()
    slot.set_editor_property("entry_id", "ExampleEndlessFloor")
    slot.set_editor_property("modding_slot_tag", slot_tag)
    bundle_entry = unreal.LeBundleContentEntry()
    bundle_entry.set_editor_property("bundle", bundle)
    bundle_entry.set_editor_property("placements", [slot])
    bundles = unreal.new_object(unreal.LeFloorContentBlock_Bundles, outer=action)
    bundles.set_editor_property("entries", [bundle_entry])
    biome_entry = unreal.LeBiomeContentEntry()
    biome_entry.set_editor_property("biome", biome)
    biomes = unreal.new_object(unreal.LeFloorContentBlock_Biomes, outer=action)
    biomes.set_editor_property("entries", [biome_entry])
    # The bundle registers its contained floor; no duplicate floor contribution.
    action.set_editor_property("content_blocks", [bundles, biomes])
    feature.set_editor_property("actions", [action])
    assets.append(feature)

    map_path = folder + "/L_ExampleFloor"
    world, failure = (_create_map or unreal.LeFloorModAuthoringLibrary.create_example_floor_map)(map_path, anchor_bp.generated_class())
    if world is None or str(failure):
        raise RuntimeError(str(failure) or "Could not create isolated example map.")
    floor.set_editor_property("level", world)
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {"plugin": plugin_name, "id": content_id,
            "assets": [asset.get_path_name() for asset in assets], "map": map_path,
            "layoutParent": "/Script/Engine.Actor", "slot": "Floor.Flow.Slot.Endless"}


def inspect_open_floor():
    """Summarize the open floor without changing maps, selecting actors or saving packages."""
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    def xyz(v):
        return [v.x, v.y, v.z]

    report = {"LayoutOrigins": [], "NavigationBounds": [], "PlacementPoints": [], "PlayerStarts": []}
    for actor in sorted(actors, key=lambda value: value.get_path_name()):
        name = actor.get_path_name()
        for layout in actor.get_components_by_class(unreal.LeFloorLayoutComponent):
            report["LayoutOrigins"].append({"Actor": name, "Location": xyz(layout.get_world_location())})
        if isinstance(actor, unreal.NavMeshBoundsVolume):
            center, extent = actor.get_actor_bounds(False)
            report["NavigationBounds"].append({"Actor": name, "Center": xyz(center), "Extent": xyz(extent)})
        if isinstance(actor, unreal.PlayerStart):
            report["PlayerStarts"].append({"Actor": name, "Location": xyz(actor.get_actor_location())})
        for point in actor.get_components_by_class(unreal.AtlasActorPlacementComponent):
            report["PlacementPoints"].append({"Component": point.get_path_name(),
                "Location": xyz(actor.get_actor_location()), "Id": point.get_editor_property("placement_id").to_string(),
                "Tags": point.get_editor_property("placement_tags").export_text(),
                "BlocksSceneReadiness": point.get_editor_property("blocks_scene_readiness")})
    return report


def verify_example(plugin_name, expected_quest_asset_name=None):
    """Read back authored values and the public map; never saves or activates gameplay."""
    folder = "/" + plugin_name + "/FloorExample"
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    floor = unreal.load_asset(folder + "/DA_Floor")
    bundle = unreal.load_asset(folder + "/DA_Bundle")
    biome = unreal.load_asset(folder + "/DA_Biome")
    # Published examples retain their original quest identity; new recipes namespace it.
    quest = unreal.load_asset(folder + "/" + (expected_quest_asset_name or quest_asset_name(plugin_name)))
    if any(asset is None for asset in (feature, floor, bundle, biome, quest)):
        raise RuntimeError("Floor example is incomplete.")
    actions = list(feature.get_editor_property("actions"))
    if len(actions) != 1 or actions[0].get_class().get_path_name() != "/Script/ElevatorCoreContent.LeGameFeatureAction_AddFloorContent":
        raise RuntimeError("Public floor action was not persisted.")
    blocks = list(actions[0].get_editor_property("content_blocks"))
    if blocks:
        bundle_blocks = [block for block in blocks if isinstance(block, unreal.LeFloorContentBlock_Bundles)]
        biome_blocks = [block for block in blocks if isinstance(block, unreal.LeFloorContentBlock_Biomes)]
        if len(bundle_blocks) != 1 or len(biome_blocks) != 1:
            raise RuntimeError("Floor starter content blocks were not persisted.")
        bundle_entries = list(bundle_blocks[0].get_editor_property("entries"))
        biome_entries = list(biome_blocks[0].get_editor_property("entries"))
        if len(bundle_entries) != 1 or bundle_entries[0].get_editor_property("bundle") != bundle or \
                len(biome_entries) != 1 or biome_entries[0].get_editor_property("biome") != biome:
            raise RuntimeError("Floor starter definitions were not persisted.")
        slots = list(bundle_entries[0].get_editor_property("placements"))
    else:
        raise RuntimeError("Floor example must use the current content-block authoring schema.")
    if len(slots) != 1 or str(slots[0].get_editor_property("entry_id")) != "ExampleEndlessFloor":
        raise RuntimeError("Floor insertion entry was not persisted.")
    expected_slot = unreal.GameplayTag()
    if not expected_slot.import_text('(TagName="Floor.Flow.Slot.Endless")') or \
            slots[0].get_editor_property("modding_slot_tag").export_text() != expected_slot.export_text():
        raise RuntimeError("Floor insertion slot must use the registered public Floor.Flow.Slot.Endless tag.")
    if list(biome.get_editor_property("floors_from_other_bundles")) != [bundle]:
        raise RuntimeError("Biome no longer owns the example bundle.")
    entries = list(bundle.get_editor_property("floors"))
    if len(entries) != 1 or entries[0].get_editor_property("floor_data_asset") != floor:
        raise RuntimeError("Bundle no longer selects the example floor.")
    fragments = list(floor.get_editor_property("fragments"))
    quests = [value for value in fragments if isinstance(value, unreal.LeFloorQuestFragment)]
    candidates = list(quests[0].get_editor_property("quest_candidates")) if len(quests) == 1 else []
    if len(candidates) != 1 or candidates[0].get_editor_property("quest_class") != quest.generated_class():
        raise RuntimeError("Floor quest composition was not persisted.")
    if not unreal.BlueprintEditorLibrary.compile_blueprint(quest):
        raise RuntimeError("Reloaded quest does not compile.")
    map_path = folder + "/L_ExampleFloor"
    level = floor.get_editor_property("level")
    if level is None or level.get_path_name() != map_path + ".L_ExampleFloor":
        raise RuntimeError("Floor map reference was not persisted: " + str(level))
    # Cook & Test reads the world asset; opening it as the active editor map can additionally
    # initialize editor systems. Check for a load-time repair before that separate operation.
    if map_path in [package.get_path_name() for package in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]:
        raise RuntimeError("Reading the saved floor map changed its package. Cook & Test must not require a repair save.")
    # Loading an isolated authored world as the editor map first unloads its package.
    # A Python strong reference here prevents that unload and causes EditorServer's GC guard to fail.
    del level
    world = unreal.EditorLoadingAndSavingUtils.load_map(map_path)
    if world is None:
        raise RuntimeError("Cannot reload the public floor map.")
    if world.get_world_settings().get_class().get_path_name() not in ("/Script/Engine.WorldSettings", "/Script/AtlasGameplayExperienceFrameworkRuntime.AtlasGameplayWorldSettings"):
        raise RuntimeError("Public map retained private game world settings.")
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    layouts = [component for actor in actors for component in actor.get_components_by_class(unreal.LeFloorLayoutComponent)]
    if len(layouts) != 1 or layouts[0].get_editor_property("is_editor_only"):
        raise RuntimeError("Floor map requires exactly one cooked public layout component.")
    if layouts[0].get_owner().get_editor_property("root_component") != layouts[0]:
        raise RuntimeError("Public static layout must be the actor root.")
    nav_bounds = [actor for actor in actors if isinstance(actor, unreal.NavMeshBoundsVolume)]
    if len(nav_bounds) != 1:
        raise RuntimeError("Navigation bounds were not persisted.")
    _, extent = nav_bounds[0].get_actor_bounds(False)
    if min(extent.x, extent.y, extent.z) <= 0:
        raise RuntimeError("Reloaded navigation volume has no brush geometry.")
    return {"Plugin": plugin_name, "Map": map_path, "LayoutComponents": len(layouts),
            "QuestClass": quest.generated_class().get_path_name(), "FloorSlotEntries": len(slots),
            "NavigationExtent": [extent.x, extent.y, extent.z], "FloorDiagnostics": inspect_open_floor(), "AssetsSaved": 0}


if __name__ == "__main__":
    created = create_example()
    project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
    output = project / "Saved/FloorModExample"
    output.mkdir(parents=True, exist_ok=True)
    (output / "authoring.json").write_text(json.dumps(created, indent=2) + "\n", encoding="utf-8")
