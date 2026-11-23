# Copyright Callback LLP. All Rights Reserved.
"""Build an editable saved Lua door using only public components and engine geometry.

The authoring wizard calls create_actor and owns saving/journaling. This module never writes
assets, opens a map or grants client interaction authority. Use a new destination folder.
"""
import re
import unreal

SOURCE = """return function(event, number, text, state, context)
    state.activations = (state.activations or 0) + 1
    -- The owner supplies its current door state under this example's event tag.
    atlas.emit(event, context[event] and 0 or 1, "")
    return state
end
"""


def create_actor(folder, script, event_tag, persistence_group, on_created=None):
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    if unreal.EditorAssetLibrary.does_asset_exist(folder + "/BP_LuaActor"):
        raise FileExistsError("BP_LuaActor already exists; choose a new folder.")
    if not persistence_group or str(persistence_group) == "None":
        raise ValueError("Choose a published world save group before creating the Lua door.")
    if not isinstance(script, unreal.AtlasLuaScript):
        raise TypeError("Expected an Atlas Lua Script asset.")
    script.set_editor_property("api_version", 2)
    script.set_editor_property("source_code", SOURCE)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.Actor)
    bp = tools.create_asset("BP_LuaActor", folder, unreal.Blueprint, factory)
    if not bp:
        raise RuntimeError("Could not create Lua actor; inspect retained draft.")
    if on_created is not None:
        on_created(bp)
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary

    def component(cls, name, parent=None):
        handles = sub.k2_gather_subobject_data_for_blueprint(bp)
        args = unreal.AddNewSubobjectParams(parent_handle=parent or handles[0], new_class=cls, blueprint_context=bp)
        handle, error = sub.add_new_subobject(args)
        if str(error):
            raise RuntimeError("Could not add " + name + ": " + str(error))
        sub.rename_subobject(handle, name)
        obj = lib.get_object_for_blueprint(lib.get_data(handle), bp)
        if obj is None:
            raise RuntimeError("Missing component template: " + name)
        return handle, obj

    root, _ = component(unreal.SceneComponent, "Root")
    _, panel = component(unreal.StaticMeshComponent, "Panel", root)
    panel.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
    panel.set_editor_property("relative_scale3d", unreal.Vector(0.15, 1.0, 2.0))
    panel.set_editor_property("relative_location", unreal.Vector(0.0, 50.0, 100.0))
    panel.set_mobility(unreal.ComponentMobility.MOVABLE)
    _, lua = component(unreal.AtlasLuaComponent, "LuaBehavior")
    lua.set_editor_property("script", script)
    _, door = component(unreal.AtlasDoorComponent, "DoorState")
    _, save = component(unreal.AtlasSavableComponent, "SaveState")
    save.set_editor_property("persistence_group", unreal.Name(persistence_group))
    store_type = unreal.load_object(None, "/Script/AtlasVariantDataFrameworkRuntime.AtlasVariantStore")
    if not E.add_member_variable(bp, "InputContext", E.get_struct_type(store_type)) or not E.compile_blueprint(bp):
        raise RuntimeError("Could not create the context variable.")
    defaults = unreal.get_default_object(bp.generated_class())
    defaults.set_editor_property("replicates", True)
    defaults.set_editor_property("replicate_movement", False)
    ge = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(bp))

    def pin(node, name):
        pins = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(pins) != 1:
            raise RuntimeError("Missing pin " + node.get_name() + "." + name)
        return pins[0]

    def link(a, an, b, bn):
        left, right = pin(a, an), pin(b, bn)
        if any(P.is_same_native_pin(other, right) for other in P.list_connected_pins(left)):
            return
        if not P.try_create_connection(left, right):
            raise RuntimeError("Cannot connect " + an + " -> " + bn)

    def value(node, name, text):
        if not P.set_pin_value(pin(node, name), text):
            raise RuntimeError("Cannot author " + name + " = " + text)

    def call(path):
        node = ge.add_call_function_node(path)
        if not node:
            raise RuntimeError("Public function unavailable: " + path)
        return node

    def getter(name):
        node = ge.add_get_member_variable_node(name)
        if not node:
            raise RuntimeError("Component variable unavailable: " + name)
        return node

    def break_struct(source, source_pin, struct_name, display_name=None):
        context_pin = pin(source, source_pin)
        # The action menu uses DisplayName metadata; the input pin keeps the native name.
        wanted = "break" + re.sub(r"[^a-z0-9]", "", (display_name or struct_name).lower())
        candidates = [str(name) for name in ge.list_available_nodes([context_pin])
                      if wanted in re.sub(r"[^a-z0-9]", "", str(name).lower())]
        if len(candidates) != 1:
            raise RuntimeError("Expected one public break node for " + struct_name + ": " + str(candidates))
        node = ge.create_node_from_name(candidates[0], unreal.Vector2D(0, 0), [context_pin])
        link(source, source_pin, node, struct_name)
        return node

    tag_text = event_tag.export_text()
    trigger = ge.add_custom_event_node("TriggerScript")
    authority = call("/Script/Engine.Actor:HasAuthority")
    allowed = ge.add_branch_node()
    link(trigger, "then", allowed, "execute"); link(authority, "ReturnValue", allowed, "Condition")
    context = getter("InputContext")
    clear = call("/Script/AtlasVariantDataFrameworkRuntime.AtlasVariantStoreLibrary:Clear")
    set_context = call("/Script/AtlasVariantDataFrameworkRuntime.AtlasVariantStoreLibrary:SetBool")
    door_get = getter("DoorState")
    read = call("/Script/AtlasInteraction.AtlasDoorComponent:GetDoorState")
    link(door_get, "DoorState", read, "self")
    state = break_struct(read, "ReturnValue", "AtlasDoorState", "Door State")
    link(context, "InputContext", clear, "Store"); link(context, "InputContext", set_context, "Store")
    link(allowed, "then", clear, "execute"); link(clear, "then", set_context, "execute")
    value(set_context, "Key", tag_text); link(state, "bOpened", set_context, "Value")
    run = call("/Script/AtlasLuaFrameworkRuntime.AtlasLuaComponent:RunEventWithContext")
    lua_get = getter("LuaBehavior")
    link(lua_get, "LuaBehavior", run, "self"); link(context, "InputContext", run, "Context")
    value(run, "Event", tag_text); value(run, "Number", "0.0")
    link(set_context, "then", run, "execute")
    run_ok = ge.add_branch_node(); link(run, "then", run_ok, "execute"); link(run, "ReturnValue", run_ok, "Condition")
    run_error = call("/Script/Engine.KismetSystemLibrary:PrintString")
    value(run_error, "bPrintToScreen", "false"); link(run_ok, "else", run_error, "execute"); link(run, "Error", run_error, "InString")

    signal = ge.add_component_bound_event_node(lua, "OnSignal")
    signal_data = break_struct(signal, "Signal", "AtlasLuaSignal")
    same_tag = call("/Script/GameplayTags.BlueprintGameplayTagLibrary:EqualEqual_GameplayTag")
    link(signal_data, "Channel", same_tag, "A"); value(same_tag, "B", tag_text)
    route = ge.add_branch_node(); link(signal, "then", route, "execute"); link(same_tag, "ReturnValue", route, "Condition")
    opened = call("/Script/Engine.KismetMathLibrary:NotEqual_DoubleDouble")
    link(signal_data, "Number", opened, "A"); value(opened, "B", "0.0")
    command = call("/Script/AtlasInteraction.AtlasDoorComponent:SetDoorOpened")
    link(route, "then", command, "execute"); link(door_get, "DoorState", command, "self")
    link(opened, "ReturnValue", command, "bOpened"); value(command, "bImmediately", "true")
    accepted = ge.add_branch_node(); link(command, "then", accepted, "execute"); link(command, "ReturnValue", accepted, "Condition")
    rejected = call("/Script/Engine.KismetSystemLibrary:PrintString")
    value(rejected, "InString", "Door rejected Lua request"); value(rejected, "bPrintToScreen", "false")
    link(accepted, "else", rejected, "execute")

    # The same projection handles live changes, quiet restore and late initial state.
    project = ge.add_branch_node(); link(state, "bOpened", project, "Condition")
    for event_name in ["OnDoorStateChanged", "OnDoorStateRestored"]:
        event = ge.add_component_bound_event_node(door, event_name)
        link(event, "then", project, "execute")
    begin = E.add_event_override(bp, "ReceiveBeginPlay", unreal.IntPoint(0, 900))
    link(begin, "then", project, "execute")
    panel_get = getter("Panel")
    for output, rotation in [("then", "0, 90, 0"), ("else", "0, 0, 0")]:
        rotate = call("/Script/Engine.SceneComponent:K2_SetRelativeRotation")
        link(project, output, rotate, "execute"); link(panel_get, "Panel", rotate, "self")
        value(rotate, "NewRotation", rotation)
    for index, node in enumerate(ge.list_all_nodes()):
        E.set_node_pos(node, unreal.IntPoint((index % 6) * 330, (index // 6) * 230))
    if not E.compile_blueprint(bp):
        raise RuntimeError("Lua door example did not compile; inspect the retained draft.")
    if not unreal.get_default_object(bp.generated_class()).get_editor_property("replicates"):
        raise RuntimeError("Replicated actor default was lost during compilation.")
    return bp
