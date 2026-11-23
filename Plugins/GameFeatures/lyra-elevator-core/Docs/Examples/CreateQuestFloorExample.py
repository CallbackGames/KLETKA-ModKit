# Copyright Callback LLP. All Rights Reserved.
"""Create a floor with an editable door objective, using public owner contracts.

Run unattended in the generated ModKit on Entry. The destination must be new.
The server reports a committed door opening; restore/replication only refresh visuals.
No game art, private scoring types, automatic disk saves or client progress RPCs.
"""
import importlib.util
from pathlib import Path
import unreal


def create_example(plugin_name="AtlasQuestFloorExample", content_id="atlas.questfloor.example", completion_phase=None):
    recipe = Path(__file__).with_name("CreateFloorModExample.py")
    spec = importlib.util.spec_from_file_location("floor_recipe", recipe)
    floor_recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(floor_recipe)
    dependencies = ["AtlasSaveGameFramework"]
    if completion_phase:
        dependencies.append("AtlasGameplayPhaseFramework")
    created = floor_recipe.create_example(plugin_name, content_id, dependencies)
    folder = "/" + plugin_name + "/FloorExample"
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = []

    def tag(name):
        result = unreal.GameplayTag()
        if not result.import_text('(TagName="' + name + '")'):
            raise RuntimeError("Missing public example tag: " + name)
        return result

    operation = tag("Interaction.Operation.Example.OpenDoor")
    event_tag = tag("Quest.Event.Example.DoorOpened")
    quest = unreal.load_asset(folder + "/" + floor_recipe.quest_asset_name(plugin_name))
    helper = unreal.get_default_object(unreal.load_class(None, "/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary"))
    outcome = helper.call_method("AddPlaygroundQuestObjective", (quest, event_tag, "Open the panel door: {Current}/{Target}"))
    failure = outcome[-1] if isinstance(outcome, tuple) else outcome
    if str(failure):
        raise RuntimeError("Quest owner rejected starter objective: " + str(failure))
    defaults = unreal.get_default_object(quest.generated_class())
    defaults.set_editor_property("display_name", "Open the panel door")
    defaults.set_editor_property("description", "Open the door on this floor. Restoring an open door does not repeat progress.")
    defaults.set_editor_property("contributor_scope", unreal.AtlasContributorScope.SESSION)
    if not E.compile_blueprint(quest):
        raise RuntimeError("Door objective does not compile")
    assets.append(quest)

    def create(name, cls, factory=None):
        if unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name):
            raise FileExistsError(folder + "/" + name)
        if factory is None:
            factory = unreal.DataAssetFactory()
            factory.set_editor_property("data_asset_class", cls)
        obj = tools.create_asset(name, folder, cls, factory)
        if not obj:
            raise RuntimeError("Could not create " + name)
        assets.append(obj)
        return obj

    def blueprint(name, parent):
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", parent)
        return create(name, unreal.Blueprint, factory)

    def pin(node, name):
        matches = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(matches) != 1:
            raise RuntimeError("Missing pin " + node.get_name() + "." + name)
        return matches[0]

    def link(a, an, b, bn):
        if not P.try_create_connection(pin(a, an), pin(b, bn)):
            raise RuntimeError("Cannot connect " + an + " -> " + bn)

    def value(node, name, text):
        if not P.set_pin_value(pin(node, name), text):
            raise RuntimeError("Cannot set " + name)

    def action(graph, name):
        choices = [str(a) for a in graph.list_available_nodes([]) if str(a).split("|")[-1] == name]
        if len(choices) != 1:
            raise RuntimeError("Expected one public node " + name + ": " + str(choices))
        return graph.create_node_from_name(choices[0], unreal.Vector2D(0, 0), [])

    action_bp = blueprint("BP_OpenDoorAction", unreal.AtlasInteractionActionComponent)
    unreal.get_default_object(action_bp.generated_class()).set_editor_property("action_tag", operation)
    for function in ("CanExecuteAction", "ExecuteAction"):
        graph = unreal.BlueprintGraphEditor.get_graph_editor(E.add_function_override(action_bp, function))
        nodes = list(graph.list_all_nodes())
        entry = next(n for n in nodes if n.get_class().get_name() == "K2Node_FunctionEntry")
        result = next(n for n in nodes if n.get_class().get_name() == "K2Node_FunctionResult")
        P.break_pin_links(pin(entry, "then"))
        graph.remove_nodes([n for n in nodes if n.get_class().get_name() == "K2Node_CallParentFunction"])
        owner = graph.add_call_function_node("/Script/Engine.ActorComponent:GetOwner")
        door = graph.add_call_function_node("/Script/Engine.Actor:GetComponentByClass")
        value(door, "ComponentClass", "/Script/AtlasInteraction.AtlasDoorComponent")
        link(owner, "ReturnValue", door, "self")
        valid = graph.add_call_function_node("/Script/Engine.KismetSystemLibrary:IsValid")
        link(door, "ReturnValue", valid, "Object")
        gate = graph.add_branch_node()
        link(entry, "then", gate, "execute"); link(valid, "ReturnValue", gate, "Condition")
        rejected = graph.add_return_node()
        link(gate, "else", rejected, "execute"); value(rejected, "ReturnValue", "false")
        value(rejected, "OutFailureReason", "Door state is unavailable.")
        if function == "CanExecuteAction":
            read = graph.add_call_function_node("/Script/AtlasInteraction.AtlasDoorComponent:GetDoorState")
            state = action(graph, "BreakAtlasDoorState")
            invert = graph.add_call_function_node("/Script/Engine.KismetMathLibrary:Not_PreBool")
            link(door, "ReturnValue", read, "self"); link(read, "ReturnValue", state, "AtlasDoorState")
            link(state, "bOpened", invert, "A"); link(invert, "ReturnValue", result, "ReturnValue")
            link(gate, "then", result, "execute")
        else:
            command = graph.add_call_function_node("/Script/AtlasInteraction.AtlasDoorComponent:SetDoorOpened")
            context = graph.add_call_function_node("/Script/AtlasInteraction.AtlasInteractionContextLibrary:GetInteractorActor")
            link(entry, "Context", context, "Context")
            link(context, "ReturnValue", command, "Interactor")
            link(door, "ReturnValue", command, "self"); value(command, "bOpened", "true")
            link(gate, "then", command, "execute"); link(command, "then", result, "execute")
            link(command, "ReturnValue", result, "ReturnValue")
        for i, node in enumerate(graph.list_all_nodes()):
            E.set_node_pos(node, unreal.IntPoint((i % 5) * 330, (i // 5) * 220))
    if not E.compile_blueprint(action_bp):
        raise RuntimeError("Door action does not compile")

    door_bp = blueprint("BP_QuestDoor", unreal.Actor)
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary

    def component(cls, name, parent=None):
        handles = sub.k2_gather_subobject_data_for_blueprint(door_bp)
        handle, error = sub.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=parent or handles[0], new_class=cls, blueprint_context=door_bp))
        if str(error):
            raise RuntimeError(str(error))
        sub.rename_subobject(handle, name)
        return handle, lib.get_object_for_blueprint(lib.get_data(handle), door_bp)

    root, _ = component(unreal.SceneComponent, "Root")
    handles = sub.k2_gather_subobject_data_for_blueprint(door_bp)
    if not sub.make_new_scene_root(handles[0], root, door_bp):
        raise RuntimeError("Could not create door root")
    _, panel = component(unreal.StaticMeshComponent, "Panel", root)
    panel.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
    panel.set_editor_property("relative_scale3d", unreal.Vector(0.15, 1, 2))
    panel.set_editor_property("relative_location", unreal.Vector(0, 50, 100))
    panel.set_mobility(unreal.ComponentMobility.MOVABLE)
    panel.set_collision_profile_name("BlockAllDynamic")
    _, door = component(unreal.AtlasDoorComponent, "DoorState")
    _, save = component(unreal.AtlasSavableComponent, "SaveState")
    save.set_editor_property("persistence_group", "KLETKA.Run.World")
    save.set_editor_property("use_scene_identity", True)
    _, target = component(unreal.AtlasInteractionTargetComponent, "InteractionTarget")
    component(action_bp.generated_class(), "OpenDoorAction")
    option = create("IO_OpenDoor", unreal.AtlasInteractionOption)
    option.set_editor_property("default_display_text", "Open")
    option.set_editor_property("input_mode", unreal.AtlasInteractionInputMode.PRESS)
    execution = option.get_editor_property("execution")
    if not execution.import_text('/Script/AtlasInteraction.AtlasInteractionActionExecution(Endpoint=Target,Action=(TagName="Interaction.Operation.Example.OpenDoor"))'):
        raise RuntimeError("Public action execution is unavailable")
    option.set_editor_property("execution", execution)
    profile = create("IP_QuestDoor", unreal.AtlasInteractionProfile)
    profile.set_editor_property("options", [option])
    target.set_editor_property("interaction_profile", profile)
    if not E.compile_blueprint(door_bp):
        raise RuntimeError("Door components do not compile")
    unreal.get_default_object(door_bp.generated_class()).set_editor_property("replicates", True)
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(door_bp))
    live = graph.add_component_bound_event_node(door, "OnDoorStateChanged")
    restored = graph.add_component_bound_event_node(door, "OnDoorStateRestored")
    begin = E.add_event_override(door_bp, "ReceiveBeginPlay", unreal.IntPoint(0, 0))
    door_get = graph.add_get_member_variable_node("DoorState")
    panel_get = graph.add_get_member_variable_node("Panel")
    read = graph.add_call_function_node("/Script/AtlasInteraction.AtlasDoorComponent:GetDoorState")
    link(door_get, "DoorState", read, "self")
    state = action(graph, "BreakAtlasDoorState"); link(read, "ReturnValue", state, "AtlasDoorState")
    # Separate live and quiet projection branches: loading can never submit quest progress.
    projections = []
    for event in (live, restored, begin):
        branch = graph.add_branch_node(); link(event, "then", branch, "execute")
        link(state, "bOpened", branch, "Condition")
        opened = None
        for route, rotation in (("then", "0,90,0"), ("else", "0,0,0")):
            rotate = graph.add_call_function_node("/Script/Engine.SceneComponent:K2_SetRelativeRotation")
            link(panel_get, "Panel", rotate, "self"); link(branch, route, rotate, "execute")
            value(rotate, "NewRotation", rotation)
            if route == "then": opened = rotate
        projections.append(opened)
    authority = graph.add_call_function_node("/Script/Engine.Actor:HasAuthority")
    gate = graph.add_branch_node(); link(projections[0], "then", gate, "execute"); link(authority, "ReturnValue", gate, "Condition")
    gs = graph.add_call_function_node("/Script/Engine.GameplayStatics:GetGameState")
    find = graph.add_call_function_node("/Script/AtlasQuestSystemRuntime.AtlasQuestBlueprintLibrary:FindQuestManagerOnActor")
    link(gs, "ReturnValue", find, "QuestOwner")
    valid = graph.add_call_function_node("/Script/Engine.KismetSystemLibrary:IsValid"); link(find, "ReturnValue", valid, "Object")
    manager_gate = graph.add_branch_node(); link(gate, "then", manager_gate, "execute"); link(valid, "ReturnValue", manager_gate, "Condition")
    save_get = graph.add_get_member_variable_node("SaveState")
    identity = graph.add_call_function_node("/Script/AtlasSaveGameFrameworkRuntime.AtlasSavableComponent:GetPersistentId")
    link(save_get, "SaveState", identity, "self")
    fact = action(graph, "MakeAtlasProgressEvent")
    value(fact, "EventTag", event_tag.export_text()); value(fact, "Magnitude", "1.0")
    link(identity, "ReturnValue", fact, "CorrelationId")
    submit = graph.add_call_function_node("/Script/AtlasQuestSystemRuntime.AtlasQuestManagerComponent:SubmitProgressEvent")
    link(manager_gate, "then", submit, "execute"); link(find, "ReturnValue", submit, "self")
    link(fact, "AtlasProgressEvent", submit, "ProgressEvent")
    for i, node in enumerate(graph.list_all_nodes()):
        E.set_node_pos(node, unreal.IntPoint((i % 6) * 330, (i // 6) * 240))
    if not E.compile_blueprint(door_bp):
        raise RuntimeError("Door progress/presentation does not compile")
    if completion_phase:
        completion_spec = importlib.util.spec_from_file_location("quest_completion_recipe", Path(__file__).with_name("AddQuestCompletionPhase.py"))
        completion_recipe = importlib.util.module_from_spec(completion_spec)
        completion_spec.loader.exec_module(completion_recipe)
        completion_recipe.configure_completion(quest, completion_phase)
    world = unreal.EditorLoadingAndSavingUtils.load_map(created["map"])
    actor = unreal.get_editor_subsystem(unreal.EditorActorSubsystem).spawn_actor_from_class(door_bp.generated_class(), unreal.Vector(1400, 0, 0))
    if not actor:
        raise RuntimeError("Could not place quest door")
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, created["map"]):
        raise RuntimeError("Could not save quest floor")
    created["assets"].extend(a.get_path_name() for a in assets if a.get_path_name() not in created["assets"])
    created["objectiveEvent"] = "Quest.Event.Example.DoorOpened"
    created["completionPhase"] = completion_phase
    created["door"] = door_bp.get_path_name()
    return created
