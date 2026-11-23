# Copyright Callback LLP. All Rights Reserved.
"""Generate a neutral, editable host using public Atlas owners and engine shapes.

Run unattended on Entry with AtlasGameplayWorldSettings selected for new maps.
The output directory must be new. No KLETKA art or private gameplay types are used.
"""
import json
from pathlib import Path
import unreal


def add_npc_loot(blueprint, pickup_class, item):
    """Bind the public NPC death event to authoritative, ledger-backed loot delivery."""
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    handles = sub.k2_gather_subobject_data_for_blueprint(blueprint)
    for handle in handles:
        obj = lib.get_object_for_blueprint(lib.get_data(handle), blueprint)
        if isinstance(obj, unreal.AtlasInventoryLootContainerComponent):
            raise RuntimeError("Loot is already authored; inspect the existing component before changing it.")
    args = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=unreal.AtlasInventoryLootContainerComponent, blueprint_context=blueprint)
    handle, error = sub.add_new_subobject(args)
    if str(error):
        raise RuntimeError(str(error))
    sub.rename_subobject(handle, "Loot")
    loot = lib.get_object_for_blueprint(lib.get_data(handle), blueprint)
    rule = unreal.new_object(unreal.AtlasLootRule_FixedAsset, outer=loot)
    rule.set_editor_property("reference_mode", unreal.AtlasAssetReferenceMode.SOFT_ASSET)
    rule.set_editor_property("asset", item)
    loot.set_editor_property("inline_root_rule", rule)
    loot.set_editor_property("spawn_definition_class", pickup_class)
    loot.set_editor_property("spawn_instance_class", pickup_class)
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    if not E.compile_blueprint(blueprint):
        raise RuntimeError("NPC component composition does not compile")
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(blueprint))
    event = graph.create_node_from_name("AddEvent|NPC|EventOnNPCDeathStarted", unreal.Vector2D(0, 0), [])
    authority = graph.add_call_function_node("/Script/Engine.Actor:HasAuthority")
    branch = graph.add_branch_node()
    getter = graph.add_get_member_variable_node("Loot")
    drop = graph.add_call_function_node("/Script/AtlasLoot.AtlasInventoryLootContainerComponent:DropLoot")
    def pin(node, name):
        found = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(found) != 1:
            raise RuntimeError("Missing graph pin " + name)
        return found[0]
    for a, an, b, bn in [(event,"then",branch,"execute"),(authority,"ReturnValue",branch,"Condition"),(branch,"then",drop,"execute"),(getter,"Loot",drop,"self")]:
        if not P.try_create_connection(pin(a,an),pin(b,bn)):
            raise RuntimeError("Could not connect loot graph: " + an + " -> " + bn)
    if not P.set_pin_value(pin(drop,"DropImpulse"), "0.0"):
        raise RuntimeError("Could not set drop impulse")
    for node,x,y in [(event,0,0),(authority,0,160),(branch,260,0),(getter,260,160),(drop,540,0)]:
        E.set_node_pos(node, unreal.IntPoint(x,y))
    if not E.compile_blueprint(blueprint):
        raise RuntimeError("NPC loot graph does not compile")


