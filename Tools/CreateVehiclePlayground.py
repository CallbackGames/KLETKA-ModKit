# Copyright Callback LLP. All Rights Reserved.
"""Create an editable, art-free vehicle example using AtlasVehicleSystem physics.

Run on Entry in an unattended editor. W/S drive, A/D steer, Space brakes, Left Shift handbrakes.
The car and its tuning asset are independent of the shooter playground.
Assign DA_ExampleDriftCar to VehicleMovement.Definition to opt into rear-wheel drift.
"""
import json
from pathlib import Path
import unreal


def create_vehicle_playground(folder="/Game/AtlasExamples/Vehicles"):
    if not unreal.SystemLibrary.is_unattended():
        raise RuntimeError("Run in a fresh unattended editor; this recipe replaces the current map.")
    if unreal.EditorAssetLibrary.does_directory_have_assets(folder):
        raise FileExistsError("Choose a new destination; existing examples are retained.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    assets = []

    def asset(name, cls, factory):
        result = tools.create_asset(name, folder, cls, factory)
        if result is None:
            raise RuntimeError("Could not create " + name)
        assets.append(result)
        return result

    def blueprint(name, parent):
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", parent)
        return asset(name, unreal.Blueprint, factory)

    def component(bp, cls, name, parent=None):
        handles = sub.k2_gather_subobject_data_for_blueprint(bp)
        args = unreal.AddNewSubobjectParams(parent_handle=parent or handles[0], new_class=cls, blueprint_context=bp)
        handle, error = sub.add_new_subobject(args)
        if str(error):
            raise RuntimeError(str(error))
        sub.rename_subobject(handle, name)
        return handle, lib.get_object_for_blueprint(lib.get_data(handle), bp)

    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.AtlasVehicleDefinition)
    definition = asset("DA_ExampleRoadCar", unreal.AtlasVehicleDefinition, factory)
    unreal.AtlasVehicleAuthoringLibrary.apply_vehicle_preset(definition, unreal.AtlasVehiclePreset.ROAD_CAR)
    # This self-contained example uses the canonical legacy input relay. Projects that
    # enable Physics Prediction can opt into the definition's network-physics mode.
    definition.set_editor_property("use_network_physics", False)
    drift_definition = asset("DA_ExampleDriftCar", unreal.AtlasVehicleDefinition, factory)
    unreal.AtlasVehicleAuthoringLibrary.apply_vehicle_preset(drift_definition, unreal.AtlasVehiclePreset.DRIFT_CAR)
    drift_definition.set_editor_property("use_network_physics", False)
    pawn = blueprint("BP_ExampleRoadCar", unreal.Pawn)
    body_handle, body = component(pawn, unreal.StaticMeshComponent, "Chassis")
    root_handle = sub.k2_gather_subobject_data_for_blueprint(pawn)[0]
    if not sub.make_new_scene_root(root_handle, body_handle, pawn):
        raise RuntimeError("Could not make the physics chassis the root")
    body.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
    body.set_editor_property("relative_scale3d", unreal.Vector(2, 1, 0.4))
    body.set_collision_profile_name("PhysicsActor")
    body.set_simulate_physics(True)
    _, movement = component(pawn, unreal.AtlasWheeledVehicleMovementComponent, "VehicleMovement")
    movement.set_editor_property("definition", definition)
    movement.set_editor_property("replicates", True)
    _, visuals = component(pawn, unreal.AtlasVehicleWheelVisualsComponent, "WheelVisuals")
    bindings = []
    for wheel in definition.get_editor_property("wheels"):
        wheel_id = str(wheel.get_editor_property("wheel_id"))
        _, mesh = component(pawn, unreal.StaticMeshComponent, "Wheel_" + wheel_id, body_handle)
        mesh.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cylinder"))
        mesh.set_collision_profile_name("NoCollision")
        # Keep the Blueprint preview useful as well as the runtime pose. Solver offsets
        # are centimetres; this example's box chassis has nonuniform mesh scale.
        mesh.set_editor_property("absolute_scale", True)
        mesh.set_editor_property("relative_scale3d", unreal.Vector(.64, .64, .2))
        mesh.set_editor_property("relative_rotation", unreal.Rotator(roll=90, pitch=0, yaw=0))
        location = wheel.get_editor_property("location")
        mesh.set_editor_property("relative_location", unreal.Vector(location.x / 2, location.y, location.z / .4))
        reference = unreal.ComponentReference()
        reference.set_editor_property("component_property", "Wheel_" + wheel_id)
        binding = unreal.AtlasVehicleWheelVisualBinding()
        binding.set_editor_property("wheel_id", wheel.get_editor_property("wheel_id"))
        binding.set_editor_property("component", reference)
        binding.set_editor_property("mesh_transform", unreal.Transform(
            rotation=unreal.Rotator(roll=90, pitch=0, yaw=0), scale=unreal.Vector(.64, .64, .2)))
        bindings.append(binding)
    visuals.set_editor_property("wheels", bindings)
    arm_handle, arm = component(pawn, unreal.SpringArmComponent, "CameraArm", body_handle)
    arm.set_editor_property("target_arm_length", 650.0)
    arm.set_editor_property("relative_location", unreal.Vector(0, 0, 150))
    arm.set_editor_property("relative_rotation", unreal.Rotator(pitch=-12, yaw=0, roll=0))
    component(pawn, unreal.CameraComponent, "Camera", arm_handle)
    defaults = unreal.get_default_object(pawn.generated_class())
    defaults.set_editor_property("replicates", True)
    defaults.set_editor_property("replicate_movement", True)
    if not E.compile_blueprint(pawn):
        raise RuntimeError("Vehicle component composition does not compile")
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(pawn))

    def pin(node, name):
        found = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(found) != 1:
            raise RuntimeError("Missing pin " + name)
        return found[0]

    def connect(a, an, b, bn):
        if not P.try_create_connection(pin(a, an), pin(b, bn)):
            raise RuntimeError("Could not connect " + an + " to " + bn)

    for row, (key, function, value) in enumerate([
        ("W", "SetThrottleInput", "1.0"), ("S", "SetThrottleInput", "-1.0"),
        ("A", "SetSteeringInput", "-1.0"), ("D", "SetSteeringInput", "1.0"),
        ("SpaceBar", "SetBrakeInput", "1.0"), ("LeftShift", "SetHandbrakeInput", "true")]):
        event = graph.create_node_from_name("Input|KeyboardEvents|" + key, unreal.Vector2D(0, row * 400), [])
        getter = graph.add_get_member_variable_node("VehicleMovement")
        E.set_node_pos(getter, unreal.IntPoint(0, row * 400 + 220))
        release = "false" if function == "SetHandbrakeInput" else "0.0"
        for index, (exec_name, amount) in enumerate([("Pressed", value), ("Released", release)]):
            call = graph.add_call_function_node("/Script/ChaosVehicles.ChaosVehicleMovementComponent:" + function)
            connect(event, exec_name, call, "execute")
            connect(getter, "VehicleMovement", call, "self")
            input_name = "bNewHandbrake" if function == "SetHandbrakeInput" else function.removeprefix("Set").removesuffix("Input")
            if not P.set_pin_value(pin(call, input_name), amount):
                raise RuntimeError("Could not set vehicle input")
            E.set_node_pos(call, unreal.IntPoint(360 + index * 320, row * 400))
    if not E.compile_blueprint(pawn):
        raise RuntimeError("Vehicle controls do not compile")
    mode = blueprint("BP_VehicleGameMode", unreal.GameModeBase)
    unreal.get_default_object(mode.generated_class()).set_editor_property("default_pawn_class", pawn.generated_class())
    # The ordinary Pawn CDO has no SCS collision body for GameModeBase's overlap query.
    # Allocate the demo's parking bays explicitly, so two players cannot spawn stacked.
    start_graph = E.add_function_override(mode, "ChoosePlayerStart")
    if start_graph is None:
        raise RuntimeError("Could not author vehicle demo spawn selection")
    starts = unreal.BlueprintGraphEditor.get_graph_editor(start_graph)
    nodes = list(starts.list_all_nodes())
    entry = next(n for n in nodes if n.get_class().get_name() == "K2Node_FunctionEntry")
    result = next(n for n in nodes if n.get_class().get_name() == "K2Node_FunctionResult")
    starts.remove_nodes([n for n in nodes if n not in (entry, result)])
    find = starts.add_call_function_node("/Script/Engine.GameplayStatics:GetAllActorsOfClass")
    if not P.set_pin_value(pin(find, "ActorClass"), "/Script/Engine.PlayerStart"):
        raise RuntimeError("Could not select demo player start class")
    count = starts.add_call_function_node("/Script/Engine.KismetArrayLibrary:Array_Length")
    players = starts.add_call_function_node("/Script/Engine.GameModeBase:GetNumPlayers")
    index = starts.add_call_function_node("/Script/Engine.KismetMathLibrary:Percent_IntInt")
    select = starts.add_call_function_node("/Script/Engine.KismetArrayLibrary:Array_Get")
    connect(entry, "then", find, "execute")
    connect(find, "then", players, "execute")
    connect(players, "then", result, "execute")
    connect(find, "OutActors", count, "TargetArray")
    connect(find, "OutActors", select, "TargetArray")
    connect(players, "ReturnValue", index, "A")
    connect(count, "ReturnValue", index, "B")
    connect(index, "ReturnValue", select, "Index")
    connect(select, "Item", result, "ReturnValue")
    for i, node in enumerate(starts.list_all_nodes()):
        E.set_node_pos(node, unreal.IntPoint((i % 4) * 330, (i // 4) * 250))
    starts.add_comment_to_nodes("Two-player demo: use distinct parking bays. Game projects own their spawn and respawn policy.",
                               list(starts.list_all_nodes()), 40)
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    if world.get_world_settings().get_class().get_path_name() not in ("/Script/Engine.WorldSettings", "/Script/AtlasGameplayExperienceFrameworkRuntime.AtlasGameplayWorldSettings"):
        raise RuntimeError("Use public world settings for exported maps")
    world.get_world_settings().set_editor_property("default_game_mode", mode.generated_class())
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    floor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(1500, 0, -50))
    floor.get_editor_property("static_mesh_component").set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
    floor.set_actor_scale3d(unreal.Vector(100, 100, 1))
    actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 0, 150))
    actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 500, 150))
    actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 900), unreal.Rotator(pitch=-50, yaw=0, roll=0))
    actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 800))
    for obj in assets:
        if isinstance(obj, unreal.Blueprint) and not E.compile_blueprint(obj):
            raise RuntimeError("Blueprint compilation failed: " + obj.get_path_name())
        if not unreal.EditorAssetLibrary.save_loaded_asset(obj, False):
            raise RuntimeError("Save failed: " + obj.get_path_name())
    map_path = folder + "/L_Vehicles"
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, map_path):
        raise RuntimeError("Could not save vehicle map")
    return {"Map": map_path, "Assets": [obj.get_path_name() for obj in assets]}


if __name__ == "__main__":
    report = create_vehicle_playground()
    out = Path(unreal.Paths.project_saved_dir()) / "ModKitPlayground"
    out.mkdir(parents=True, exist_ok=True)
    (out / "vehicle-creation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
