# Copyright Callback LLP. All Rights Reserved.
"""Run with the generated ModKit's Python editor commandlet; see Docs/Authoring/index.html in the project.

Creates new content only. Existing destinations are rejected by the owner tools.
Change the default plugin/content names for your mod; do not regenerate shipped identities.
"""
import json
from pathlib import Path
import unreal


def create_example(plugin_name="AtlasInventoryExample", content_id="atlas.inventory.example"):
    request = unreal.AMSNewModRequest()
    identity = unreal.AMSModAuthoringIdentity()
    identity.set_editor_property("template", unreal.AMSModTemplate.GAMEPLAY_GAME_FEATURE)
    identity.set_editor_property("content_id", content_id)
    identity.set_editor_property("plugin_name", plugin_name)
    identity.set_editor_property("required_plugin_names", ["AtlasInventorySystem"])
    request.set_editor_property("identity", identity)
    presentation = unreal.AMSModAuthoringPresentation()
    presentation.set_editor_property("author", "Atlas Inventory example")
    request.set_editor_property("presentation", presentation)
    result = unreal.AMSModAuthoringBlueprintLibrary.create_mod_from_template(request)
    if result is None or not result.get_editor_property("success"):
        raise RuntimeError("Mod Wizard rejected the destination; inspect its validation messages.")

    created = populate_template(plugin_name, content_id)
    created.update(root=result.get_editor_property("mod_root"), manifest=result.get_editor_property("manifest_path"))
    return created


def populate_template(plugin_name, content_id):
    """Populate a new mounted Game Feature; never overwrite an asset or alter a map."""
    folder = "/" + plugin_name + "/InventoryExample"
    names = ("DA_Ingredient", "DA_ExampleItem", "DA_ExampleRecipe", "DA_InventoryContent",
             "BP_ExampleStation", "BP_IngredientPickup")
    if any(unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name) or
           unreal.find_object(None, folder + "/" + name + "." + name) for name in names):
        raise RuntimeError("Inventory starter destination already contains assets.")
    data = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    if data is None or list(data.get_editor_property("actions")):
        raise RuntimeError("Inventory starter requires a new empty Game Feature Data.")
    factory = unreal.DataAssetFactory()
    factory.set_editor_property("data_asset_class", unreal.AtlasInventoryItemDefinition)
    ingredient = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
        "DA_Ingredient", folder, unreal.AtlasInventoryItemDefinition, factory)
    if ingredient is None:
        raise RuntimeError("Could not create the ingredient definition.")
    # The definition generates its own stable ID; identity is deliberately hidden from Python editing.
    ingredient.set_editor_property("display_name", "Example ingredient")
    tag = unreal.GameplayTag()
    if not tag.import_text('(TagName="Inventory.Crafting.Station.Workbench")'):
        raise RuntimeError("Inventory's Workbench station tag is unavailable.")
    library = unreal.AtlasInventoryModAuthoringLibrary
    created = library.create_inventory_mod_example(folder, unreal.Name(content_id + ".workbench"), ingredient, tag)
    if created is None:
        raise RuntimeError("Inventory helper rejected the example; inspect its failure text.")
    content, failure = created
    if content is None or str(failure):
        raise RuntimeError(str(failure))
    # Both definitions belong to this mod; register the ingredient as well as its output.
    content.set_editor_property("items", [*content.get_editor_property("items"), ingredient])
    errors = list(content.validate_content())
    if errors:
        raise RuntimeError("; ".join(str(error) for error in errors))
    item = content.get_editor_property("items")[0]
    recipe = content.get_editor_property("recipes")[0]
    data = unreal.load_asset("/" + plugin_name + "/" + plugin_name)
    action_class = unreal.load_class(None, "/Script/AtlasInventorySystemRuntime.AtlasGameFeatureAction_AddInventoryContent")
    if data is None or action_class is None:
        raise RuntimeError("Game Feature Data or Inventory action is unavailable.")
    action = unreal.new_object(action_class, outer=data)
    action.set_editor_property("content", content)
    data.set_editor_property("actions", [action])
    actor_result = library.create_inventory_example_actors(folder, ingredient, tag)
    if actor_result is None:
        raise RuntimeError("Could not create the station and pickup example.")
    station, pickup, failure = actor_result
    if station is None or pickup is None or str(failure):
        raise RuntimeError(str(failure))
    unreal.log_warning("The new station has a crafting component only. Bind the player's authorized interaction to Submit Craft before testing the inventory exchange.")
    assets = [ingredient, item, recipe, content, data, station, pickup]
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name())
    return {
        "plugin": plugin_name, "id": content_id,
        "assets": [asset.get_path_name() for asset in assets],
        "recipeId": str(recipe.get_editor_property("recipe_id")),
    }


if __name__ == "__main__":
    example = create_example()
    project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
    output = project / "Saved/InventoryModExample"
    output.mkdir(parents=True, exist_ok=True)
    (output / "authoring.json").write_text(json.dumps(example, indent=2), encoding="utf-8")
    unreal.log("Inventory example saved. Inspect it before packaging with the Mod Wizard.")
