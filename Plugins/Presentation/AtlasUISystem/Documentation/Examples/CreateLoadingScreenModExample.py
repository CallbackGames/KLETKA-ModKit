# Copyright Callback LLP. All Rights Reserved.
"""Create an additive loading variant through the public presentation owner."""
import unreal


def populate_template(plugin_name, content_id):
    folder = "/" + plugin_name + "/LoadingExample"
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if feature is None or list(feature.get_editor_property("actions")):
        raise RuntimeError("Loading starter requires a new empty Game Feature Data.")
    for name in ("W_ExampleLoadingScreen", "DA_ExampleLoadingScreen"):
        if unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name):
            raise RuntimeError("Loading starter already exists: " + folder + "/" + name)
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.WidgetBlueprintFactory()
    factory.set_editor_property("parent_class", unreal.UserWidget)
    blueprint = tools.create_asset("W_ExampleLoadingScreen", folder, unreal.WidgetBlueprint, factory)
    if blueprint is None:
        raise RuntimeError("Could not create the loading Widget Blueprint.")
    authoring = unreal.AtlasUIAuthoringLibrary
    background = authoring.create_designer_widget(blueprint, unreal.Border, "Background")
    background.set_padding(unreal.Margin(64))
    background.set_brush_color(unreal.LinearColor(0.015, 0.015, 0.02, 1.0))
    background.set_horizontal_alignment(unreal.HorizontalAlignment.H_ALIGN_CENTER)
    background.set_vertical_alignment(unreal.VerticalAlignment.V_ALIGN_CENTER)
    title = authoring.create_designer_widget(blueprint, unreal.TextBlock, "Title")
    title.set_text("MY LOADING SCREEN")
    title.set_auto_wrap_text(True)
    background.add_child(title)
    if not authoring.set_designer_root(blueprint, background):
        raise RuntimeError("Could not assign the loading screen's owned root.")
    unreal.BlueprintEditorLibrary.compile_blueprint(blueprint)
    if blueprint.get_editor_property("status") != unreal.BlueprintStatus.BS_UP_TO_DATE:
        raise RuntimeError("Example loading screen did not compile.")
    asset_factory = unreal.DataAssetFactory()
    asset_factory.set_editor_property("data_asset_class", unreal.AtlasLoadingScreenDefinition)
    definition = tools.create_asset("DA_ExampleLoadingScreen", folder,
                                    unreal.AtlasLoadingScreenDefinition, asset_factory)
    if definition is None:
        raise RuntimeError("Could not create the loading definition.")
    definition.set_editor_property("screen_id", content_id + ".loading.main")
    definition.set_editor_property("widget_class", blueprint.generated_class())
    definition.set_editor_property("weight", 1)
    action = unreal.new_object(unreal.AtlasGameFeatureAction_AddLoadingScreens, outer=feature)
    action.set_editor_property("screens", [definition])
    feature.set_editor_property("actions", [action])
    for asset in (blueprint, definition, feature):
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {"plugin": plugin_name, "id": content_id,
            "assets": [blueprint.get_path_name(), definition.get_path_name(), feature.get_path_name()]}
