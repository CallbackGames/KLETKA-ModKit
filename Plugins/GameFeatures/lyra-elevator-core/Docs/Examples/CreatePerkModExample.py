# Copyright Callback LLP. All Rights Reserved.
"""KLETKA sentence-perk starter using the public Roguelike owner contracts.

The generated ability logs activation and ends immediately. Put the perk's gameplay
effect before End Ability. No existing asset, active world or base perk is changed.
"""
import unreal


def populate_template(plugin_name, content_id):
    folder = "/" + plugin_name + "/PerkExample"
    names = ("GA_ExamplePerk", "DA_ExamplePerk")
    if any(unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name) or
           unreal.find_object(None, folder + "/" + name + "." + name) for name in names):
        raise RuntimeError("Perk starter destination already contains assets.")
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if feature is None or list(feature.get_editor_property("actions")):
        raise RuntimeError("Perk starter requires a new empty Game Feature Data.")
    pool = unreal.GameplayTag()
    if not pool.import_text('(TagName="Perk.Pool.Sentence")'):
        raise RuntimeError("The published KLETKA sentence-perk pool is unavailable.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.AtlasGameplayAbility)
    ability = tools.create_asset(names[0], folder, unreal.Blueprint, factory)
    if ability is None:
        raise RuntimeError("Could not create the public ability Blueprint.")
    editor = unreal.BlueprintEditorLibrary
    pins = unreal.BlueprintGraphPin

    def pin(node, name):
        found = [value for value in editor.list_all_pins(node) if str(pins.get_pin_name(value)) == name]
        if len(found) != 1:
            raise RuntimeError("Expected one " + name + " pin on " + node.get_name())
        return found[0]

    # Use the engine's inherited-event API rather than a custom event with the same name.
    event = editor.add_event_override(ability, "K2_ActivateAbility", unreal.IntPoint(0, 0))
    graph = unreal.BlueprintGraphEditor.get_graph_editor_by_name(ability, "EventGraph")
    if event is None or graph is None:
        raise RuntimeError("Could not create the ability activation event.")
    log = graph.add_call_function_node("/Script/Engine.KismetSystemLibrary:PrintString")
    end = graph.add_call_function_node("/Script/GameplayAbilities.GameplayAbility:K2_EndAbility")
    if log is None or end is None:
        raise RuntimeError("The public activation example functions are unavailable.")
    if not pins.set_pin_value(pin(log, "InString"), "Example perk activated. Add gameplay before End Ability."):
        raise RuntimeError("Could not set the activation diagnostic.")
    if not pins.set_pin_value(pin(log, "bPrintToScreen"), "false"):
        raise RuntimeError("Could not disable the player-facing diagnostic.")
    if not pins.try_create_connection(pin(event, "then"), pin(log, "execute")) or \
            not pins.try_create_connection(pin(log, "then"), pin(end, "execute")):
        raise RuntimeError("Could not connect the ability lifecycle.")
    graph.add_comment_node("Replace this diagnostic with your perk effect; keep a deliberate End Ability path.",
                           unreal.Vector2D(-30, -90), unreal.Vector2D(850, 270))
    fixed = unreal.get_default_object(unreal.load_class(None, '/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary')).call_method('EnsureExampleNodeIds', (ability,))
    if fixed is None or fixed[-1]:
        raise RuntimeError("Invalid perk graph identities: " + str(fixed))
    if not editor.compile_blueprint(ability):
        raise RuntimeError("Perk ability Blueprint does not compile.")
    defaults = unreal.get_default_object(ability.generated_class())
    defaults.set_editor_property("activation_policy", unreal.AtlasAbilityActivationPolicy.ON_SPAWN)
    defaults.set_editor_property("net_execution_policy", unreal.GameplayAbilityNetExecutionPolicy.SERVER_ONLY)

    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.RoguelikePerkDefinition)
    perk = tools.create_asset(names[1], folder, unreal.RoguelikePerkDefinition, factory)
    if perk is None:
        raise RuntimeError("Could not create the perk definition.")
    presentation = unreal.new_object(unreal.RoguelikePerkPresentationFragment, outer=perk)
    presentation.set_editor_property("display_name", "Example perk")
    presentation.set_editor_property("description", "Starter perk: logs activation and ends. Author its gameplay in GA_ExamplePerk.")
    grant = unreal.new_object(unreal.RoguelikePerkAbilityFragment, outer=perk)
    grant.set_editor_property("gameplay_ability", ability.generated_class())
    perk.set_editor_property("fragments", [presentation, grant])
    contribution = unreal.RoguelikePerkContribution()
    contribution.set_editor_property("pool", pool)
    contribution.set_editor_property("definition", perk)
    # The owner generates the rule ID and perk ID. Do not copy IDs from another mod.
    action = unreal.new_object(unreal.RoguelikeGameFeatureAction_AddPerkContent, outer=feature)
    action.set_editor_property("entries", [contribution])
    feature.set_editor_property("actions", [action])
    for asset in (ability, perk, feature):
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {"plugin": plugin_name, "id": content_id,
            "assets": [asset.get_path_name() for asset in (ability, perk, feature)],
            "pool": "Perk.Pool.Sentence"}