def add_pickup_progress(owner, folder, schema=None, quest=None):
    """A committed pickup updates a typed statistic and advances one authoritative quest."""
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.AtlasStatisticsSchema)
    new_quest = quest is None
    schema = schema or tools.create_asset("DA_PlaygroundStatistics", folder, unreal.AtlasStatisticsSchema, factory)
    quest = quest or tools.create_asset("BP_PlaygroundQuest", folder, unreal.AtlasQuestBlueprint, unreal.AtlasQuestDefinitionFactory())
    if not schema or not quest:
        raise RuntimeError("Choose an empty destination for progress examples")
    key, event_tag = unreal.GameplayTag(), unreal.GameplayTag()
    if not key.import_text('(TagName="Statistics.Example.Pickups")') or not event_tag.import_text('(TagName="Quest.Event.Example.Pickup")'):
        raise RuntimeError("Install the public example tag configuration before generating progress assets")
    definition = unreal.AtlasStatisticDefinition()
    definition.set_editor_property("key", key)
    definition.set_editor_property("value_type", unreal.AtlasVariantValueType.INT32)
    zero = unreal.AtlasVariantValue()
    zero.set_editor_property("value_type", unreal.AtlasVariantValueType.INT32)
    definition.set_editor_property("default_value", zero)
    definition.set_editor_property("display_name", "Collected pickups")
    definition.set_editor_property("description", "Counts committed actor pickups, not interaction attempts or individual stack units.")
    schema.set_editor_property("definitions", [definition])
    defaults = unreal.get_default_object(quest.generated_class())
    defaults.set_editor_property("display_name", "Pick up the sample weapon")
    defaults.set_editor_property("description", "Press E at the pickup. Completion comes from a successful inventory transfer.")
    defaults.set_editor_property("requires_explicit_acceptance", False)
    if new_quest:
        helper = unreal.get_default_object(unreal.load_class(None, "/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary"))
        outcome = helper.call_method("AddPlaygroundQuestObjective", (quest, event_tag))
        failure = outcome[-1] if isinstance(outcome, tuple) else outcome
        if str(failure):
            raise RuntimeError("Quest objective authoring failed: " + str(failure))
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    for cls, name in [(unreal.AtlasStatisticsComponent, "Statistics"), (unreal.AtlasQuestManagerComponent, "Quests")]:
        handles = sub.k2_gather_subobject_data_for_blueprint(owner)
        if any(isinstance(lib.get_object_for_blueprint(lib.get_data(h), owner), cls) for h in handles):
            raise RuntimeError("Progress component already exists: " + name)
        handle, error = sub.add_new_subobject(unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=cls, blueprint_context=owner))
        if str(error):
            raise RuntimeError(str(error))
        sub.rename_subobject(handle, name)
        obj = lib.get_object_for_blueprint(lib.get_data(handle), owner)
        obj.set_editor_property("replicates", True)
        if name == "Statistics":
            obj.set_editor_property("base_schema", schema)
    if not E.compile_blueprint(owner):
        raise RuntimeError("Progress component composition does not compile")
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(owner))
    inventory = next(lib.get_object_for_blueprint(lib.get_data(h), owner) for h in sub.k2_gather_subobject_data_for_blueprint(owner) if isinstance(lib.get_object_for_blueprint(lib.get_data(h), owner), unreal.AtlasInventoryManagerComponent))

    def pin(node, name):
        values = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(values) != 1:
            raise RuntimeError("Missing pin " + name + ": " + str([str(P.get_pin_name(p)) for p in E.list_all_pins(node)]))
        return values[0]

    def wire(a, an, b, bn):
        if not P.try_create_connection(pin(a, an), pin(b, bn)):
            raise RuntimeError("Could not connect " + an + " -> " + bn)

    def value(node, name, text):
        if not P.set_pin_value(pin(node, name), text):
            raise RuntimeError("Could not set " + name)

    def action(name):
        choices = [str(a) for a in graph.list_available_nodes([]) if str(a).split('|')[-1] == name]
        if len(choices) != 1:
            raise RuntimeError("Ambiguous graph action " + name + ": " + str(choices))
        return graph.create_node_from_name(choices[0], unreal.Vector2D(0, 0), [])

    begin = graph.find_event_node("ReceiveBeginPlay") or graph.create_node_from_name("AddEvent|EventBeginPlay", unreal.Vector2D(0, 0), [])
    authority = graph.add_call_function_node("/Script/Engine.Actor:HasAuthority")
    branch = graph.add_branch_node()
    quests = graph.add_get_member_variable_node("Quests")
    start = graph.add_call_function_node("/Script/AtlasQuestSystemRuntime.AtlasQuestManagerComponent:StartQuest")
    value(start, "Definition", unreal.get_default_object(quest.generated_class()).get_path_name())
    wire(begin, "then", branch, "execute")
    wire(authority, "ReturnValue", branch, "Condition")
    wire(branch, "then", start, "execute")
    wire(quests, "Quests", start, "self")
    event = graph.add_component_bound_event_node(inventory, "OnActorPickupCommitted")
    committed = action("BreakAtlasActorPickupCommittedMessage")
    wire(event, "Message", committed, "AtlasActorPickupCommittedMessage")
    stats = graph.add_get_member_variable_node("Statistics")
    add = graph.add_call_function_node("/Script/AtlasStatisticsSystemRuntime.AtlasStatisticsComponent:AddInt32")
    wire(event, "then", add, "execute")
    wire(stats, "Statistics", add, "self")
    value(add, "Key", key.export_text())
    value(add, "Delta", "1")
    fact = action("MakeAtlasProgressEvent")
    value(fact, "EventTag", event_tag.export_text())
    value(fact, "Magnitude", "1.0")
    wire(committed, "RequestId", fact, "CorrelationId")
    submit = graph.add_call_function_node("/Script/AtlasQuestSystemRuntime.AtlasQuestManagerComponent:SubmitProgressEvent")
    wire(quests, "Quests", submit, "self")
    wire(add, "then", submit, "execute")
    wire(fact, "AtlasProgressEvent", submit, "ProgressEvent")
    # The event comes from the inventory owner's committed server mutation, never from a client RPC.
    for node, x, y in [(begin,0,0),(authority,0,160),(branch,260,0),(quests,280,180),(start,600,0),(event,0,450),(committed,0,680),(stats,280,540),(add,540,450),(fact,540,750),(submit,920,450)]:
        E.set_node_pos(node, unreal.IntPoint(x,y))
    if not E.compile_blueprint(owner):
        raise RuntimeError("Pickup progress graph does not compile")
    return [schema, quest]


