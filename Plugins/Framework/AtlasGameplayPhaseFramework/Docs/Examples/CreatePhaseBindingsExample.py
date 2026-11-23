# Copyright Callback LLP. All Rights Reserved.
"""Draft a GameState phase binding in a mod's GameFeatureData. The caller reviews and saves it."""
import unreal


def create_bindings(feature, folder, phases, priority=0, name="BP_GameplayPhaseBindings"):
    if not isinstance(feature, unreal.GameFeatureData):
        raise TypeError("Select the mod's GameFeatureData.")
    mount = feature.get_path_name().split("/", 2)[1]
    if not folder.startswith("/" + mount + "/"):
        raise ValueError("The binding must belong to the same content mount as the feature.")
    if not isinstance(priority, int) or not -2147483648 <= priority <= 2147483647:
        raise ValueError("Priority must be an int32. Larger values override lower-priority bindings.")
    if not phases:
        raise ValueError("Supply at least one concrete Gameplay Phase Ability class.")
    tags = []
    for phase in phases:
        if not phase or not isinstance(unreal.get_default_object(phase), unreal.AtlasGamePhaseAbility):
            raise TypeError("Every phase must derive from Gameplay Phase Ability.")
        phase_tag = unreal.get_default_object(phase).get_editor_property("game_phase_tag")
        tag = str(phase_tag.export_text())
        if not unreal.GameplayTagLibrary.is_gameplay_tag_valid(phase_tag) or tag in tags:
            raise ValueError("Each ability needs a valid, distinct Game Phase Tag: " + tag)
        tags.append(tag)
    if unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name):
        raise FileExistsError(folder + "/" + name)
    action_class = unreal.load_class(None, "/Script/GameFeatures.GameFeatureAction_AddComponents")
    if action_class is None:
        raise RuntimeError("Game Feature Add Components is unavailable.")
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.AtlasGamePhaseBindingsComponent)
    bp = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, folder, unreal.Blueprint, factory)
    if bp is None:
        raise RuntimeError("Could not create the binding Blueprint.")
    defaults = unreal.get_default_object(bp.generated_class())
    defaults.set_editor_property("phases", list(phases))
    defaults.set_editor_property("priority", priority)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(bp):
        raise RuntimeError("Binding Blueprint did not compile; inspect the retained draft.")
    entry = unreal.GameFeatureComponentEntry()
    entry.set_editor_property("actor_class", unreal.GameStateBase)
    entry.set_editor_property("component_class", bp.generated_class())
    entry.set_editor_property("server_component", True)
    entry.set_editor_property("client_component", False)
    action = unreal.new_object(action_class, outer=feature)
    action.set_editor_property("ComponentList", [entry])
    feature.set_editor_property("actions", list(feature.get_editor_property("actions")) + [action])
    return {"component": bp, "action": action}
