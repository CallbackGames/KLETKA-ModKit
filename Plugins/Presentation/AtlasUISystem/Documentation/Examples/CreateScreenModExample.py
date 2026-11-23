# Copyright Callback LLP. All Rights Reserved.
"""Create an editable presentation-role starter, using only public owner/Unreal types."""
import unreal


def populate_template(plugin_name, content_id):
    folder = "/" + plugin_name + "/ScreenExample"
    name = "W_ExampleMainScreen"
    destination = folder + "/" + name
    if unreal.EditorAssetLibrary.does_asset_exist(destination):
        raise RuntimeError("Screen starter already exists: " + destination)
    feature = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if feature is None or list(feature.get_editor_property("actions")):
        raise RuntimeError("Screen starter requires a new empty Game Feature Data.")
    role = unreal.GameplayTag()
    if (not role.import_text('(TagName="UI.Frontend.Screen.Main")')
            or 'UI.Frontend.Screen.Main' not in role.export_text()):
        raise RuntimeError("This game does not publish the main-menu screen role.")
    factory = unreal.WidgetBlueprintFactory()
    factory.set_editor_property("parent_class", unreal.AtlasUIActivatableWidget)
    blueprint = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        name, folder, unreal.WidgetBlueprint, factory)
    if blueprint is None:
        raise RuntimeError("Could not create the example screen Blueprint.")
    authoring = unreal.AtlasUIAuthoringLibrary
    background = authoring.create_designer_widget(blueprint, unreal.Border, "ExampleBackground")
    if background is None:
        raise RuntimeError("The new screen has no writable designer tree.")
    background.set_padding(unreal.Margin(48))
    background.set_brush_color(unreal.LinearColor(0.025, 0.025, 0.025, 1.0))
    column = authoring.create_designer_widget(blueprint, unreal.VerticalBox, "ExampleContent")
    background.add_child(column)
    for index, value in enumerate((
        "MY MODDED MAIN MENU",
        "Edit this Widget Blueprint in the Designer and add your navigation in its Graph.",
        "This starter replaces only the main menu. Authentication and content checks remain owned by the game.",
        "Use the game's USE STANDARD MENU control, F10 or controller View / Select to return safely.",
    )):
        label = authoring.create_designer_widget(blueprint, unreal.TextBlock, "ExampleText" + str(index))
        label.set_text(value)
        label.set_auto_wrap_text(True)
        slot = column.add_child_to_vertical_box(label)
        slot.set_padding(unreal.Margin(0, 0, 0, 20))
    if not authoring.set_designer_root(blueprint, background):
        raise RuntimeError("Could not assign the screen's owned root.")
    if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
        raise RuntimeError("Example screen did not compile.")
    cdo = unreal.get_default_object(blueprint.generated_class())
    cdo.set_editor_property("default_input_mode", unreal.AtlasUIInputMode.MENU)
    cdo.set_editor_property("is_focusable", True)
    cdo.set_editor_property("auto_activate", False)
    replacement = unreal.AtlasUIScreenReplacement()
    replacement.set_editor_property("role", role)
    replacement.set_editor_property("screen_class", blueprint.generated_class())
    action = unreal.new_object(unreal.AtlasGameFeatureAction_ReplaceScreens, outer=feature)
    action.set_editor_property("screens", [replacement])
    feature.set_editor_property("actions", [action])
    for asset in (blueprint, feature):
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {"plugin": plugin_name, "id": content_id,
            "assets": [blueprint.get_path_name(), feature.get_path_name()]}