def add_progress_hud(hud):
    """Show the sample's live pickup counter; keep the graph editable and guarded before possession."""
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(hud))
    old = [n for n in graph.list_all_nodes() if any(str(P.get_pin_name(p)) == 'Text' for p in E.list_all_pins(n))]
    if len(old) != 1:
        raise RuntimeError("Expected the untouched one-line instruction HUD")
    def pin(node, name):
        return next(p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name)
    def wire(a, an, b, bn):
        if not P.try_create_connection(pin(a, an), pin(b, bn)):
            raise RuntimeError("HUD connection failed: " + an + " -> " + bn)
    def value(node, name, text):
        if not P.set_pin_value(pin(node, name), text):
            raise RuntimeError("HUD default failed: " + name)
    owner = graph.add_call_function_node('/Script/Engine.HUD:GetOwningPlayerController')
    stats = graph.add_call_function_node('/Script/AtlasStatisticsSystemRuntime.AtlasStatisticsComponent:FindStatisticsComponent')
    valid = graph.add_call_function_node('/Script/Engine.KismetSystemLibrary:IsValid')
    branch = graph.add_branch_node()
    count = graph.add_call_function_node('/Script/AtlasStatisticsSystemRuntime.AtlasStatisticsComponent:GetInt32')
    string = graph.add_call_function_node('/Script/Engine.KismetStringLibrary:Conv_IntToString')
    text = graph.add_call_function_node('/Script/Engine.KismetStringLibrary:Concat_StrStr')
    draw = graph.add_call_function_node('/Script/Engine.HUD:DrawText')
    wire(owner,'ReturnValue',stats,'Actor');wire(stats,'ReturnValue',valid,'Object');wire(valid,'ReturnValue',branch,'Condition')
    wire(old[0],'then',branch,'execute');wire(branch,'then',draw,'execute')
    wire(stats,'ReturnValue',count,'self');wire(count,'OutValue',string,'InInt');wire(string,'ReturnValue',text,'B');wire(text,'ReturnValue',draw,'Text')
    value(count,'Key','(TagName="Statistics.Example.Pickups")');value(text,'A','Quest: collect one sample item. Pickups: ')
    value(draw,'TextColor','(R=1.0,G=1.0,B=1.0,A=1.0)');value(draw,'ScreenX','24.0');value(draw,'ScreenY','64.0')
    for i,node in enumerate([owner,stats,valid,branch,count,string,text,draw]):
        E.set_node_pos(node,unreal.IntPoint(i*240,400 if i<4 else 700))
    if not E.compile_blueprint(hud):
        raise RuntimeError("Live progress HUD does not compile")


