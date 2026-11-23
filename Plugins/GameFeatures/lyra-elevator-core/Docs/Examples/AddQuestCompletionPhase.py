# Copyright Callback LLP. All Rights Reserved.
"""Add an optional game-phase request to a quest's real completion. Leaves the Blueprint unsaved for review."""
import unreal


def configure_completion(quest, phase_tag="Phase.Win"):
    E, P = unreal.BlueprintEditorLibrary, unreal.BlueprintGraphPin
    if not isinstance(quest, unreal.Blueprint) or not isinstance(unreal.get_default_object(quest.generated_class()), unreal.AtlasQuestDefinition):
        raise TypeError("Choose an editable Quest Definition Blueprint.")
    tag = unreal.GameplayTag()
    if not tag.import_text('(TagName="' + phase_tag + '")') or not unreal.GameplayTagLibrary.is_gameplay_tag_valid(tag):
        raise ValueError("Choose a declared game phase tag.")
    graph = unreal.BlueprintGraphEditor.get_graph_editor(E.find_event_graph(quest))
    if any("quest deactivated" in E.get_node_title(n).lower() or "onquestdeactivated" in E.get_node_title(n).lower() for n in graph.list_all_nodes()):
        raise ValueError("This quest already handles deactivation. Integrate the phase request into that existing graph instead of replacing it.")
    choices = [str(a) for a in graph.list_available_nodes([])]
    switch = [a for a in choices if "switch" in a.lower() and "atlasactioncancellationreason" in a.lower().replace(" ", "")]
    if len(switch) != 1 or "WorldSubsystems|GetAtlasGamePhaseSubsystem" not in choices:
        raise RuntimeError("The public quest reason switch or gameplay phase subsystem is unavailable.")

    def pin(node, name):
        matches = [p for p in E.list_all_pins(node) if str(P.get_pin_name(p)) == name]
        if len(matches) != 1:
            raise RuntimeError("Missing Blueprint pin " + node.get_name() + "." + name)
        return matches[0]

    def link(a, an, b, bn):
        if not P.try_create_connection(pin(a, an), pin(b, bn)):
            raise RuntimeError("Could not connect " + an + " -> " + bn)

    event = E.add_event_override(quest, "OnQuestDeactivated", unreal.IntPoint(0, 0))
    reason = graph.create_node_from_name(switch[0], unreal.Vector2D(250, 0), [])
    manager = graph.add_call_function_node("/Script/AtlasQuestSystemRuntime.AtlasQuestDefinition:GetRuntimeQuestManager")
    owner = graph.add_call_function_node("/Script/Engine.ActorComponent:GetOwner")
    authority = graph.add_call_function_node("/Script/Engine.Actor:HasAuthority")
    branch = graph.add_branch_node()
    phases = graph.create_node_from_name("WorldSubsystems|GetAtlasGamePhaseSubsystem", unreal.Vector2D(520, 260), [])
    start = graph.add_call_function_node("/Script/AtlasGameplayPhaseFrameworkRuntime.AtlasGamePhaseSubsystem:K2_TryStartConfiguredPhase")
    E.set_node_pos(manager, unreal.IntPoint(0, 350)); E.set_node_pos(owner, unreal.IntPoint(250, 350))
    E.set_node_pos(authority, unreal.IntPoint(500, 350)); E.set_node_pos(branch, unreal.IntPoint(520, 0))
    E.set_node_pos(start, unreal.IntPoint(800, 0))
    link(event, "then", reason, "execute"); link(event, "Reason", reason, "Selection")
    link(reason, "QuestCompleted", branch, "execute")
    link(manager, "ReturnValue", owner, "self"); link(owner, "ReturnValue", authority, "self")
    link(authority, "ReturnValue", branch, "Condition")
    link(manager, "ReturnValue", phases, "WorldContext")
    link(branch, "then", start, "execute"); link(phases, "ReturnValue", start, "self")
    if not P.set_pin_value(pin(start, "PhaseTag"), tag.export_text()):
        raise RuntimeError("Could not set the phase tag.")
    graph.add_comment_to_nodes("Only real quest completion on authority requests the configured game phase. Restore, abandon and failure do not replay it. Inspect the start result; never retry recursively.", [event, reason, manager, owner, authority, branch, phases, start])
    fixed = unreal.get_default_object(unreal.load_class(None, '/Script/AtlasContentEditor.AtlasPlaygroundAuthoringLibrary')).call_method('EnsureExampleNodeIds', (quest,))
    if fixed is None or fixed[-1]:
        raise RuntimeError("Invalid quest graph identities: " + str(fixed))
    if not E.compile_blueprint(quest):
        raise RuntimeError("Quest completion graph did not compile; inspect the retained unsaved draft.")
    return quest
