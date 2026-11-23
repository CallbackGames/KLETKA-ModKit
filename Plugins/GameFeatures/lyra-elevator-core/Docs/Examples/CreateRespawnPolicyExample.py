# Copyright Callback LLP. All Rights Reserved.
"""Create a public respawn price asset and component binding in an existing Game Feature.

Run inside the ModKit editor. create_policy returns drafts for the caller to review and save.
The New Mod populate_template entry point saves those drafts and their GameFeatureData binding.
Neither entry point activates a feature, edits a map, or uses private game classes.
"""
import math
import unreal


def populate_template(plugin_name, content_id):
    """New Mod recipe: save the authored draft and its explicit feature binding."""
    feature=unreal.load_asset('/'+plugin_name+'/'+plugin_name)
    created=create_policy(feature,'/'+plugin_name+'/RespawnExample')
    assets=[created['policy'],created['component'],feature]
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset,only_if_is_dirty=False):
            raise RuntimeError('Could not save '+asset.get_path_name())
    return {'plugin':plugin_name,'id':content_id,'assets':[a.get_path_name() for a in assets]}


def create_policy(feature, folder, multiplier=0.5, adjustment=0, on_created=None):
    if not isinstance(feature, unreal.GameFeatureData):
        raise TypeError("Select a GameFeatureData asset from the mod's content root.")
    mount = feature.get_path_name().split("/", 2)[1]
    if not folder.startswith("/" + mount + "/"):
        raise ValueError("Create the policy inside the same content mount as its GameFeatureData.")
    if not math.isfinite(multiplier) or multiplier < 0 or not isinstance(adjustment, int) or not -2147483648 <= adjustment <= 2147483647:
        raise ValueError("Use a finite nonnegative multiplier and an int32 flat adjustment.")
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    for name in ("DA_RespawnPrice", "BP_RespawnCostPolicy"):
        if unreal.EditorAssetLibrary.does_asset_exist(folder + "/" + name):
            raise FileExistsError("Destination already contains " + name + "; choose another folder.")
    action_class = unreal.load_class(None, "/Script/GameFeatures.GameFeatureAction_AddComponents")
    if action_class is None:
        raise RuntimeError("The engine Add Components action is unavailable.")
    policy = tools.create_asset("DA_RespawnPrice", folder, unreal.LeRespawnPricePolicy, unreal.LeRespawnPricePolicyFactory())
    if policy is None:
        raise RuntimeError("Could not create Respawn Price Policy.")
    if on_created:
        on_created(policy)
    policy.set_editor_property("multiplier", multiplier)
    policy.set_editor_property("flat_adjustment", adjustment)
    factory = unreal.BlueprintFactory()
    factory.set_editor_property("parent_class", unreal.LeRespawnCostPolicyComponent)
    bp = tools.create_asset("BP_RespawnCostPolicy", folder, unreal.Blueprint, factory)
    if bp is None:
        raise RuntimeError("Could not create the policy component; inspect the retained price asset draft.")
    if on_created:
        on_created(bp)
    component_class = bp.generated_class()
    if component_class is None:
        raise RuntimeError("The component draft has no generated class.")
    unreal.get_default_object(component_class).set_editor_property("policy", policy)
    if not unreal.BlueprintEditorLibrary.compile_blueprint(bp):
        raise RuntimeError("Policy component did not compile; inspect the retained draft.")
    component_class = bp.generated_class()
    entry = unreal.GameFeatureComponentEntry()
    entry.set_editor_property("actor_class", unreal.GameStateBase)
    entry.set_editor_property("component_class", component_class)
    entry.set_editor_property("server_component", True)
    entry.set_editor_property("client_component", True)
    action = unreal.new_object(action_class, outer=feature)
    # This engine action has no generated Python subclass; use the reflected C++ property name.
    action.set_editor_property("ComponentList", [entry])
    actions = list(feature.get_editor_property("actions"))
    actions.append(action)
    feature.set_editor_property("actions", actions)
    return {"policy": policy, "component": bp, "action": action}
