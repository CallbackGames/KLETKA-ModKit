# Copyright Callback LLP. All Rights Reserved.
"""Entity + public component + isolated playable floor. No private actor parents or base assets are edited."""
import importlib.util
from pathlib import Path
import unreal


class ExampleGraph:
    """Small checked graph writer shared by the owner recipes; failures stop authoring."""
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin

    def __init__(self, blueprint):
        self.blueprint = blueprint
        self.graph = unreal.BlueprintGraphEditor.get_graph_editor_by_name(blueprint, "EventGraph")

    def pin(self, node, name):
        found = [p for p in self.E.list_all_pins(node) if str(self.P.get_pin_name(p)) == name] if node else []
        if len(found) != 1:
            raise RuntimeError("Expected one graph pin: " + name)
        return found[0]

    def link(self, a, output, b, input):
        if not self.P.try_create_connection(self.pin(a, output), self.pin(b, input)):
            raise RuntimeError("Could not connect " + output + " -> " + input)

    def value(self, node, name, value):
        if not self.P.set_pin_value(self.pin(node, name), str(value)):
            raise RuntimeError("Could not set pin " + name)

    def call(self, path):
        node = self.graph.add_call_function_node(path)
        if not node:
            raise RuntimeError("Missing public function " + path)
        return node

    def action(self, name):
        matches = [str(a) for a in self.graph.list_available_nodes([]) if str(a).split("|")[-1] == name]
        if len(matches) != 1:
            raise RuntimeError("Expected one graph action " + name + ": " + str(matches))
        return self.graph.create_node_from_name(matches[0], unreal.Vector2D(0, 0), [])

    def member(self, name, owner=""):
        node = self.graph.add_get_member_variable_node(name, owner)
        if not node:
            raise RuntimeError("Missing public member " + name)
        return node

    def event(self, name):
        return self.E.add_event_override(self.blueprint, name, unreal.IntPoint(0, 0))

    def branch(self, previous, condition, output="ReturnValue", route="then"):
        node = self.graph.add_branch_node()
        self.link(previous, route, node, "execute")
        self.link(condition, output, node, "Condition")
        return node

    def valid(self, previous, value, output="ReturnValue"):
        check = self.call("/Script/Engine.KismetSystemLibrary:IsValid")
        self.link(value, output, check, "Object")
        return self.branch(previous, check)

    def compile(self):
        fixed = unreal.get_default_object(unreal.load_class(None, '/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary')).call_method('EnsureExampleNodeIds', (self.blueprint,))
        if fixed is None or fixed[-1]:
            raise RuntimeError("Invalid example graph identities: " + str(fixed))
        for i, node in enumerate(self.graph.list_all_nodes()):
            self.E.set_node_pos(node, unreal.IntPoint((i % 6) * 350, (i // 6) * 250))
        if not self.E.compile_blueprint(self.blueprint):
            raise RuntimeError("Example graph does not compile: " + self.blueprint.get_path_name())


def author_familiar(blueprint):
    """Claim on authoritative player overlap; follow the PlayerState's current pawn."""
    g = ExampleGraph(blueprint)
    familiar = g.member("Familiar")
    authority = g.call("/Script/Engine.Actor:HasAuthority")
    overlap = g.event("ReceiveActorBeginOverlap")
    gate = g.branch(overlap, authority)
    cast = g.action("CastToPawn")
    g.link(gate, "then", cast, "execute")
    g.link(overlap, "OtherActor", cast, "Object")
    player = g.call("/Script/Engine.Pawn:IsPlayerControlled")
    g.link(cast, "AsPawn", player, "self")
    player_gate = g.branch(cast, player)
    owner = g.call("/Script/RoguelikeCoreComponents.RoFamiliarComponent:GetOwningPlayer")
    g.link(familiar, "Familiar", owner, "self")
    claimed = g.valid(player_gate, owner)
    state = g.member("PlayerState", "/Script/Engine.Pawn")
    g.link(cast, "AsPawn", state, "self")
    state_valid = g.call("/Script/Engine.KismetSystemLibrary:IsValid")
    g.link(state, "PlayerState", state_valid, "Object")
    claim_gate = g.branch(claimed, state_valid, route="else")
    assign = g.call("/Script/RoguelikeCoreComponents.RoFamiliarComponent:SetOwningPlayer")
    g.link(claim_gate, "then", assign, "execute")
    g.link(familiar, "Familiar", assign, "self")
    g.link(state, "PlayerState", assign, "Player")
    tick = g.event("ReceiveTick")
    tick_gate = g.branch(tick, authority)
    pawn = g.call("/Script/RoguelikeCoreComponents.RoFamiliarComponent:GetOwningPawn")
    g.link(familiar, "Familiar", pawn, "self")
    pawn_gate = g.valid(tick_gate, pawn)
    target = g.call("/Script/RoguelikeCoreComponents.RoFamiliarComponent:GetLocationToStickAroundPawn")
    g.link(familiar, "Familiar", target, "self")
    position = g.call("/Script/Engine.Actor:K2_GetActorLocation")
    move = g.call("/Script/Engine.KismetMathLibrary:VInterpTo")
    g.link(position, "ReturnValue", move, "Current")
    g.link(target, "ReturnValue", move, "Target")
    g.link(tick, "DeltaSeconds", move, "DeltaTime")
    g.value(move, "InterpSpeed", "4.0")
    apply = g.call("/Script/Engine.Actor:K2_SetActorLocation")
    g.link(pawn_gate, "then", apply, "execute")
    g.link(move, "ReturnValue", apply, "NewLocation")
    g.value(apply, "bSweep", "true")
    g.graph.add_comment_node("Server claims the first overlapping player's PlayerState. Later overlaps cannot steal it. The current pawn is re-queried after respawn; movement replicates from authority.", unreal.Vector2D(-40, -110), unreal.Vector2D(1800, 100))
    g.compile()


def author_boss(blueprint):
    """Two health-driven phases; death closes the encounter once on authority."""
    g = ExampleGraph(blueprint)
    encounter = g.member("Encounter")
    authority = g.call("/Script/Engine.Actor:HasAuthority")
    begin = g.event("ReceiveBeginPlay")
    gate = g.branch(begin, authority)
    state = g.call("/Script/RoguelikeCoreComponents.RoBossEncounterComponent:GetEncounterState")
    g.link(encounter, "Encounter", state, "self")
    fields = g.action("BreakRoBossEncounterState")
    g.link(state, "ReturnValue", fields, "RoBossEncounterState")
    fresh = g.call("/Script/Engine.KismetMathLibrary:EqualEqual_ByteByte")
    g.link(fields, "Status", fresh, "A")
    g.value(fresh, "B", "0")  # ERoBossEncounterStatus::NotStarted
    fresh_gate = g.branch(gate, fresh)
    # Restored running/completed encounters keep their phase and identity.
    start = g.call("/Script/RoguelikeCoreComponents.RoBossEncounterComponent:StartConfiguredEncounter")
    g.link(fresh_gate, "then", start, "execute")
    g.link(encounter, "Encounter", start, "self")
    tick = g.event("ReceiveTick")
    tick_gate = g.branch(tick, authority)
    health = g.member("Health")
    fraction = g.call("/Script/AtlasAbilitiesSystemRuntime.AtlasHealthComponent:GetHealthFraction")
    g.link(health, "Health", fraction, "self")
    phase = g.call("/Script/RoguelikeCoreComponents.RoBossEncounterComponent:SubmitSignal")
    g.link(tick_gate, "then", phase, "execute")
    g.link(encounter, "Encounter", phase, "self")
    g.value(phase, "Signal", '(TagName="Event.Boss.Input.HealthFraction")')
    g.link(fraction, "ReturnValue", phase, "Value")
    # Resolve behavior from persisted encounter state, including a restored phase Two.
    # SetGait changes the native motor's speed without restarting AI or invalidating its path.
    second = g.call("/Script/GameplayTags.BlueprintGameplayTagLibrary:EqualEqual_GameplayTag")
    g.link(fields, "Phase", second, "A")
    g.value(second, "B", '(TagName="State.AI.Boss.Phase.Two")')
    speed_gate = g.branch(phase, second)
    movement = g.member("Movement")
    sprint = g.call("/Script/AtlasLocomotionSystemRuntime.AtlasTraversalComponent:SetGait")
    g.link(speed_gate, "then", sprint, "execute")
    g.link(movement, "Movement", sprint, "self")
    g.value(sprint, "NewGait", "Sprint")
    death = g.event("OnNPCDeathStarted")
    death_gate = g.branch(death, authority)
    finish = g.call("/Script/RoguelikeCoreComponents.RoBossEncounterComponent:FinishEncounter")
    g.link(death_gate, "then", finish, "execute")
    g.link(encounter, "Encounter", finish, "self")
    g.value(finish, "Result", "Completed")
    connect_loot_drop(g, g.branch(finish, finish))
    g.graph.add_comment_node("DA_ExampleBossEncounter owns the health threshold and destination phase. This graph supplies health samples and applies the boss's movement behavior, including after restore. Actual server NPC death closes the encounter once, then requests the loot owner's cached remainder. Restore/replication never requests a drop. Persist encounter, loot ledger and pickup state together.", unreal.Vector2D(-40, -110), unreal.Vector2D(1800, 100))
    g.compile()


def connect_loot_drop(g, previous):
    loot = g.member("DeathLoot")
    drop = g.call("/Script/AtlasLoot.AtlasInventoryLootContainerComponent:DropLoot")
    g.link(previous, "then", drop, "execute")
    g.link(loot, "DeathLoot", drop, "self")
    g.value(drop, "bIgnoreRemainingAmount", "false")


def author_enemy_drop(blueprint):
    g = ExampleGraph(blueprint)
    death = g.event("OnNPCDeathStarted")
    authority = g.call("/Script/Engine.Actor:HasAuthority")
    connect_loot_drop(g, g.branch(death, authority))
    g.compile()


def populate_entity(plugin_name, content_id, kind):
    if kind not in ("Enemy", "Familiar", "Boss", "WorldActor"):
        raise RuntimeError("Unknown entity starter: " + kind)
    folder = "/" + plugin_name + "/EntityExample"
    if unreal.EditorAssetLibrary.does_directory_exist(folder):
        raise RuntimeError("Entity starter refuses an existing destination: " + folder)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    assets = []
    parent = unreal.Actor
    if kind in ("Enemy", "Boss"):
        examples = unreal.AtlasNPCExampleLibrary.create_combat_guard(folder + "/NPC")
        if not examples or examples[1]:
            raise RuntimeError("Combat guard authoring failed: " + str(examples))
        assets.extend(examples[0])
        parent = next(a for a in assets if a.get_name() == "BP_ExampleGuard").generated_class()
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", parent)
    actor = tools.create_asset("BP_Example" + kind, folder, unreal.Blueprint, factory)
    if actor is None:
        raise RuntimeError("Could not create the public actor Blueprint.")
    assets.append(actor)
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary

    def component(bp, cls, name):
        handles = sub.k2_gather_subobject_data_for_blueprint(bp)
        handle, error = sub.add_new_subobject(unreal.AddNewSubobjectParams(
            parent_handle=handles[0], new_class=cls, blueprint_context=bp))
        if str(error):
            raise RuntimeError(str(error))
        sub.rename_subobject(handle, name)
        return handle, lib.get_object_for_blueprint(lib.get_data(handle), bp)

    if kind not in ("Enemy", "Boss"):
        root, marker = component(actor, unreal.StaticMeshComponent, "ExampleBody")
        handles = sub.k2_gather_subobject_data_for_blueprint(actor)
        if not sub.make_new_scene_root(handles[0], root, actor):
            raise RuntimeError("Could not create the actor's public scene root.")
        marker.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
        marker.set_editor_property("relative_scale3d", unreal.Vector(0.6, 0.6, 1.2))
        marker.set_editor_property("mobility", unreal.ComponentMobility.MOVABLE)
        marker.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    definition = None
    inventory_content = None
    if kind in ("Enemy", "Boss"):
        item_factory = unreal.DataAssetFactory()
        item_factory.set_editor_property("data_asset_class", unreal.AtlasInventoryItemDefinition)
        item = tools.create_asset("DA_ExampleDrop", folder, unreal.AtlasInventoryItemDefinition, item_factory)
        if not item:
            raise RuntimeError("Could not create the mod-owned drop item.")
        item.set_editor_property("display_name", "Example boss trophy" if kind == "Boss" else "Example enemy drop")
        world_fragment = unreal.new_object(unreal.load_class(None, "/Script/AtlasInventorySystemRuntime.InventoryFragment_WorldActor"), outer=item)
        world_fragment.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
        world_fragment.set_editor_property("pickup_display_name", item.get_editor_property("display_name"))
        item.set_editor_property("fragments", [world_fragment])
        item_factory.set_editor_property("data_asset_class", unreal.AtlasInventoryContentSet)
        inventory_content = tools.create_asset("DA_EntityInventoryContent", folder, unreal.AtlasInventoryContentSet, item_factory)
        inventory_content.set_editor_property("content_id", content_id + ".drops")
        inventory_content.set_editor_property("items", [item])
        assets.extend([item, inventory_content])
        _, loot = component(actor, unreal.AtlasInventoryLootContainerComponent, "DeathLoot")
        rule = unreal.new_object(unreal.AtlasLootRule_FixedAsset, outer=loot)
        rule.set_editor_property("reference_mode", unreal.AtlasAssetReferenceMode.SOFT_ASSET)
        rule.set_editor_property("asset", item)
        table = unreal.new_object(unreal.AtlasLootRule_All, outer=loot)
        table.set_editor_property("children", [rule])
        loot.set_editor_property("inline_root_rule", table)
        loot.set_editor_property("spawn_definition_class", unreal.AtlasInventoryWorldCollectable)
        _, save = component(actor, unreal.AtlasSavableComponent, "SaveState")
        save.set_editor_property("persistence_group", "KLETKA.Run.World")
        # Existing combat owner restores living health without damage/death events;
        # dead actors become save tombstones instead of respawning with fresh loot.
        component(actor, unreal.AtlasHealthSaveComponent, "HealthState")
    if kind == "Enemy":
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.LeEnemyArchetypeDefinition)
        definition = tools.create_asset("DA_ExampleEnemy", folder, unreal.LeEnemyArchetypeDefinition, factory)
        if definition is None:
            raise RuntimeError("Could not create the enemy definition.")
        definition.set_editor_property("display_name", "Example enemy")
        definition.set_editor_property("display_description", "Editable ground guard: perception, navigation, GAS attack and health. Tune the included NPC definition, StateTree and ability.")
        _, identity = component(actor, unreal.LeEnemyArchetypeComponent, "EnemyIdentity")
        identity.set_editor_property("archetype_definition", definition)
        assets.append(definition)
    elif kind == "Familiar":
        component(actor, unreal.RoFamiliarComponent, "Familiar")
        _, save = component(actor, unreal.AtlasSavableComponent, "SaveState")
        save.set_editor_property("persistence_group", "KLETKA.Run.World")
        _, trigger = component(actor, unreal.SphereComponent, "ClaimRange")
        trigger.set_sphere_radius(220.0)
        trigger.set_collision_enabled(unreal.CollisionEnabled.QUERY_ONLY)
        trigger.set_collision_response_to_all_channels(unreal.CollisionResponseType.ECR_IGNORE)
        trigger.set_collision_response_to_channel(unreal.CollisionChannel.ECC_PAWN, unreal.CollisionResponseType.ECR_OVERLAP)
        trigger.set_editor_property("generate_overlap_events", True)
    elif kind == "Boss":
        _, encounter = component(actor, unreal.RoBossEncounterComponent, "Encounter")
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.RoBossEncounterDefinition)
        rules = tools.create_asset("DA_ExampleBossEncounter", folder, unreal.RoBossEncounterDefinition, factory)
        if not rules:
            raise RuntimeError("Could not create boss encounter definition.")
        rules.set_editor_property("definition_id", content_id + ".boss.encounter")
        first = unreal.RoBossPhaseDefinition()
        if not first.import_text('(Phase=(TagName="State.AI.Boss.Phase.One"),Transitions=((Signal=(TagName="Event.Boss.Input.HealthFraction"),Comparison=AtMost,Threshold=0.5,TargetPhase=(TagName="State.AI.Boss.Phase.Two"))))'):
            raise RuntimeError("Could not author initial boss phase.")
        second = unreal.RoBossPhaseDefinition()
        if not second.import_text('(Phase=(TagName="State.AI.Boss.Phase.Two"))'):
            raise RuntimeError("Could not author second boss phase.")
        rules.set_editor_property("initial_phase", first.get_editor_property("phase"))
        rules.set_editor_property("phases", [first, second])
        encounter.set_editor_property("definition", rules)
        assets.append(rules)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(actor):
        raise RuntimeError("Entity Blueprint does not compile.")
    if kind == "Familiar":
        author_familiar(actor)
    elif kind == "Boss":
        author_boss(actor)
    elif kind == "Enemy":
        author_enemy_drop(actor)
    defaults = unreal.get_default_object(actor.generated_class())
    defaults.set_editor_property("replicates", True)
    defaults.set_editor_property("replicate_movement", True)
    if definition is not None:
        definition.set_editor_property("pawn_class", actor.generated_class())

    # Reuse the same tested floor recipe as the ordinary floor template. Customize its anchor
    # before the isolated map is created, so no editor-world switch or repair resave is needed.
    spec = importlib.util.spec_from_file_location("_entity_floor_recipe", Path(__file__).with_name("CreateFloorModExample.py"))
    floor_recipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(floor_recipe)

    def create_map(path, unused_anchor_class):
        anchor = unreal.load_asset("/" + plugin_name + "/FloorExample/BP_FloorLayout")
        _, point = component(anchor, unreal.AtlasActorPlacementComponent, "ExamplePlacement")
        point.set_editor_property("default_actor_class", actor.generated_class())
        point.set_editor_property("allow_replacement", True)
        point.set_editor_property("allow_removal", True)
        point.set_editor_property("allow_additions", True)
        if not unreal.BlueprintEditorLibrary.compile_blueprint(anchor):
            raise RuntimeError("Floor placement Blueprint does not compile.")
        cdo = unreal.get_default_object(anchor.generated_class())
        cdo.set_editor_property("replicates", True)
        cdo.set_editor_property("always_relevant", True)
        return unreal.LeFloorModAuthoringLibrary.create_example_floor_map(path, anchor.generated_class())

    result = floor_recipe.populate_template(plugin_name, content_id, _create_map=create_map)
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if inventory_content is not None:
        inventory_action = unreal.new_object(unreal.AtlasGameFeatureAction_AddInventoryContent, outer=feature)
        inventory_action.set_editor_property("content", inventory_content)
        feature.set_editor_property("actions", list(feature.get_editor_property("actions")) + [inventory_action])
    if definition is not None:
        action = unreal.new_object(unreal.LeGameFeatureAction_AddEnemyContent, outer=feature)
        entry = unreal.LeEnemyArchetypeContribution()
        entry.set_editor_property("definition", definition)
        action.set_editor_property("entries", [entry])
        feature.set_editor_property("actions", list(feature.get_editor_property("actions")) + [action])
    for asset in assets + [feature]:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    result["entity_kind"] = kind
    result["entity_assets"] = [asset.get_path_name() for asset in assets]
    result["assets"] = list(dict.fromkeys(result["assets"] + result["entity_assets"]))
    return result