def create_playground(folder="/Game/AtlasExamples/Playground"):
    if not unreal.SystemLibrary.is_unattended():
        raise RuntimeError("Generate from a fresh unattended editor; the recipe changes the current map.")
    if unreal.EditorAssetLibrary.does_directory_have_assets(folder):
        raise FileExistsError("Choose an empty destination; existing examples are retained.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    assets = []

    def tag(name):
        value = unreal.GameplayTag()
        if not value.import_text('(TagName="' + name + '")'):
            raise RuntimeError("Missing public tag: " + name)
        return value

    def create(name, cls, factory=None):
        if factory is None:
            factory = unreal.DataAssetFactory()
            factory.set_editor_property("data_asset_class", cls)
        asset = tools.create_asset(name, folder, cls, factory)
        if asset is None:
            raise RuntimeError("Could not create " + name)
        assets.append(asset)
        return asset

    def blueprint(name, parent):
        factory = unreal.BlueprintFactory()
        factory.set_editor_property("parent_class", parent)
        return create(name, unreal.Blueprint, factory)

    def component(bp, cls, name, parent=None):
        handles = sub.k2_gather_subobject_data_for_blueprint(bp)
        args = unreal.AddNewSubobjectParams()
        args.set_editor_property("parent_handle", parent or handles[0])
        args.set_editor_property("new_class", cls)
        args.set_editor_property("blueprint_context", bp)
        handle, error = sub.add_new_subobject(args)
        if str(error):
            raise RuntimeError("Cannot add " + name + ": " + str(error))
        sub.rename_subobject(handle, name)
        obj = lib.get_object_for_blueprint(lib.get_data(handle), bp)
        if obj is None:
            raise RuntimeError("Cannot edit component template " + name)
        return handle, obj

    def find_handle(bp, name):
        for handle in sub.k2_gather_subobject_data_for_blueprint(bp):
            obj = lib.get_object_for_blueprint(lib.get_data(handle), bp)
            if obj and obj.get_name().removesuffix("_GEN_VARIABLE") == name:
                return handle
        raise RuntimeError("Missing component: " + name)

    def cube_component(bp, name, scale, location=(0, 0, 0), parent=None):
        handle, mesh = component(bp, unreal.StaticMeshComponent, name, parent)
        mesh.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
        mesh.set_editor_property("relative_scale3d", unreal.Vector(*scale))
        mesh.set_editor_property("relative_location", unreal.Vector(*location))
        mesh.set_collision_profile_name("NoCollision")
        return handle, mesh

    helper = unreal.load_class(None, "/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary")
    if helper is None:
        raise RuntimeError("Public AtlasContentEditor authoring module is unavailable.")
    result = unreal.get_default_object(helper).call_method("CreatePlaygroundGraphs", args=(folder,))
    if len(result) == 4:
        success, *result = result
        if not success:
            raise RuntimeError("Playground graph generation failed: " + str(result[-1]))
    controller, hud, failure = result
    if controller is None or hud is None or str(failure):
        raise RuntimeError("Controller/HUD graph generation failed: " + str(failure))
    assets.extend([controller, hud])
    pawn = blueprint("BP_PlaygroundCharacter", unreal.AtlasModularCharacter)
    cube_component(pawn, "Body", (0.45, 0.45, 1.4))
    _, asc = component(pawn, unreal.AtlasAbilitySystemComponent, "AbilitySystem")
    asc.set_editor_property("replicates", True)
    component(pawn, unreal.AtlasPawnExtensionComponent, "PawnExtension")
    component(pawn, unreal.AtlasAbilityExecutionComponent, "AbilityExecution")
    component(pawn, unreal.AtlasCombatActionStateComponent, "CombatActionState")
    component(controller, unreal.AtlasInventoryManagerComponent, "Inventory")
    _, container = component(controller, unreal.AtlasMainInventoryContainerComponent, "Backpack")
    container.set_editor_property("initial_contents_mode", unreal.AtlasContainerInitialContentsMode.EMPTY)
    _, equipment = component(pawn, unreal.AtlasPlayerEquipmentComponent, "Equipment")
    _, mount = component(pawn, unreal.SceneComponent, "EquipmentMount")
    mount.set_editor_property("component_tags", ["EquipmentMount"])
    mount.set_editor_property("relative_location", unreal.Vector(30, 30, 30))
    arm_handle, arm = component(pawn, unreal.SpringArmComponent, "CameraArm")
    arm.set_editor_property("target_arm_length", 300.0)
    arm.set_editor_property("use_pawn_control_rotation", True)
    arm.set_editor_property("relative_location", unreal.Vector(0, 0, 64))
    component(pawn, unreal.CameraComponent, "Camera", arm_handle)

    weapon_actor = blueprint("BP_PlaygroundWeapon", unreal.AtlasEquipmentActor)
    cube_component(weapon_actor, "WorldShape", (0.6, 0.12, 0.12), (20, 0, 0), find_handle(weapon_actor, "WorldView"))
    cube_component(weapon_actor, "FirstPersonShape", (0.6, 0.12, 0.12), (20, 0, 0), find_handle(weapon_actor, "FirstPersonView"))
    weapon = create("DA_PlaygroundWeapon", unreal.AtlasEquipmentDefinition, unreal.AtlasHitscanEquipmentTemplateFactory())
    spawn = unreal.AtlasEquipmentActorToSpawn()
    spawn.set_editor_property("actor_class", weapon_actor.generated_class())
    spawn.set_editor_property("attachment_source", unreal.AtlasEquipmentAttachmentSource.SPAWN_RULE)
    spawn.set_editor_property("attachment_role", "MainHand")
    weapon.set_editor_property("spawn_actor_rules", [spawn])
    profile = create("DA_PlaygroundEquipmentRig", unreal.AtlasEquipmentPresentationProfile, unreal.AtlasEquipmentPresentationProfileFactory())
    profile.set_editor_property("animation_free", True)
    profile.set_editor_property("rig_id", "Atlas.Playground")
    mount_rule = unreal.AtlasEquipmentPresentationAttachment()
    mount_rule.set_editor_property("role", "MainHand")
    mount_rule.set_editor_property("component_tag", "EquipmentMount")
    profile.set_editor_property("attachments", [mount_rule])
    equipment.set_editor_property("presentation_profile", profile)
    fallback = unreal.AtlasFallbackEquipmentEntry()
    fallback.set_editor_property("equipment_definition", weapon)
    fallback.set_editor_property("slot_tag", tag("Inventory.Equipment.Slot.Primary"))
    equipment.set_editor_property("fallback_equipment", [fallback])
    rule = unreal.AtlasEquipmentSlotRule()
    rule.set_editor_property("slot_tag", tag("Inventory.Equipment.Slot.Primary"))
    equipment.set_editor_property("equipment_slot_rules", [rule])

    ingredient = create("DA_PlaygroundIngredient", unreal.AtlasInventoryItemDefinition)
    ingredient.set_editor_property("display_name", "Sample weapon")
    equippable = unreal.new_object(unreal.InventoryFragment_Equippable, outer=ingredient)
    equippable.set_editor_property("equipment_definition", weapon)
    slotted = unreal.new_object(unreal.AtlasInventoryFragment_WorldSlotted, outer=ingredient)
    slotted.set_editor_property("slot_tag", tag("Interaction.Item.WorldSlotted.Example"))
    slotted.set_editor_property("additive_transform", unreal.Transform(scale=unreal.Vector(0.35, 0.35, 0.35)))
    visual = unreal.new_object(unreal.InventoryFragment_WorldActor, outer=ingredient)
    visual.set_editor_property("static_mesh", unreal.load_asset("/Engine/BasicShapes/Cube"))
    ingredient.set_editor_property("fragments", [equippable, slotted, visual])
    pickup = blueprint("BP_IngredientPickup", unreal.AtlasInteractiveWorldCollectable)
    seed = unreal.AtlasContainerInitialItem()
    seed.set_editor_property("item_definition", ingredient)
    seed.set_editor_property("stack_count", 1)
    defaults = unreal.get_default_object(pickup.generated_class())
    single = defaults.get_component_by_class(unreal.AtlasInventorySingleItemContainerComponent)
    single.set_editor_property("initial_contents_mode", unreal.AtlasContainerInitialContentsMode.AUTHORED_ITEMS)
    single.set_editor_property("initial_item", seed)
    option = create("IO_PlaygroundPickup", unreal.AtlasInteractionOption)
    option.set_editor_property("default_display_text", "Pick up sample item")
    execution = option.get_editor_property("execution")
    if not execution.import_text('/Script/AtlasInteraction.AtlasInteractionActionExecution(Endpoint=Target,Action=(TagName="Interaction.Operation.Inventory.Pickup"))'):
        raise RuntimeError("Public pickup action is unavailable")
    option.set_editor_property("execution", execution)
    interactions = create("IP_PlaygroundPickup", unreal.AtlasInteractionProfile)
    interactions.set_editor_property("options", [option])
    defaults.get_component_by_class(unreal.AtlasInteractionTargetComponent).set_editor_property("interaction_profile", interactions)
    _, pickup_shape = cube_component(pickup, "PickupShape", (0.35, 0.35, 0.35))
    pickup_shape.set_collision_profile_name("BlockAllDynamic")
    rack_slot = blueprint("BP_ItemRackSlot", unreal.AtlasWorldEquipmentSlot)
    _, slot_shape = cube_component(rack_slot, "SlotShape", (0.4, 0.4, 0.1), (0, 0, -25))
    slot_shape.set_collision_profile_name("BlockAllDynamic")
    rack_options = []
    for action in ("Take", "Put"):
        rack_option = create("IO_Rack" + action, unreal.AtlasInteractionOption)
        rack_option.set_editor_property("default_display_text", action + " sample item")
        execution = rack_option.get_editor_property("execution")
        if not execution.import_text('/Script/AtlasInteraction.AtlasInteractionActionExecution(Endpoint=Target,Action=(TagName="Interaction.Operation.Inventory.' + action + '"))'):
            raise RuntimeError("Public rack action is unavailable: " + action)
        rack_option.set_editor_property("execution", execution)
        rack_options.append(rack_option)
    rack_interactions = create("IP_ItemRack", unreal.AtlasInteractionProfile)
    rack_interactions.set_editor_property("options", rack_options)
    unreal.get_default_object(rack_slot.generated_class()).get_component_by_class(unreal.AtlasInteractionTargetComponent).set_editor_property("interaction_profile", rack_interactions)
    rack_layout = create("DA_ItemRackLayout", unreal.AtlasWorldEquipmentLayout)
    rack_layout.set_editor_property("slot_class", rack_slot.generated_class())
    places = []
    for index, slot_id in enumerate(("Left", "Right")):
        place = unreal.AtlasWorldEquipmentPlace()
        place.set_editor_property("slot_id", slot_id)
        place.set_editor_property("transform", unreal.Transform(location=unreal.Vector(0, index * 65, 0)))
        accepted = unreal.GameplayTagContainer()
        if not accepted.import_text('(GameplayTags=((TagName="Interaction.Item.WorldSlotted.Example")))'):
            raise RuntimeError("Install the public rack example tag")
        place.set_editor_property("accepted_item_tags", accepted)
        places.append(place)
    rack_layout.set_editor_property("slots", places)
    rack = blueprint("BP_ItemRack", unreal.AtlasWorldEquipmentPad)
    unreal.get_default_object(rack.generated_class()).set_editor_property("layout", rack_layout)
    npc = unreal.AtlasNPCAuthoringLibrary.create_npc_assets(folder, "PlaygroundTarget", unreal.AtlasNPCMovementPreset.GROUND, False)
    if not npc.get_editor_property("success"):
        raise RuntimeError(str(npc.get_editor_property("errors")))
    for name in ("blueprint", "definition", "state_tree"):
        assets.append(npc.get_editor_property(name))
    npc_bp = npc.get_editor_property("blueprint")
    _, target_shape = cube_component(npc_bp, "TargetShape", (0.6, 0.6, 1.6))
    target_shape.set_collision_profile_name("BlockAllDynamic")
    add_npc_loot(npc_bp, pickup.generated_class(), ingredient)
    assets.extend(add_pickup_progress(controller, folder))
    add_progress_hud(hud)

    game_mode = blueprint("BP_PlaygroundGameMode", unreal.AtlasGameplayGameModeBase)
    mode_defaults = unreal.get_default_object(game_mode.generated_class())
    mode_defaults.set_editor_property("player_controller_class", controller.generated_class())
    mode_defaults.set_editor_property("hud_class", hud.generated_class())
    mode_defaults.set_editor_property("default_pawn_class", pawn.generated_class())
    unreal.get_default_object(pawn.generated_class()).set_editor_property("use_controller_rotation_yaw", True)
    experience = create("DA_PlaygroundExperience", unreal.AtlasGameplayExperienceDefinition, unreal.AtlasGameplayExperienceDefinitionFactory())
    experience.set_editor_property("display_name", "Atlas public gameplay playground")
    setup = unreal.new_object(unreal.PawnSetupFragment, outer=experience)
    setup.set_editor_property("default_pawn_class", pawn.generated_class())
    experience.set_editor_property("fragments", [setup])

    for asset in assets:
        if isinstance(asset, unreal.Blueprint) and not unreal.BlueprintEditorLibrary.compile_blueprint(asset):
            raise RuntimeError("Blueprint compilation failed: " + asset.get_path_name())
    world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
    settings = world.get_world_settings()
    if settings.get_class().get_path_name() != "/Script/AtlasGameplayExperienceFrameworkRuntime.AtlasGameplayWorldSettings":
        raise RuntimeError("Select public AtlasGameplayWorldSettings for new maps before running the recipe.")
    settings.set_editor_property("default_game_mode", game_mode.generated_class())
    identity = unreal.PrimaryAssetId()
    stable_id = str(experience.get_editor_property("experience_id"))
    if stable_id in ("", "None") or not identity.import_text("AtlasGameplayExperience:" + stable_id):
        raise RuntimeError("Experience factory did not produce a valid identity")
    settings.set_editor_property("default_experience_id", identity)
    actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    ground = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(500, 0, -60))
    ground.get_editor_property("static_mesh_component").set_static_mesh(unreal.load_asset("/Engine/BasicShapes/Cube"))
    ground.set_actor_scale3d(unreal.Vector(40, 40, 1))
    actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0, 0, 900), unreal.Rotator(-50, 0, 0))
    actors.spawn_actor_from_class(unreal.SkyLight, unreal.Vector(0, 0, 800))
    actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 0, 100))
    actors.spawn_actor_from_class(unreal.PlayerStart, unreal.Vector(0, 250, 100))
    actors.spawn_actor_from_class(pickup.generated_class(), unreal.Vector(200, -160, 30))
    actors.spawn_actor_from_class(rack.generated_class(), unreal.Vector(350, -260, 60))
    actors.spawn_actor_from_class(npc_bp.generated_class(), unreal.Vector(800, 0, 110))
    nav = actors.spawn_actor_from_class(unreal.NavMeshBoundsVolume, unreal.Vector(500, 0, 150))
    nav.set_actor_scale3d(unreal.Vector(25, 25, 5))
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Save failed: " + asset.get_path_name())
    map_path = folder + "/L_Playground"
    if not unreal.EditorLoadingAndSavingUtils.save_map(world, map_path):
        raise RuntimeError("Map save failed")
    return {"Map": map_path, "Experience": identity.export_text(), "Assets": [asset.get_path_name() for asset in assets]}


if __name__ == "__main__":
    report = create_playground()
    out = Path(unreal.Paths.project_saved_dir()) / "ModKitPlayground"
    out.mkdir(parents=True, exist_ok=True)
    (out / "creation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
