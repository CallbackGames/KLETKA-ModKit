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
    factory.set_editor_property("parent_class", unreal.AtlasGameplayAbility)
    ability = tools.create_asset("GA_ExampleCurse", folder, unreal.Blueprint, factory)
    if ability is None:
        raise RuntimeError("Could not create the curse ability.")
    assets.append(ability)
    effect_factory = unreal.BlueprintFactory()
    effect_factory.set_editor_property("parent_class", unreal.GameplayEffect)
    effect = tools.create_asset("GE_ExampleCurseDamage", folder, unreal.Blueprint, effect_factory)
    if not effect or not unreal.BlueprintEditorLibrary.compile_blueprint(effect):
        raise RuntimeError("Could not create curse GameplayEffect.")
    modifier = unreal.GameplayModifierInfo()
    # This owner attribute and serialized form are shared with the canonical NPC damage example.
    if not modifier.import_text('(Attribute=(AttributeName="Damage",Attribute=/Script/AtlasAbilitiesSystemRuntime.AtlasHealthSet:Damage,AttributeOwner="/Script/CoreUObject.Class\'/Script/AtlasAbilitiesSystemRuntime.AtlasHealthSet\'"),ModifierOp=AddBase,ModifierMagnitude=(MagnitudeCalculationType=ScalableFloat,ScalableFloatMagnitude=(Value=10.0)))'):
        raise RuntimeError("The public health damage attribute is unavailable.")
    effect_defaults = unreal.get_default_object(effect.generated_class())
    effect_defaults.set_editor_property("duration_policy", unreal.GameplayEffectDurationType.INSTANT)
    effect_defaults.set_editor_property("modifiers", [modifier])
    assets.append(effect)
    graph_spec = importlib.util.spec_from_file_location("_curse_graph_writer", Path(__file__).with_name("EntityModStarter.py"))
    graph_recipe = importlib.util.module_from_spec(graph_spec)
    graph_spec.loader.exec_module(graph_recipe)
    author_damage_curse(ability, effect, graph_recipe.ExampleGraph)
    defaults = unreal.get_default_object(ability.generated_class())
    defaults.set_editor_property("activation_policy", unreal.AtlasAbilityActivationPolicy.ON_SPAWN)
    defaults.set_editor_property("net_execution_policy", unreal.GameplayAbilityNetExecutionPolicy.SERVER_ONLY)
    curse = data("DA_ExampleCurse", unreal.LeFloorCursePrankDataAsset)
    curse.set_editor_property("prank_class", ability.generated_class())
    curse.set_editor_property("display_name", "Example curse")
    curse.set_editor_property("display_description", "Deals 10 GAS damage once to each current player pawn when this floor curse activates on the server, then ends.")
    curse.set_editor_property("min_cage_regular_stops", 0)
    config = curse.get_editor_property("spawn_config")
    config.set_editor_property("spawn_chance", 100.0)
    config.set_editor_property("max_spawn_chance", 100.0)
    curse.set_editor_property("spawn_config", config)
    action = list(feature.get_editor_property("actions"))[0]
    events = unreal.new_object(unreal.LeFloorContentBlock_Pranks, outer=action)
    events.set_editor_property("pranks", [curse])
    action.set_editor_property("content_blocks", list(action.get_editor_property("content_blocks")) + [events])
    fragment = unreal.new_object(unreal.LeFloorCursePrankFragment, outer=floor)
    fragment.set_editor_property("activation_chance", 100.0)
    fragment.set_editor_property("maximum_activation_chance", 100.0)
    fragment.set_editor_property("chance_added_at_max_biome_progress", 0.0)
    entry = unreal.LeWeightedPrankReference()
    # AssetManager has not registered this new feature yet; preserve the authored stable ID.
    prank_id = recipe.authored_primary_asset_id(curse, "Prank")
    entry.set_editor_property("prank_id", prank_id)
    fragment.set_editor_property("pranks", [entry])
    floor.set_editor_property("fragments", list(floor.get_editor_property("fragments")) + [fragment])
    scan = unreal.PrimaryAssetTypeInfo()
    scan.set_editor_property("primary_asset_type", "Prank")
    scan.set_editor_property("asset_base_class", unreal.LeFloorPrankDataAssetBase)
    scan.set_editor_property("specific_assets", [unreal.SoftObjectPath(curse.get_path_name())])
    feature.set_editor_property("primary_asset_types_to_scan", list(feature.get_editor_property("primary_asset_types_to_scan")) + [scan])

    for asset in assets + [floor, feature]:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    result["content_assets"] = [a.get_path_name() for a in assets]
    result["assets"] = list(dict.fromkeys(result["assets"] + result["content_assets"]))
    return result


def author_damage_curse(ability, effect, graph_class):
    g = graph_class(ability)
    activate = g.event("K2_ActivateAbility")
    players = g.call("/Script/Engine.GameplayStatics:GetAllActorsOfClass")
    g.value(players, "ActorClass", "/Script/Engine.PlayerState")
    g.link(activate, "then", players, "execute")
    macros = unreal.load_asset("/Engine/EditorBlueprintResources/StandardMacros")
    loop_graph = unreal.BlueprintEditorLibrary.find_graph(macros, "ForEachLoop")
    if not loop_graph:
        raise RuntimeError("Engine ForEachLoop macro unavailable.")
    loop = g.graph.add_macro_node(loop_graph.get_path_name())
    g.link(players, "then", loop, "Exec")
    g.link(players, "OutActors", loop, "Array")
    pawn = g.call("/Script/Engine.PlayerState:GetPawn")
    g.link(loop, "Array Element", pawn, "self")
    asc = g.call("/Script/GameplayAbilities.AbilitySystemBlueprintLibrary:GetAbilitySystemComponent")
    g.link(pawn, "ReturnValue", asc, "Actor")
    valid = g.call("/Script/Engine.KismetSystemLibrary:IsValid")
    g.link(asc, "ReturnValue", valid, "Object")
    gate = g.branch(loop, valid, route="LoopBody")
    context = g.call("/Script/GameplayAbilities.AbilitySystemComponent:MakeEffectContext")
    g.link(asc, "ReturnValue", context, "self")
    apply = g.call("/Script/GameplayAbilities.AbilitySystemComponent:BP_ApplyGameplayEffectToSelf")
    g.link(gate, "then", apply, "execute")
    g.link(asc, "ReturnValue", apply, "self")
    g.link(context, "ReturnValue", apply, "EffectContext")
    g.value(apply, "GameplayEffectClass", effect.generated_class().get_path_name())
    g.value(apply, "Level", "1.0")
    end = g.call("/Script/GameplayAbilities.GameplayAbility:K2_EndAbility")
    g.link(loop, "Completed", end, "execute")
    g.graph.add_comment_node("Server-only instantaneous curse: 10 damage through the pawn's canonical health GAS attribute. Iterate player states once, skip unpossessed/no-ASC players, and end after the loop. No ticking effect or restore replay.", unreal.Vector2D(-40, -110), unreal.Vector2D(1800, 100))
    g.compile()
