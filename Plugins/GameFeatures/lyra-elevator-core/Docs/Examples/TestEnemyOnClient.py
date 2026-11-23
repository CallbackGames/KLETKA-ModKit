"""Run inside an isolated two-player PIE session launched by the content authoring panel."""
import json
import math
import os
import time
import traceback
from pathlib import Path

import unreal as u


def run():
    request = Path(os.environ["ATLAS_ENEMY_TEST_REQUEST"])
    config = json.loads(request.read_text(encoding="utf-8"))
    report = request.parent / "result.json"
    result = {"success": False, "enemy": config["enemy"], "stage": "waiting for remote player"}
    game = u.GameplayStatics
    editor = u.get_editor_subsystem(u.LevelEditorSubsystem)
    expires = time.monotonic() + 120

    def finish(error=None):
        if error:
            result["error"] = error
        result["success"] = error is None
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        u.unregister_slate_post_tick_callback(callback)
        frames.close()
        editor.editor_request_end_play()
        u.EditorPythonScripting.set_keep_python_script_alive(False)

    def scenario():
        # This scenario exercises the authored pawn directly. Mount the selected
        # workspace content in this disposable editor just as the Mod Wizard does.
        # Artifact admission and Game Feature activation are covered by the package tests.
        plugin = config["enemy"].split("/")[1]
        root = Path(u.Paths.convert_relative_path_to_full(u.Paths.project_dir())) / "Plugins/GameFeatures"
        descriptor = Path(config.get("descriptor", root / plugin / (plugin + ".uplugin"))).resolve(strict=True)
        if descriptor.stem != plugin or not descriptor.is_relative_to(root.resolve()):
            raise ValueError("Enemy must belong to the selected source Game Feature.")
        worlds = u.get_editor_subsystem(u.UnrealEditorSubsystem)
        while True:
            editor_world = worlds.get_editor_world()
            if editor_world and not editor_world.get_path_name().startswith("/Temp/Untitled"):
                break
            del editor_world
            yield
        asset = config["enemy"].split(".")[0]
        if not u.AssetRegistryHelpers.get_asset_registry().get_assets_by_path("/" + plugin, recursive=True):
            content = (descriptor.parent / "Content").as_posix() + "/"
            u.SystemLibrary.execute_console_command(editor_world, f'PackageName.RegisterMountPoint /{plugin}/ "{content}"')
            u.AssetRegistryHelpers.get_asset_registry().scan_paths_synchronous(["/" + plugin], force_rescan=True)
        result["source_mount"] = "/" + plugin
        pawn = u.EditorAssetLibrary.load_blueprint_class(asset)
        if not pawn:
            raise RuntimeError("Feature did not supply " + config["enemy"])
        del editor_world
        import gc
        gc.collect()
        result["stage"] = "waiting for remote player"
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        editor.editor_request_begin_play()
        while True:
            worlds = u.EditorLevelLibrary.get_pie_worlds(False)
            ready = [w for w in worlds if game.get_game_state(w)]
            server = next((w for w in ready if game.get_game_state(w).has_authority()), None)
            client = next((w for w in ready if not game.get_game_state(w).has_authority()), None)
            if server and client:
                controllers = [game.get_player_controller(server, i) for i in range(game.get_num_player_controllers(server))]
                remote = next((p for p in controllers if p and not p.is_local_controller()), None)
                local = game.get_player_controller(client, 0)
                target = remote.get_controlled_pawn() if remote else None
                peer = local.get_controlled_pawn() if local else None
                if target and peer and peer.is_locally_controlled() and target.get_name() == peer.get_name():
                    health = u.AtlasHealthComponent.find_atlas_health_component(target)
                    replica = u.AtlasHealthComponent.find_atlas_health_component(peer)
                    if health and replica and health.get_current_health() == replica.get_current_health() > 0:
                        break
            yield
        initial = health.get_current_health()
        preview = config.get("preview")
        if preview:
            culture = preview["culture"]
            if not u.InternationalizationLibrary.set_current_culture(culture, False):
                raise RuntimeError("Unrecognized preview culture: " + culture)
            using_gamepad = preview["gamepad"]
            if not u.AtlasContentAuthoringOptions.set_remote_preview_input(local, using_gamepad):
                raise RuntimeError("CommonInput could not select the requested input type on the remote player.")
            library = u.get_default_object(u.load_class(None, "/Script/Engine.SubsystemBlueprintLibrary"))
            input_subsystem = library.call_method("GetLocalPlayerSubSystemFromPlayerController",
                                                  (local, u.CommonInputSubsystem.static_class()))
            result["preview"] = {"culture": u.InternationalizationLibrary.get_current_culture(),
                                 "client_world": client.get_path_name(), "client_player": local.get_path_name()}
            hud = local.get_hud()
            result["preview"]["hud"] = hud.get_class().get_path_name() if hud else None
        result.update(stage="waiting for an attributed attack", player=target.get_path_name(), initial_health=initial)
        result["stage"] = "waiting for an attributed attack"
        spawn = u.get_default_object(game.static_class())
        scale = u.SpawnActorScaleMethod.MULTIPLY_WITH_ROOT
        def begin(cls, transform):
            return spawn.call_method("BeginDeferredActorSpawnFromClass", (server, cls, transform, u.SpawnActorCollisionHandlingMethod.ALWAYS_SPAWN, None, scale))
        # Give the test its own floor away from authored encounters and other damage sources.
        origin = target.get_actor_location() + u.Vector(0, 0, 2500)
        ground = u.Transform(location=origin-u.Vector(0,0,target.capsule_component.get_scaled_capsule_half_height()+15), scale=u.Vector(20,20,.3))
        platform = begin(u.StaticMeshActor.static_class(), ground)
        platform.set_replicates(True)
        mesh = platform.static_mesh_component
        mesh.set_mobility(u.ComponentMobility.MOVABLE)
        mesh.set_static_mesh(u.load_asset("/Engine/BasicShapes/Cube.Cube"))
        mesh.set_collision_profile_name("BlockAll")
        spawn.call_method("FinishSpawningActor", (platform, ground, scale))
        for actor in (target, peer):
            actor.character_movement.set_movement_mode(u.MovementMode.MOVE_NONE)
            actor.set_actor_location(origin, False, True)
        ready = time.monotonic()+1
        while time.monotonic()<ready:
            yield
        # Keep the remote target stationary until impact so client prediction cannot
        # move it off the isolated test floor while the test pawn enters the world.
        for actor in (target, peer):
            actor.set_actor_location(origin, False, True)
        loc = origin + u.Vector(150,0,0)
        transform = u.Transform(location=loc,rotation=u.Rotator(yaw=180))
        enemy = begin(pawn,transform)
        if not enemy:
            raise RuntimeError("Enemy could not spawn on the server.")
        spawn.call_method("FinishSpawningActor", (enemy, transform, scale))
        start = enemy.get_component_by_class(u.AtlasNPCComponent)
        agent = enemy.get_component_by_class(u.AtlasAIAgentComponent)
        enemy.set_actor_rotation(u.MathLibrary.find_look_at_rotation(loc, origin), True)
        if not start or not agent:
            raise RuntimeError("Enemy needs an Atlas NPC component and an AI agent.")
        if not enemy.get_controller():
            enemy.spawn_default_controller()
        # Restore both movement owners before combat so the normal hit impulse can run.
        for actor in (target, peer):
            actor.set_actor_location(origin, False, True)
            actor.character_movement.set_movement_mode(u.MovementMode.MOVE_WALKING)
        start.start_npc()
        first_position = peer.get_actor_location()
        result["hit_events"] = []
        result["max_client_horizontal_cm"] = 0
        def damaged(component, old, new, instigator, causer, tags):
            if (instigator == enemy or causer == enemy) and new < old:
                result["hit"] = {"before": old, "after": new, "tags": tags.export_text()}
                result["hit_events"].append(result["hit"])
        health.on_health_changed.add_callable(damaged)
        teams = u.get_default_object(u.load_class(None, "/Script/Engine.SubsystemBlueprintLibrary")).call_method("GetWorldSubsystem", (server, u.AtlasTeamSubsystem.static_class()))
        if teams:
            relation, source_team, player_team = teams.compare_teams(enemy, target)
            result["teams"] = {"relation": str(relation), "enemy": source_team.value, "player": player_team.value}
        observation = u.AtlasAIObservationSample()
        for key, value in dict(target=target, location=target.get_actor_location(), generation=agent.get_context_generation(), sample_time=game.get_time_seconds(server), sensed=True).items():
            observation.set_editor_property(key, value)
        report.write_text(json.dumps(result, indent=2), encoding="utf-8")
        if not agent.submit_observation(observation):
            raise RuntimeError("AI rejected the remote player sight observation.")
        result["presentation"] = {"culture": u.InternationalizationLibrary.get_current_culture(), "cues": [], "lens_effects": [], "selected_sounds": []}
        def observe(kind, value):
            if value and value not in result["presentation"][kind]:
                result["presentation"][kind].append(value)
        def player_effects():
            for cue in game.get_all_actors_of_class(client, u.GameplayCueNotify_Actor):
                if cue.get_owner() != peer and cue.get_attach_parent_actor() != peer:
                    continue
                observe("cues", cue.get_class().get_path_name())
                try:
                    sound = cue.get_editor_property("DamageSoundToPlay")
                except Exception:
                    sound = None
                if sound:
                    observe("selected_sounds", sound.get_path_name())
            view_target = local.get_view_target()
            for effect in game.get_all_actors_with_interface(client, u.CameraLensEffectInterface):
                if effect.get_owner() == view_target:
                    observe("lens_effects", effect.get_class().get_path_name())
        feedback_until = None
        started = time.monotonic()
        while True:
            location = peer.get_actor_location()
            result["max_client_horizontal_cm"] = max(result["max_client_horizontal_cm"],
                math.hypot(location.x-first_position.x, location.y-first_position.y))
            if time.monotonic() - started > 30 and len(result["hit_events"]) < config.get("min_hits", 1):
                raise TimeoutError("NPC did not damage its observed remote target; see AI, visibility, team and distance fields.")
            player_effects()
            result["ai"] = {field: str(start.get_editor_property(field)) for field in (
                "setup_reason", "decision_reason", "combat_movement_reason", "combat_attack_reason")}
            context = agent.get_context()
            result.update(visible=context.get_editor_property("visible"), intent=str(context.get_editor_property("intent")), distance_cm=enemy.get_distance_to(target), selected_target=(context.target.get_path_name() if context.target else None), server_health=health.get_current_health(), client_health=replica.get_current_health())
            if len(result["hit_events"]) >= config.get("min_hits", 1) and result["client_health"] == result["server_health"] < initial:
                if feedback_until is None:
                    result["stage"] = "remote player received enemy damage"
                    if preview:
                        active = input_subsystem.get_current_input_type()
                        result["preview"]["input_type_at_hit"] = str(active)
                        if active != (u.CommonInputType.GAMEPAD if using_gamepad else u.CommonInputType.MOUSE_AND_KEYBOARD):
                            raise RuntimeError("The remote player's input type changed before impact.")
                        if u.InternationalizationLibrary.get_current_culture() != result["preview"]["culture"]:
                            raise RuntimeError("The preview culture changed before impact.")
                    feedback_until = time.monotonic() + 1
                    # Read back a rendered frame after replication and local UI have had an opportunity to paint.
                    yield
                if preview and preview["capture_viewport"] and "screenshot" not in result["preview"]:
                    image = report.parent / "client-hit.png"
                    if not u.AtlasContentAuthoringOptions.capture_remote_player_viewport(local, str(image)):
                        raise RuntimeError("Could not capture the remote player's viewport. Run the test with rendering enabled.")
                    result["preview"]["screenshot"] = str(image)
            if feedback_until is not None and time.monotonic() >= feedback_until:
                return
            yield

    frames = scenario()
    def tick(delta):
        try:
            if time.monotonic() > expires:
                raise TimeoutError(result["stage"] + ". Use a playable map with a replicated player pawn, health and a hostile target policy.")
            next(frames)
        except StopIteration:
            finish()
        except Exception:
            finish(traceback.format_exc())
    u.EditorPythonScripting.set_keep_python_script_alive(True)
    callback = u.register_slate_post_tick_callback(tick)


if __name__ == "__main__":
    run()
