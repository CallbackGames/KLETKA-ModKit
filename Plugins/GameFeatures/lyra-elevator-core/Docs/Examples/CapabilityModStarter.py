# Copyright Callback LLP. All Rights Reserved.
"""Playable examples composed from the canonical public owners and the floor recipe."""
import importlib.util
from pathlib import Path
import unreal


def owner_recipe():
    spec = importlib.util.spec_from_file_location('_capability_entity', Path(__file__).with_name('EntityModStarter.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def component(blueprint, cls, name):
    subsystem = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    library = unreal.SubobjectDataBlueprintFunctionLibrary
    handles = subsystem.k2_gather_subobject_data_for_blueprint(blueprint)
    handle, error = subsystem.add_new_subobject(unreal.AddNewSubobjectParams(
        parent_handle=handles[0], new_class=cls, blueprint_context=blueprint))
    if str(error):
        raise RuntimeError(str(error))
    subsystem.rename_subobject(handle, name)
    return library.get_object_for_blueprint(library.get_data(handle), blueprint)


def tag(name):
    value = unreal.GameplayTag()
    if not value.import_text('(TagName="' + name + '")'):
        raise RuntimeError('Missing public tag: ' + name)
    return value


def finish(result, assets):
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError('Could not save ' + asset.get_path_name())
    result['assets'] = list(dict.fromkeys(result['assets'] + [a.get_path_name() for a in assets]))
    return result


def base(plugin_name, content_id):
    recipe = owner_recipe()
    result = recipe.populate_entity(plugin_name, content_id, 'WorldActor')
    actor = unreal.load_asset('/' + plugin_name + '/EntityExample/BP_ExampleWorldActor')
    feature = unreal.load_asset('/' + plugin_name + '/' + plugin_name)
    return recipe, result, actor, feature


def populate_cage(plugin_name, content_id):
    _, result, actor, feature = base(plugin_name, content_id)
    defaults = unreal.get_default_object(actor.generated_class())
    defaults.set_editor_property('always_relevant', True)
    target = unreal.LeCageDeviceContentLibrary.get_device_addon_target(unreal.LeCageDeviceSite.SCANNER)
    if not target:
        raise RuntimeError('The public scanner addon target is unavailable.')
    rule = unreal.AtlasActorPlacementRule()
    rule.set_editor_property('target_placement_id', target[0])
    rule.set_editor_property('operation', unreal.AtlasActorPlacementOperation.ADD)
    rule.set_editor_property('actor_class', actor.generated_class())
    action = unreal.new_object(unreal.AtlasGameFeatureAction_AddActorPlacements, outer=feature)
    action.set_editor_property('rules', [rule])
    feature.set_editor_property('actions', list(feature.get_editor_property('actions')) + [action])
    result['device_target'] = str(target[0])
    return finish(result, [actor, feature])


def populate_progression(plugin_name, content_id):
    recipe, result, actor, feature = base(plugin_name, content_id)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataAssetFactory()
    factory.set_editor_property('data_asset_class', unreal.AtlasProgressionSchema)
    schema = tools.create_asset('DA_ExampleProgression', '/' + plugin_name + '/ProgressionExample',
                                unreal.AtlasProgressionSchema, factory)
    if not schema:
        raise RuntimeError('Could not create the progression schema.')
    schema.set_editor_property('stable_schema_name', content_id + '.progression')
    schema.set_editor_property('default_scope', unreal.AtlasProgressionScope.INSTANCE)
    cost = unreal.AtlasResourceAmount()
    cost.set_editor_property('resource', tag('Progression.Resource.Points'))
    cost.set_editor_property('amount', 3)
    node = unreal.AtlasProgressionNodeDefinition()
    node.set_editor_property('node_id', 'Training')
    node.set_editor_property('display_name', 'Training rank')
    node.set_editor_property('max_rank', 3)
    node.set_editor_property('costs', [cost])
    schema.set_editor_property('nodes', [node])
    progression = component(actor, unreal.AtlasProgressionComponent, 'Progression')
    progression.set_editor_property('registered_schemas', [schema])
    component(actor, unreal.AtlasProgressionSaveComponent, 'ProgressionSave')
    save = component(actor, unreal.AtlasSavableComponent, 'SaveState')
    save.set_editor_property('persistence_group', 'KLETKA.Run.World')
    trigger = component(actor, unreal.SphereComponent, 'UpgradeRange')
    trigger.set_sphere_radius(180.0)
    trigger.set_collision_enabled(unreal.CollisionEnabled.QUERY_ONLY)
    trigger.set_collision_response_to_all_channels(unreal.CollisionResponseType.ECR_IGNORE)
    trigger.set_collision_response_to_channel(unreal.CollisionChannel.ECC_PAWN, unreal.CollisionResponseType.ECR_OVERLAP)
    trigger.set_editor_property('generate_overlap_events', True)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(actor):
        raise RuntimeError('Progression components did not compile.')
    g = recipe.ExampleGraph(actor)
    owner = g.member('Progression')
    save_node = g.member('SaveState')
    identity = g.call('/Script/AtlasSaveGameFrameworkRuntime.AtlasSavableComponent:GetPersistentId')
    g.link(save_node, 'SaveState', identity, 'self')
    subject = g.action('MakeAtlasSubjectHandle')
    g.value(subject, 'Type', '(TagName="Progression.Subject.Item")')
    g.link(identity, 'ReturnValue', subject, 'InstanceId')
    # AssetManager lookup is unavailable before feature registration. Use this owned
    # schema's authored stable identity; do not turn an early lookup into an empty ID.
    schema_id = unreal.PrimaryAssetId()
    if not schema_id.import_text('AtlasProgressionSchema:' + content_id + '.progression'):
        raise RuntimeError('Could not serialize the authored progression schema identity.')
    schema_literal = schema_id.export_text()
    record = g.call('/Script/AtlasProgressionSystemRuntime.AtlasProgressionComponent:GetProgressionRecord')
    for function in (record,):
        g.link(owner, 'Progression', function, 'self')
        g.link(subject, 'AtlasSubjectHandle', function, 'Subject')
        g.value(function, 'SchemaId', schema_literal)
    authority = g.call('/Script/Engine.Actor:HasAuthority')
    begin = g.event('ReceiveBeginPlay')
    gate = g.branch(begin, authority)
    exists = g.branch(gate, record)
    register = g.call('/Script/AtlasProgressionSystemRuntime.AtlasProgressionComponent:RegisterSubject')
    g.link(exists, 'else', register, 'execute')
    g.link(owner, 'Progression', register, 'self')
    g.link(subject, 'AtlasSubjectHandle', register, 'Subject')
    g.value(register, 'Schema', schema.get_path_name())
    registered = g.branch(register, register)
    fund = g.call('/Script/AtlasProgressionSystemRuntime.AtlasProgressionComponent:AddResource')
    g.link(registered, 'then', fund, 'execute')
    g.link(owner, 'Progression', fund, 'self')
    g.link(subject, 'AtlasSubjectHandle', fund, 'Subject')
    g.value(fund, 'SchemaId', schema_literal)
    g.value(fund, 'Resource', '(TagName="Progression.Resource.Points")')
    g.value(fund, 'Delta', '10')
    overlap = g.event('ReceiveActorBeginOverlap')
    gate = g.branch(overlap, authority)
    pawn = g.action('CastToPawn')
    g.link(gate, 'then', pawn, 'execute')
    g.link(overlap, 'OtherActor', pawn, 'Object')
    controlled = g.call('/Script/Engine.Pawn:IsPlayerControlled')
    g.link(pawn, 'AsPawn', controlled, 'self')
    ready = g.branch(g.branch(pawn, controlled), record)
    fields = g.action('BreakAtlasProgressionRecord')
    g.link(record, 'OutRecord', fields, 'AtlasProgressionRecord')
    request = g.action('MakeAtlasTransactionRequest')
    transaction = g.call('/Script/Engine.KismetGuidLibrary:NewGuid')
    g.link(transaction, 'ReturnValue', request, 'TransactionId')
    g.link(subject, 'AtlasSubjectHandle', request, 'Subject')
    g.value(request, 'SchemaId', schema_literal)
    g.link(fields, 'Revision', request, 'ExpectedRevision')
    g.value(request, 'NodeId', 'Training')
    submit = g.call('/Script/AtlasProgressionSystemRuntime.AtlasProgressionComponent:SubmitTransaction')
    g.link(ready, 'then', submit, 'execute')
    g.link(owner, 'Progression', submit, 'self')
    g.link(request, 'AtlasTransactionRequest', submit, 'Request')
    g.graph.add_comment_node('A fresh saved subject receives 10 points once. Each player overlap buys one Training rank for 3 points, capped at rank 3. World save restores the record before BeginPlay, so reload never refills points or repeats a purchase. Every purchase uses the observed revision.', unreal.Vector2D(-40, -110), unreal.Vector2D(1800, 100))
    g.compile()
    scan = unreal.PrimaryAssetTypeInfo()
    scan.set_editor_property('primary_asset_type', 'AtlasProgressionSchema')
    scan.set_editor_property('asset_base_class', unreal.AtlasProgressionSchema)
    scan.set_editor_property('specific_assets', [unreal.SoftObjectPath(schema.get_path_name())])
    feature.set_editor_property('primary_asset_types_to_scan', list(feature.get_editor_property('primary_asset_types_to_scan')) + [scan])
    return finish(result, [schema, actor, feature])


def populate_subtitles(plugin_name, content_id):
    recipe, result, actor, feature = base(plugin_name, content_id)
    component(actor, unreal.SubtitleEmitterComponent, 'Subtitles')
    trigger = component(actor, unreal.SphereComponent, 'SubtitleRange')
    trigger.set_sphere_radius(240.0)
    trigger.set_collision_enabled(unreal.CollisionEnabled.QUERY_ONLY)
    trigger.set_collision_response_to_all_channels(unreal.CollisionResponseType.ECR_IGNORE)
    trigger.set_collision_response_to_channel(unreal.CollisionChannel.ECC_PAWN, unreal.CollisionResponseType.ECR_OVERLAP)
    trigger.set_editor_property('generate_overlap_events', True)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(actor):
        raise RuntimeError('Subtitle components did not compile.')
    g = recipe.ExampleGraph(actor)
    overlap = g.event('ReceiveActorBeginOverlap')
    pawn = g.action('CastToPawn')
    g.link(overlap, 'then', pawn, 'execute')
    g.link(overlap, 'OtherActor', pawn, 'Object')
    local = g.call('/Script/Engine.Pawn:IsLocallyControlled')
    g.link(pawn, 'AsPawn', local, 'self')
    player = g.call('/Script/Engine.Pawn:IsPlayerControlled')
    g.link(pawn, 'AsPawn', player, 'self')
    gate = g.branch(g.branch(pawn, player), local)
    emitter = g.member('Subtitles')
    show = g.call('/Script/AtlasSubtitleSystemRuntime.SubtitleEmitterComponent:ShowCustomSubtitle')
    g.link(gate, 'then', show, 'execute')
    g.link(emitter, 'Subtitles', show, 'self')
    caption = g.call('/Script/Engine.KismetSystemLibrary:MakeLiteralText')
    g.value(caption, 'Value', 'NSLOCTEXT("' + content_id + '", "ExampleCaption", "This caption belongs to the example mod. Edit this text in the actor Blueprint.")')
    g.link(caption, 'ReturnValue', show, 'SubtitleText')
    g.value(show, 'Duration', '4.0')
    g.graph.add_comment_node('Presentation only: a local player overlap shows a four-second spatial caption. No RPC or authoritative gameplay change. The scoped display uses its owning LocalPlayer viewpoint. The host may retain separate legacy subtitle displays.', unreal.Vector2D(-40, -110), unreal.Vector2D(1800, 100))
    g.compile()
    factory = unreal.WidgetBlueprintFactory()
    factory.set_editor_property('parent_class', unreal.UserWidget)
    widget = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        'W_ExampleSubtitles', '/' + plugin_name + '/SubtitleExample', unreal.WidgetBlueprint, factory)
    if not widget:
        raise RuntimeError('Could not create the subtitle display Blueprint.')
    ui = unreal.AtlasUIAuthoringLibrary
    display = ui.create_designer_widget(widget, unreal.SubtitleDisplay, 'ScopedSubtitles')
    if not display:
        raise RuntimeError('Could not create the scoped subtitle display.')
    options_factory = unreal.DataAssetFactory()
    options_factory.set_editor_property('data_asset_class', unreal.SubtitleDisplayOptions)
    options = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        'DA_SubtitleStyle', '/' + plugin_name + '/SubtitleExample', unreal.SubtitleDisplayOptions, options_factory)
    if not options:
        raise RuntimeError('Could not create the mod-owned subtitle style.')
    font_asset = unreal.load_asset('/Engine/EngineFonts/Roboto')
    if not font_asset:
        raise RuntimeError('The engine example font is unavailable.')
    font = unreal.SlateFontInfo()
    font.set_editor_property('font_object', font_asset)
    font.set_editor_property('typeface_font_name', 'Regular')
    font.set_editor_property('size', 24)
    options.set_editor_property('font', font)
    options.set_editor_property('display_text_sizes', [16, 20, 24, 30, 36])
    options.set_editor_property('display_text_colors', [unreal.LinearColor(1, 1, 1, 1), unreal.LinearColor(1, 1, 0, 1)])
    options.set_editor_property('display_border_size', [0.0, 1.0, 2.0])
    options.set_editor_property('display_background_opacity', [0.0, 0.25, 0.5, 0.75, 1.0])
    display.set_editor_property('options', options)
    display.set_editor_property('use_local_player_subtitles', True)
    display.set_editor_property('wrap_text_at', 640.0)
    if not ui.set_designer_root(widget, display) or not unreal.BlueprintEditorLibrary.compile_blueprint(widget):
        raise RuntimeError('Scoped subtitle display did not compile.')
    entry = unreal.AtlasHUDElementEntry()
    entry.set_editor_property('widget_class', widget.generated_class())
    # This point is present in W_ElevatorHUDLayout. It adds a local-player widget;
    # it never replaces the active CommonUI layer or a host subtitle widget.
    entry.set_editor_property('slot_id', tag('HUD.Slot.ModeStatus'))
    action = unreal.new_object(unreal.AtlasGameFeatureAction_AddWidgets, outer=feature)
    action.set_editor_property('widgets', [entry])
    feature.set_editor_property('actions', list(feature.get_editor_property('actions')) + [action])
    return finish(result, [actor, options, widget, feature])
