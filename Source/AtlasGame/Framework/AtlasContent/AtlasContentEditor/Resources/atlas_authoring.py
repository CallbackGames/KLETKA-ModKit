# Copyright Callback LLP. All Rights Reserved.
"""Game and ModKit editor composition of existing Atlas owner authoring tools.

No runtime types or rules live here. Creation failures remove only operation-owned
drafts; save failures retain a journal for resuming without duplicate contributions.
"""
import hashlib
import importlib.util
import os
import json
import re
import subprocess
import uuid
from pathlib import Path

import unreal


def prop(obj, name):
    return obj.get_editor_property(name)


def tag(value):
    result = unreal.GameplayTag()
    if value and (not re.fullmatch(r"[A-Za-z0-9_.]+", value) or
                  not result.import_text('(TagName="' + value + '")') or
                  not unreal.GameplayTagLibrary.is_gameplay_tag_valid(result)):
        raise ValueError("Unknown gameplay tag: " + value)
    return result


def load(path, cls):
    obj = unreal.load_asset(path) if path else None
    if obj is None or not isinstance(obj, cls):
        raise ValueError("Select an existing " + cls.__name__ + ": " + str(path))
    return obj


class Authoring:
    def __init__(self, request):
        self.request = request
        self.project = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir()))
        self.result = dict(success=False, summary="Not completed", feature="", assets=[], messages=[])
        self.assets = []
        self.feature = None
        self.pending_actions = []
        self.pending_scans = []
        self.journal = None

    def message(self, text, asset=None, severity="info"):
        path = asset.get_path_name() if isinstance(asset, unreal.Object) else str(asset or "")
        self.result["messages"].append(dict(severity=severity, asset=path, message=str(text)))

    def require(self, name):
        cls = getattr(unreal, name, None)
        if cls is None:
            raise ValueError(name + " is unavailable. Enable/build its owning Editor module for this product.")
        return cls

    def descriptors(self):
        return {p.stem: p for p in (self.project / "Plugins").rglob("*.uplugin")
                if "Intermediate" not in p.parts and "Saved" not in p.parts}

    def preflight(self):
        r = self.request
        self.recipe = r.get("recipe", "ItemRecipe")
        self.name = r.get("name", "")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.name):
            raise ValueError("Name must start with a letter and contain only letters, digits and underscores (1–64 characters).")
        self.descriptor_paths = self.descriptors()
        self.dependencies = set()
        self.feature_name = r.get("new_feature", "")
        if r.get("feature"):
            self.feature = load(r["feature"], unreal.GameFeatureData)
            self.feature_name = self.feature.get_path_name().split("/")[1]
            if self.feature_name == "Game" or self.feature_name not in self.descriptor_paths:
                raise ValueError("Choose GameFeatureData inside a mounted Game Feature plugin.")
            self.result["feature"] = self.feature.get_path_name()
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", self.feature_name):
            raise ValueError("Choose a feature or enter a new plugin name (letters, digits and underscores).")
        elif self.feature_name in self.descriptor_paths:
            raise ValueError("Plugin already exists. Select its GameFeatureData instead: " + self.feature_name)
        if not self.feature and (self.project / "Plugins/GameFeatures" / self.feature_name).exists():
            raise ValueError("Feature directory already exists; it will not be overwritten: " + self.feature_name)
        self.folder = "/" + self.feature_name + "/" + self.name
        self.namespace = self.feature_name.lower() + "." + self.name.lower()
        self.owner_name = self.feature_name + "_" + self.name
        self.source = None
        if self.recipe == "ItemRecipe":
            self.require("AtlasInventoryModAuthoringLibrary")
            self.dependencies.add("AtlasInventorySystem")
            self.source = load(r.get("ingredient"), self.require("AtlasInventoryItemDefinition"))
            self.station = tag(r.get("station_tag", ""))
            if not r.get("station_tag"):
                raise ValueError("Select the station tag used by your test host's AvailableList crafting station.")
            self.names = ["DA_ExampleItem", "DA_ExampleRecipe", "DA_InventoryContent", "BP_ExampleStation", "BP_IngredientPickup"]
        elif self.recipe == "NPC":
            self.require("AtlasNPCAuthoringLibrary")
            # AI composition is a Source family, not a fictitious plugin dependency.
            self.movement = getattr(unreal.AtlasNPCMovementPreset, re.sub(r"(?<!^)(?=[A-Z])", "_", r.get("movement", "Ground")).upper())
            self.behavior = getattr(unreal.AtlasNPCBehaviorPreset, r.get("behavior", "Passive").upper())
            self.work_action = tag(r.get("work_action", ""))
            if r.get("behavior") == "Worker" and not r.get("work_action"):
                raise ValueError("Worker requires the exact Work Action tag from a target Interaction Option.")
            self.names = ["NPC_" + self.owner_name, "ST_" + self.owner_name, "BP_" + self.owner_name]
        elif self.recipe == "InteractiveObject":
            self.source = load(r.get("source_option"), self.require("AtlasInteractionOption"))
            self.actor_template = load(r.get("actor_template"), unreal.Blueprint)
            failure = self.require("AtlasInteractionTemplateLibrary").validate_actor_template(self.actor_template, self.source)
            if str(failure):
                raise ValueError(str(failure))
            self.validate_asset(self.actor_template)
            root = self.actor_template.get_path_name().split("/")[1]
            if root not in ("Game", "Engine", self.feature_name):
                self.dependencies.add(root)
            self.names = ["IO_" + self.owner_name, "IP_" + self.owner_name, "BP_" + self.owner_name]
        elif self.recipe == "LuaBehavior":
            self.require("AtlasLuaScript")
            self.require("AtlasDoorComponent")
            self.lua_example_path = Path(unreal.Paths.project_dir()).resolve() / "Plugins/Framework/AtlasLuaFramework/Docs/Examples/CreateLuaDoorExample.py"
            if not self.lua_example_path.is_file():
                raise ValueError("The public Lua door recipe is missing from this editor distribution.")
            self.dependencies.update(("AtlasLuaFramework", "AtlasSaveGameFramework"))
            self.lua_event = tag(r.get("lua_event", ""))
            if not r.get("lua_event"):
                raise ValueError("Choose a registered Lua event tag.")
            groups = [str(value) for value in unreal.get_default_object(unreal.AtlasContentAuthoringOptions).call_method("PersistenceGroupChoices", ())]
            self.lua_group = r.get("lua_persistence_group", "")
            if self.lua_group in ("", "None") and len(groups) == 1:
                self.lua_group = groups[0]
            if self.lua_group.lower() not in {group.lower() for group in groups}:
                raise ValueError("Choose a World Save Group from the host catalogue or a loaded mod world fragment before creating this actor.")
            self.names = ["DA_LuaBehavior", "BP_LuaActor"]
        elif self.recipe == "ExperienceVariant":
            self.dependencies.add("AtlasGameplayExperienceFramework")
            self.source = load(r.get("base_experience"), self.require("AtlasGameplayExperienceDefinition"))
            if not prop(self.source, "pack_ids") and prop(self.source, "packs"):
                raise ValueError("Migrate legacy Packs to Pack IDs using the owner tool before creating a variant.")
            self.names = ["DA_" + self.feature_name + "_" + self.name, "PACK_" + self.feature_name + "_" + self.name]
        else:
            raise ValueError("Unsupported recipe: " + self.recipe)
        if self.source:
            root = self.source.get_path_name().split("/")[1]
            if root not in ("Game", "Engine", self.feature_name):
                self.dependencies.add(root)
            self.validate_asset(self.source)
        if self.feature:
            desc = json.loads(self.descriptor_paths[self.feature_name].read_text(encoding="utf-8-sig"))
            declared = {p["Name"] for p in desc.get("Plugins", []) if p.get("Enabled", True)}
            missing = self.dependencies - declared
            if missing:
                raise ValueError("Game Feature descriptor must declare dependencies before creation: " + ", ".join(sorted(missing)))
        if self.feature and unreal.AtlasContentAuthoringOptions.is_asset_dirty(self.feature):
            raise ValueError("Save the selected Game Feature before creating linked content. Existing unsaved changes are not part of this operation.")
        for name in self.names:
            path = self.folder + "/" + name
            if self.feature and unreal.EditorAssetLibrary.does_asset_exist(path):
                raise ValueError("Destination exists; choose a new name or edit the existing asset: " + path)
            self.message("Will create " + path)
        if self.recipe == "InteractiveObject":
            self.message("Copies the working actor's components and graph. Host interaction/input and any interactor ability requirements remain part of the selected test Experience.")
        self.message("Required plugin dependencies: " + (", ".join(sorted(self.dependencies)) or "Source owner modules in this product"))
        self.fail_if_errors()

    def fail_if_errors(self):
        if any(m["severity"] == "error" for m in self.result["messages"]):
            raise ValueError("Resolve the linked owner diagnostics before continuing.")

    def validate_asset(self, asset):
        data = unreal.AssetRegistryHelpers.create_asset_data(asset)
        state, errors, warnings = unreal.get_editor_subsystem(unreal.EditorValidatorSubsystem).is_asset_valid(
            data, unreal.DataValidationUsecase.MANUAL)
        for error in errors:
            self.message(error, asset, "error")
        for warning in warnings:
            self.message(warning, asset, "warning")
        if state == unreal.DataValidationResult.INVALID and not errors:
            self.message("Owner validator rejected this asset; inspect Data Validation log.", asset, "error")

    def create_data(self, name, cls, factory=None):
        if factory is None:
            factory = unreal.DataAssetFactory()
            factory.set_editor_property("data_asset_class", cls)
        asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(name, self.folder, cls, factory)
        return self.remember(asset)

    def remember(self, asset):
        if asset is None:
            raise RuntimeError("Owner tool did not return an asset. Inspect Output Log.")
        self.assets.append(asset)
        self.result["assets"].append(asset.get_path_name())
        return asset

    def duplicate(self, source, name):
        return self.remember(unreal.AssetToolsHelpers.get_asset_tools().duplicate_asset(name, self.folder, source))

    def ensure_feature(self):
        if self.feature:
            return
        request = unreal.AMSNewModRequest()
        identity = unreal.AMSModAuthoringIdentity()
        identity.set_editor_property("template", unreal.AMSModTemplate.GAMEPLAY_GAME_FEATURE)
        identity.set_editor_property("content_id", self.feature_name.lower() + ".content")
        identity.set_editor_property("plugin_name", self.feature_name)
        identity.set_editor_property("required_plugin_names", sorted(self.dependencies))
        request.set_editor_property("identity", identity)
        result = unreal.AMSModAuthoringBlueprintLibrary.create_mod_from_template(request)
        if result is None or not prop(result, "success"):
            raise RuntimeError("Mod Wizard rejected creation; inspect its report. Partial output is retained.")
        self.feature = load("/" + self.feature_name + "/" + self.feature_name, unreal.GameFeatureData)
        self.result["feature"] = self.feature.get_path_name()
        # Internal Source products keep inactive features Registered for asset discovery.
        descriptor = self.project / "Plugins/GameFeatures" / self.feature_name / (self.feature_name + ".uplugin")
        data = json.loads(descriptor.read_text(encoding="utf-8-sig"))
        data["BuiltInInitialFeatureState"] = "Registered"
        data["Category"] = "Atlas Content"
        descriptor.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def add_scan(self, asset_type, cls, assets):
        self.pending_scans.append(dict(type=asset_type, cls=cls.static_class().get_path_name(), assets=[a.get_path_name() for a in assets]))

    def journal_path(self, feature_name, name):
        key = hashlib.sha256((feature_name + "/" + name).encode("utf-8")).hexdigest()
        return self.project / "Saved/AtlasAuthoring/Operations" / (key + ".json")

    def write_journal(self):
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.journal, indent=2), encoding="utf-8")
        os.replace(temporary, self.journal_file)
        self.result["journal"] = str(self.journal_file)

    def disk_path(self, asset_path):
        package = asset_path.split(".")[0]
        prefix = "/" + self.feature_name + "/"
        if not package.startswith(prefix):
            raise ValueError("Operation asset is outside its feature: " + asset_path)
        base = self.descriptor_paths[self.feature_name].parent / "Content"
        path = (base / (package[len(prefix):] + ".uasset")).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError("Invalid operation asset path.")
        return path

    def disk_hash(self, path):
        file = self.disk_path(path)
        return hashlib.sha256(file.read_bytes()).hexdigest() if file.is_file() else None

    def apply_links(self):
        actions = list(prop(self.feature, "actions"))
        for path in self.journal["inventory_content"]:
            content = load(path, self.require("AtlasInventoryContentSet"))
            cls = unreal.load_class(None, "/Script/AtlasInventorySystemRuntime.AtlasGameFeatureAction_AddInventoryContent")
            if not any(a and a.get_class() == cls and prop(a, "content") == content for a in actions):
                action = unreal.new_object(cls, outer=self.feature)
                action.set_editor_property("content", content)
                actions.append(action)
        self.feature.set_editor_property("actions", actions)
        entries = [entry.copy() for entry in prop(self.feature, "primary_asset_types_to_scan")]
        for scan in self.journal["scans"]:
            entry = next((e for e in entries if str(prop(e, "primary_asset_type")) == scan["type"]), None)
            if entry is None:
                entry = unreal.PrimaryAssetTypeInfo()
                entry.set_editor_property("primary_asset_type", scan["type"])
                entry.set_editor_property("asset_base_class", unreal.load_class(None, scan["cls"]))
                entries.append(entry)
            paths = list(prop(entry, "specific_assets"))
            for path in scan["assets"]:
                value = unreal.SoftObjectPath(path)
                if value not in paths:
                    paths.append(value)
            entry.set_editor_property("specific_assets", paths)
        self.feature.set_editor_property("primary_asset_types_to_scan", entries)

    def save_asset(self, asset):
        # A single seam for failure-injection acceptance; production always uses the owner editor save.
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError("Could not save " + asset.get_path_name() + ". Review the operation journal, then Resume Save; no asset is recreated.")

    def commit(self):
        prepared_types = []
        primary_paths = set()
        for scan in self.journal['scans']:
            info = unreal.PrimaryAssetTypeInfo()
            info.set_editor_property('primary_asset_type', scan['type'])
            info.set_editor_property('asset_base_class', unreal.load_class(None, scan['cls']))
            prepared_types.append(info)
            primary_paths.update(scan['assets'])
        for path in self.journal['inventory_content']:
            content = load(path, self.require('AtlasInventoryContentSet'))
            for field in ('items', 'recipes'):
                primary_paths.update(asset.get_path_name() for asset in prop(content, field) if asset)
        registration = unreal.AtlasContentAuthoringOptions()
        registration.set_editor_property('prepared_primary_asset_types', prepared_types)
        # Only these owner definitions are resolved by Primary Asset ID. Options,
        # profiles and Blueprint templates are linked directly; do not invent
        # Asset Manager types for every UPrimaryDataAsset in an operation.
        primary_assets = [asset for asset in self.assets if asset.get_path_name() in primary_paths]
        if not registration.refresh_created_primary_assets(primary_assets):
            raise RuntimeError("Primary Asset registration failed. Check the owner's type in Asset Manager settings and resolve conflicting IDs before Resume Save.")
        for asset in self.assets:
            self.validate_asset(asset)
        self.fail_if_errors()
        self.journal["phase"] = "saving"
        self.write_journal()
        for asset in self.assets:
            path = asset.get_path_name()
            previous = self.journal["saved"].get(path)
            if previous:
                if self.disk_hash(path) != previous or unreal.AtlasContentAuthoringOptions.is_asset_dirty(asset):
                    raise RuntimeError("Previously saved operation asset changed; preserved without overwrite: " + path)
                continue
            self.save_asset(asset)
            self.journal["saved"][path] = self.disk_hash(path)
            self.write_journal()
            self.message("Saved", asset)
        if self.disk_hash(self.feature.get_path_name()) != self.journal["feature_before"]:
            raise RuntimeError("The Game Feature changed on disk after preparation. Preserved without overwriting its actions; review the journal.")
        if unreal.AtlasContentAuthoringOptions.is_asset_dirty(self.feature):
            raise RuntimeError("The Game Feature has unsaved changes. Save/review those changes before recovery; no actions were overwritten.")
        old_actions = list(prop(self.feature, "actions"))
        old_scans = list(prop(self.feature, "primary_asset_types_to_scan"))
        try:
            self.apply_links()
            self.save_asset(self.feature)
        except Exception:
            self.feature.set_editor_property("actions", old_actions)
            self.feature.set_editor_property("primary_asset_types_to_scan", old_scans)
            # Leave the package dirty deliberately: do not silently discard unrelated editor state.
            raise
        self.journal["phase"] = "complete"
        self.journal["feature_after"] = self.disk_hash(self.feature.get_path_name())
        self.write_journal()
        self.result.update(success=True, summary="Linked assets saved. Validate Feature with a test Experience before play.")

    def resume(self):
        self.feature = load(self.request.get("feature"), unreal.GameFeatureData)
        self.feature_name = self.feature.get_path_name().split("/")[1]
        self.descriptor_paths = self.descriptors()
        self.journal_file = self.journal_path(self.feature_name, self.request.get("name", ""))
        self.journal = json.loads(self.journal_file.read_text(encoding="utf-8"))
        if self.journal["feature"] != self.feature.get_path_name():
            raise ValueError("Operation belongs to another Game Feature.")
        self.result["feature"] = self.feature.get_path_name()
        if self.journal["phase"] == "complete":
            self.result.update(success=True, summary="This operation is already complete; no assets or actions were duplicated.")
            return
        if self.journal["phase"] not in ("prepared", "saving"):
            raise ValueError("Creation failed before preparation. Review retained diagnostics, then retry Create Linked Assets with the same feature and name.")
        self.assets = [load(path, unreal.Object) for path in self.journal["assets"]]
        self.result["assets"] = list(self.journal["assets"])
        self.message("Resuming saved drafts. Pending unsaved drafts must still be open in this Editor; already saved files are hash-checked before proceeding.")
        self.commit()

    def create(self):
        self.preflight()
        self.ensure_feature()
        self.descriptor_paths = self.descriptors()
        self.journal_file = self.journal_path(self.feature_name, self.name)
        self.journal = dict(phase="creating", feature=self.feature.get_path_name(), assets=[], saved={},
                            feature_before=self.disk_hash(self.feature.get_path_name()), inventory_content=[], scans=[])
        self.write_journal()
        if self.recipe == "ItemRecipe":
            created = unreal.AtlasInventoryModAuthoringLibrary.create_inventory_mod_example(
                self.folder, unreal.Name(self.namespace), self.source, self.station)
            if created is None:
                raise RuntimeError("Inventory helper rejected creation; inspect owner log.")
            content, error = created
            if content is None or str(error):
                raise RuntimeError(str(error))
            self.remember(prop(content, "items")[0]); self.remember(prop(content, "recipes")[0]); self.remember(content)
            self.pending_actions.append(content.get_path_name())
            actor_result = unreal.AtlasInventoryModAuthoringLibrary.create_inventory_example_actors(self.folder, self.source, self.station)
            if actor_result is None:
                raise RuntimeError("Station/pickup authoring failed. Inspect the retained assets.")
            station, pickup, failure = actor_result
            if not station or not pickup or str(failure):
                raise RuntimeError(str(failure))
            self.remember(station); self.remember(pickup)
            self.message("Content contribution linked. Place BP_ExampleStation and BP_IngredientPickup in the test host. Add game visuals and route an authorized interaction to Submit Craft; the recipe consumes one ingredient and produces one item.", content)
        elif self.recipe == "NPC":
            result = unreal.AtlasNPCAuthoringLibrary.create_npc_template_assets(
                self.folder, self.owner_name, self.movement, self.behavior, self.work_action)
            if not prop(result, "success"):
                raise RuntimeError("; ".join(str(e) for e in prop(result, "errors")))
            definition, tree, blueprint = [self.remember(prop(result, p)) for p in ("definition", "state_tree", "blueprint")]
            self.add_scan("AtlasNPC", unreal.AtlasNPCDefinition, [definition])
            self.message("Place the Blueprint in your test map and configure visuals/navigation. Worker also needs a target with the selected Work Action.", blueprint)
        elif self.recipe == "InteractiveObject":
            option = self.duplicate(self.source, self.names[0])
            profile = self.create_data(self.names[1], unreal.AtlasInteractionProfile)
            profile.set_editor_property("options", [option])
            blueprint = self.duplicate(self.actor_template, self.names[2])
            failure = unreal.AtlasInteractionTemplateLibrary.configure_actor_variant(blueprint, self.source, profile)
            if str(failure):
                raise RuntimeError(str(failure))
            if not unreal.BlueprintEditorLibrary.compile_blueprint(blueprint):
                raise RuntimeError("Interactive variant failed compilation.")
            self.message("Working actor graph/components copied. Configure the new option, place the variant in its test host, and exercise its server execution. Original assets were not changed.", blueprint)
        elif self.recipe == "LuaBehavior":
            script = self.create_data("DA_LuaBehavior", unreal.AtlasLuaScript)
            spec = importlib.util.spec_from_file_location("atlas_lua_door_example", self.lua_example_path)
            example = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(example)
            blueprint = example.create_actor(self.folder, script, self.lua_event, self.lua_group, self.remember)
            self.message("Place BP_LuaActor in your floor and call TriggerScript from an authorized interaction. It reads Door State, passes a copied context to Lua API 2, filters the returned channel and calls Set Door Opened. Live changes and quiet restore project the same panel pose. SaveState uses world group " + self.lua_group + "; disk writes remain explicit. BeginPlay only reads the door state; it does not run Lua.", blueprint)
        else:
            experience = self.duplicate(self.source, self.names[0])
            pack = self.create_data(self.names[1], unreal.AtlasGameplayExperiencePack, unreal.AtlasGameplayExperiencePackFactory())
            fragment = unreal.new_object(unreal.AtlasGameplayGameFeatureFragment, outer=pack)
            fragment.set_editor_property("contribution_id", self.namespace)
            fragment.set_editor_property("plugin_names", [self.feature_name])
            pack.set_editor_property("fragments", [fragment])
            ids = list(prop(experience, "pack_ids"))
            if not ids and prop(experience, "packs"):
                raise ValueError("Migrate the base Experience's legacy Packs to Pack IDs with the owner migration tool first.")
            ids.append(unreal.PrimaryAssetId(unreal.PrimaryAssetType("AtlasGameplayExperiencePack"), prop(pack, "pack_id")))
            experience.set_editor_property("pack_ids", ids)
            self.add_scan("AtlasGameplayExperience", unreal.AtlasGameplayExperienceDefinition, [experience])
            self.add_scan("AtlasGameplayExperiencePack", unreal.AtlasGameplayExperiencePack, [pack])
            self.message("Independent Experience snapshot plus feature Pack. Later edits to the base root are not inherited; referenced packs remain shared.", experience)
        self.journal.update(phase="prepared", assets=[a.get_path_name() for a in self.assets],
                            inventory_content=self.pending_actions, scans=self.pending_scans)
        self.write_journal()
        self.commit()

    def server_pie_world(self):
        for world in unreal.EditorLevelLibrary.get_pie_worlds(True):
            state = unreal.GameplayStatics.get_game_state(world)
            if state and state.has_authority():
                return world
        raise ValueError("Start standalone or listen-server PIE with the mod active.")

    def measure_shot(self):
        import math
        world = self.server_pie_world()
        target_tag = self.request.get("damage_target_tag")
        if not target_tag or target_tag == "None":
            raise ValueError("Set Damage Target Tag to the actor tag of a single practice target in Play / Checks.")
        targets = unreal.GameplayStatics.get_all_actors_with_tag(world, target_tag)
        if len(targets) != 1:
            raise ValueError(f"Expected one target tagged {target_tag}; found {len(targets)}.")
        component = targets[0].get_component_by_class(self.require("AtlasHealthComponent"))
        if not component or component.get_current_health() <= 0:
            raise ValueError("Use a living practice target with an Atlas Health component.")
        value = component.get_current_health()
        key = (hash(world), targets[0].get_path_name(), target_tag)
        state = getattr(unreal, "_atlas_modkit_shots", {})
        if state.get("key") != key:
            state = {"key": key, "shots": []}
        stages = ["without the part", "with the part installed", "after removing the part"]
        stage = len(state["shots"])
        if "before" not in state:
            state["before"] = value
            unreal._atlas_modkit_shots = state
            self.result.update(success=True, summary=f"Target HP {value:g}. Fire one comparable shot {stages[stage]} and measure again.")
            return
        if value <= 0 or value >= state["before"]:
            raise ValueError("The target must survive one damaging shot. Restore the target and restart PIE if the measurement was interrupted.")
        state["shots"].append(state.pop("before") - value)
        if len(state["shots"]) < 3:
            self.result.update(success=True, summary=f"Recorded {state['shots'][-1]:g} damage. Prepare the same weapon {stages[stage+1]} and measure before firing.")
            return
        original, modified, removed = state["shots"]
        unreal._atlas_modkit_shots = {}
        passed = not math.isclose(modified, original, rel_tol=1e-4, abs_tol=1e-4) and math.isclose(original, removed, rel_tol=1e-4, abs_tol=1e-4)
        self.result.update(success=passed, summary=f"Observed damage: baseline {original:g}, installed {modified:g}, removed {removed:g}.",
                           baseline=original, installed=modified, removed=removed)

    def profile_setting(self, capture):
        setting = self.request.get("profile_setting_id")
        if not setting or setting == "None":
            raise ValueError("Choose the stable Profile Setting Id under Play / Checks.")
        world = self.server_pie_world()
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        library = unreal.get_default_object(unreal.load_class(None, "/Script/Engine.SubsystemBlueprintLibrary"))
        settings = None
        for name in ("AtlasPersistentSettingsSubsystem", "AtlasLocalPlayerSubsystem"):
            owner = getattr(unreal, name, None)
            if owner:
                settings = library.call_method("GetLocalPlayerSubSystemFromPlayerController", (pc, owner.static_class()))
                if settings:
                    break
        if not settings or settings.get_readiness() not in (unreal.AtlasReadiness.READY, unreal.AtlasReadiness.OFFLINE) or not settings.get_current_account_id():
            raise ValueError("Open the same local account profile and wait for settings to load.")
        resolved = settings.get_effective_value(setting)
        if not resolved.found:
            raise ValueError("No registered value for setting " + setting)
        platform = unreal.GameplayStatics.get_platform_name()
        profile = hashlib.sha256(settings.get_current_account_id().encode("utf-8")).hexdigest()
        identity = json.dumps([setting, platform, profile], ensure_ascii=False)
        path = self.project / "Saved/AtlasAuthoring/Settings" / (hashlib.sha256(identity.encode("utf-8")).hexdigest() + ".json")
        row = dict(setting=setting, platform=platform, value=resolved.value.export_text(), origin=str(resolved.origin))
        run = [os.getpid(), hash(settings)]
        if capture:
            origins = unreal.AtlasSettingValueOrigin
            if resolved.origin not in (origins.MACHINE, origins.ACCOUNT, origins.PRODUCT_PROFILE, origins.CONTEXT):
                raise ValueError("Change this option from its default and Apply before capturing the profile.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(run=run, observed=row), indent=2), encoding="utf-8")
            self.result.update(success=True, summary=f"Captured {setting} from {row['origin']} on {platform}. Restart PIE, open the same profile and compare.", setting=row)
            return
        if not path.exists():
            raise ValueError("No capture for this setting, platform and local profile.")
        baseline = json.loads(path.read_text(encoding="utf-8"))
        if baseline["run"] == run:
            raise ValueError("Restart the play session and reload the same profile before comparing.")
        matched = baseline["observed"] == row
        self.result.update(success=matched, summary=f"{setting} {'matches' if matched else 'differs from'} the saved capture on {platform}.",
                           before=baseline["observed"], after=row)

    def quest_receipts(self, capture):
        feature = load(self.request.get("feature"), unreal.GameFeatureData)
        name = feature.get_path_name().split("/")[1]
        world = self.server_pie_world()
        rows = {}
        for owner in unreal.GameplayStatics.get_all_actors_of_class(world, unreal.Actor):
            for manager in owner.get_components_by_class(self.require("AtlasQuestManagerComponent")):
                for view in manager.query_quests(unreal.AtlasQuestListFilter.ALL):
                    if not view.definition:
                        continue
                    prefix = "/" + name + "/"
                    asset = unreal.SystemLibrary.get_soft_object_reference_from_primary_asset_id(view.definition_id)
                    asset_path = asset.get_path_name() if isinstance(asset, unreal.Object) else str(asset or "")
                    if not any(path.startswith(prefix) for path in (asset_path, view.definition.get_path_name(),
                                                                   view.definition.get_class().get_path_name())):
                        continue
                    receipts = sorted(r.transaction_id.export_text() for r in manager.get_quest_reward_receipts(view.instance_id))
                    if len(set(receipts)) != len(receipts):
                        raise ValueError("Duplicate reward receipt: " + view.definition.get_path_name())
                    if receipts:
                        rows[view.instance_id.export_text()] = {"definition": view.definition_id.export_text(),
                                                               "lifecycle": str(view.lifecycle), "receipts": receipts}
        path = self.project / "Saved/AtlasAuthoring/QuestReceipts" / (name + ".json")
        if capture:
            if not rows:
                raise ValueError("Complete a quest from this feature and acknowledge its reward before capture.")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
            self.result.update(success=True, summary=f"Captured {len(rows)} rewarded quests. Save, reload, revisit the reward and compare.", receipts=rows)
        else:
            if not path.exists():
                raise ValueError("Capture the rewarded quest receipts before saving.")
            baseline = json.loads(path.read_text(encoding="utf-8"))
            differences = [key for key in baseline if baseline[key] != rows.get(key)]
            self.result.update(success=not differences, summary="Quest receipts and lifecycle match the capture."
                               if not differences else "Changed or missing quest instances: " + ", ".join(differences),
                               before=baseline, after=rows)

    def trace_interaction(self):
        bindings = getattr(unreal, "_atlas_modkit_interaction_bindings", {})
        live = {}
        def receiver(path):
            def failed(code, detail):
                sender = unreal.find_object(None, path)
                if sender:
                    message = unreal.AtlasInteractionFailureLibrary.get_interaction_failure_text(code, detail)
                    unreal.SystemLibrary.print_string(sender, f"{code}: {message}", duration=5.0)
            return failed
        worlds = unreal.EditorLevelLibrary.get_pie_worlds(True)
        for world in worlds:
            pc = unreal.GameplayStatics.get_player_controller(world, 0)
            if not pc or not pc.is_local_controller():
                continue
            for actor in (pc, pc.get_controlled_pawn(), prop(pc, "player_state")):
                if not actor:
                    continue
                for manager in actor.get_components_by_class(self.require("AtlasInteractionManagerComponent")):
                    path = manager.get_path_name()
                    handler = bindings.get(path) or receiver(path)
                    manager.on_interaction_failed_detailed.add_callable_unique(handler)
                    live[path] = handler
        unreal._atlas_modkit_interaction_bindings = live
        if not live:
            raise ValueError("Start PIE with a local player and an Interaction Manager.")
        self.result.update(success=True, summary=f"Tracing rejected interactions on {len(live)} local player manager(s). Retry the interaction; see the reason in the viewport and Output Log.")

    def craft_exchange(self):
        """Observe a player's authoritative inventory before and after a real station interaction."""
        feature = load(self.request.get("feature"), unreal.GameFeatureData)
        mount = "/" + feature.get_path_name().split("/")[1]
        paths = unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path(mount, recursive=True)
        recipes = [a.get_asset() for a in paths if str(a.asset_class_path.asset_name) == "AtlasCraftingRecipeDefinition"]
        if len(recipes) != 1:
            raise ValueError("Select the starter Game Feature containing exactly one recipe.")
        recipe = recipes[0]
        ingredients, effects = list(prop(recipe, "ingredients")), list(prop(recipe, "effects"))
        products = list(prop(effects[0], "product_specs")) if len(effects) == 1 and isinstance(effects[0], unreal.AtlasCraftingProduceItemsEffect) else []
        if len(ingredients) != 1 or len(prop(ingredients[0], "accepted_definitions")) != 1 or len(products) != 1:
            raise ValueError("This exchange check requires one input definition and one Produce Items result.")
        ingredient = prop(ingredients[0], "accepted_definitions")[0]
        product = prop(products[0], "item_definition")
        if not ingredient or not product or ingredient == product:
            raise ValueError("Choose distinct ingredient and product definitions for this check.")
        world = self.server_pie_world()
        pc = unreal.GameplayStatics.get_player_controller(world, 0)
        if not pc or not pc.get_controlled_pawn():
            raise ValueError("Start standalone or listen-server PIE with a possessed player.")
        owners = [pc, pc.get_controlled_pawn(), prop(pc, "player_state")]
        containers = [c for actor in owners if actor for c in actor.get_components_by_class(unreal.AtlasInventoryContainerComponent)]
        if not containers:
            raise ValueError("The possessed player has no inventory containers.")
        amounts = tuple(sum(c.get_total_stack_count_by_definition(item) for c in containers) for item in (ingredient, product))
        if prop(products[0], "min_quantity") != prop(products[0], "max_quantity"):
            raise ValueError("Choose a fixed output quantity for this exchange check.")
        expected = (-prop(ingredients[0], "quantity"), prop(products[0], "min_quantity"))
        previous = getattr(unreal, "_atlas_modkit_craft_baseline", None)
        key = (hash(world), hash(pc.get_controlled_pawn()), recipe.get_path_name())
        if not previous or previous[0] != key:
            if amounts[0] < -expected[0]:
                raise ValueError(f"Give this player at least {-expected[0]} {ingredient.get_name()} and check again.")
            unreal._atlas_modkit_craft_baseline = (key, amounts)
            self.result.update(success=True, summary=f"Recorded inventory {amounts}. Use the station once and select Check PIE Craft Exchange again.")
            return
        unreal._atlas_modkit_craft_baseline = None
        change = tuple(after - before for after, before in zip(amounts, previous[1]))
        self.result.update(success=change == expected, summary=f"Authoritative player inventory changed {change}; expected {expected} (ingredient, product).",
                           before=previous[1], after=amounts, recipe=recipe.get_path_name())

    def validate(self):
        self.feature = load(self.request.get("feature"), unreal.GameFeatureData)
        self.feature_name = self.feature.get_path_name().split("/")[1]
        if self.feature_name == "Game":
            raise ValueError("Select a feature in its own plugin mount.")
        self.result["feature"] = self.feature.get_path_name()
        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        data = registry.get_assets_by_path("/" + self.feature_name, recursive=True)
        for entry in data:
            # Map/world traversal is deliberately outside an asset-only validation pass.
            if str(entry.asset_class_path.asset_name) != "World":
                asset = entry.get_asset()
                self.validate_asset(asset)
                if asset and isinstance(asset, unreal.Blueprint) and asset.get_name() == "BP_ExampleStation":
                    sub = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
                    lib = unreal.SubobjectDataBlueprintFunctionLibrary
                    components = [lib.get_object_for_blueprint(lib.get_data(h), asset) for h in sub.k2_gather_subobject_data_for_blueprint(asset)]
                    target_type = getattr(unreal, "AtlasInteractionTargetComponent", None)
                    station_type = getattr(unreal, "AtlasCraftingStationComponent", None)
                    if station_type and any(isinstance(c, station_type) for c in components) and not (target_type and any(isinstance(c, target_type) for c in components)):
                        self.message("This starter station has no Interaction Target component. Connect an authorized Submit Craft through the station or the host and verify it with Measure crafting exchange.", asset, "warning")
        inventory = getattr(unreal, "AtlasProjectValidationLibrary", None)
        if inventory:
            for issue in inventory.validate_inventory_project_assets_in_roots(["/" + self.feature_name], True):
                self.message(prop(issue, "message"), str(prop(issue, "asset_path")), "error" if "ERROR" in str(prop(issue, "severity")) else "warning")
        if self.request.get("test_experience"):
            experience = load(self.request["test_experience"], self.require("AtlasGameplayExperienceDefinition"))
            plan = unreal.AtlasGameplayExperienceRequestPolicyLibrary.get_experience_plan_with_host_policy(experience)
            for diagnostic in prop(plan, "diagnostics"):
                self.message(str(prop(diagnostic, "code")) + ": " + str(prop(diagnostic, "message")), experience,
                             "error" if "ERROR" in str(prop(diagnostic, "severity")) else "warning")
            if not prop(plan, "valid"):
                self.message("Host-policy plan is invalid.", experience, "error")
            activated = set()
            for entry in prop(plan, "fragments"):
                fragment = prop(entry, "fragment")
                if isinstance(fragment, unreal.AtlasGameplayGameFeatureFragment):
                    activated.update(prop(fragment, "plugin_names"))
            if self.feature_name not in activated:
                self.message("Selected Experience does not activate this feature. Add its independent Game Features pack before play.", experience, "error")
            self.message("Host-policy plan resolved. This does not prove actor capabilities, station reachability or gameplay execution.", experience)
        else:
            self.message("No test Experience selected: host composition was not checked.", self.feature, "warning")
        self.fail_if_errors()
        self.result.update(success=True, summary="Asset/selected composition validation completed. Runtime behavior still needs a playtest.")

    def play(self):
        self.validate()
        experience = load(self.request.get("test_experience"), self.require("AtlasGameplayExperienceDefinition"))
        descriptors = self.descriptors()
        descriptor = json.loads(descriptors[self.feature_name].read_text(encoding="utf-8-sig"))
        if descriptor.get("BuiltInInitialFeatureState") != "Registered":
            raise ValueError("Internal play requires the feature's BuiltInInitialFeatureState to be Registered for asset discovery. Activation stays in the Experience.")
        map_value = self.request.get("test_map", "")
        map_data = unreal.EditorAssetLibrary.find_asset_data(map_value)
        if not map_data.is_valid() or str(map_data.asset_class_path.asset_name) != "World":
            raise ValueError("Choose an existing saved test map.")
        map_path = map_value.split(".")[0]
        # The product selection policy accepts this identity before map defaults.
        identity = str(prop(experience, "experience_id"))
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", identity):
            raise ValueError("Test Experience must have a stable, non-empty Experience ID.")
        output = self.project / "Saved/AtlasAuthoring" / ("play-" + uuid.uuid4().hex)
        output.mkdir(parents=True)
        executable = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.engine_dir())) / "Binaries/Win64/UnrealEditor.exe"
        project_file = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path()))
        args = [str(executable), str(project_file), map_path, "-game", "-windowed", "-ResX=1280", "-ResY=720",
                "-nosplash", "-log", "-EnablePlugins=" + self.feature_name, "-Experience=" + identity,
                "-UserDir=" + str(output / "User") + "/", "-abslog=" + str(output / "game.log")]
        if self.request.get("headless", False):
            args.extend(["-nullrhi", "-unattended", "-nosound"])
        process = subprocess.Popen(args, cwd=self.project)
        receipt = dict(args=args, pid=process.pid, experience=experience.get_path_name(), feature=self.feature_name,
                       map=map_path, user_dir=str(output / "User"), status="launched-unverified", log=str(output / "game.log"))
        (output / "launch.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        self.message("Separate play process launched. Check the Ready Experience and perform the recipe's gameplay steps. Log: " + str(output / "game.log"))
        self.result.update(success=True, summary="Play launched; gameplay acceptance has NOT been recorded.", launch=receipt)

    def test_enemy_client(self):
        feature = load(self.request.get("feature"), unreal.GameFeatureData)
        name = feature.get_path_name().split("/")[1]
        selected = [a for a in unreal.EditorUtilityLibrary.get_selected_assets() if isinstance(a, unreal.LeEnemyArchetypeDefinition)]
        if not selected:
            registry = unreal.AssetRegistryHelpers.get_asset_registry()
            selected = [row.get_asset() for row in registry.get_assets_by_path("/" + name, recursive=True)
                        if str(row.asset_class_path.asset_name) == "LeEnemyArchetypeDefinition"]
        if len(selected) != 1 or not selected[0].get_path_name().startswith("/" + name + "/"):
            raise ValueError("Select one enemy archetype in this feature in the Content Browser.")
        pawn = prop(selected[0], "pawn_class")
        if not pawn:
            raise ValueError("The selected archetype needs a pawn class.")
        map_path = self.request.get("test_map", "").split(".")[0]
        map_data = unreal.EditorAssetLibrary.find_asset_data(map_path)
        if not map_data.is_valid() or str(map_data.asset_class_path.asset_name) != "World":
            raise ValueError("Choose a saved multiplayer gameplay map with a player pawn and health.")
        owner = self.descriptors().get("ElevatorCore")
        runner = owner.parent / "Docs/Examples/TestEnemyOnClient.py" if owner else None
        if not runner or not runner.is_file():
            raise ValueError("ElevatorCore enemy test script is unavailable in this installation.")
        output = self.project / "Saved/AtlasAuthoring" / ("enemy-" + uuid.uuid4().hex)
        output.mkdir(parents=True)
        request = output / "request.json"
        culture = self.request.get("preview_culture") or unreal.InternationalizationLibrary.get_current_culture()
        preview = {"culture": culture, "gamepad": self.request.get("preview_gamepad", False),
                   "capture_viewport": self.request.get("capture_client_viewport", True)}
        request.write_text(json.dumps({"enemy": pawn.get_path_name(), "descriptor": str(self.descriptors()[name]),
                                       "preview": preview}), encoding="utf-8")
        executable = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.engine_dir())) / "Binaries/Win64/UnrealEditor.exe"
        project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.get_project_file_path())
        prefix = "-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorPlaySettings]:"
        args = [str(executable), project, map_path, "-EnablePlugins=" + name, "-ExecutePythonScript=" + str(runner),
                "-UserDir=" + str(output / "User") + "/", "-abslog=" + str(output / "editor.log"),
                "-culture=" + culture, "-ini:EditorPerProjectUserSettings:[Internationalization]:PreviewGameLanguage=" + culture,
                "-Multiprocess", "-NoLiveCoding", "-NoSteam", "-NoRedpointEOS", "-NetDriverOverrides=/Script/OnlineSubsystemUtils.IpNetDriver",
                "-ini:Engine:[AtlasOnlineServicesFramework]:bApplyInEditor=False", prefix + "PlayNetMode=PIE_ListenServer",
                prefix + "PlayNumberOfClients=2", prefix + "RunUnderOneProcess=True", prefix + "bLaunchSeparateServer=False"]
        process = subprocess.Popen(args, cwd=self.project, env=dict(os.environ, ATLAS_ENEMY_TEST_REQUEST=str(request)))
        self.result.update(success=True, summary="Remote-player test started. Result: " + str(output / "result.json"), pid=process.pid)

    def packaged(self):
        import runpy
        tool_path = self.project / "Tools/ContentModWorkflow.py"
        if not tool_path.is_file():
            raise ValueError("Cook & Test requires a generated ModKit with Tools/ContentModWorkflow.py.")
        tools = runpy.run_path(str(tool_path))
        feature = load(self.request.get("feature"), unreal.GameFeatureData)
        name = feature.get_path_name().split("/")[1]
        descriptors = self.descriptors()
        if name not in descriptors:
            raise ValueError("Select the GameFeatureData inside the mod plugin.")
        plugin = descriptors[name]
        if not plugin.resolve().is_relative_to(self.project.resolve() / "Plugins/GameFeatures"):
            raise ValueError("Cook & Test only accepts a Game Feature in this ModKit.")
        self.result["feature"] = feature.get_path_name()
        operation = self.request["operation"]
        if operation == "release_summary":
            manifest = tools["read"](plugin.parent / "ams_manifest.json")
            receipt, job = None, None
            try:
                path = tools["current_job"](self.project, plugin)
                job = tools["check_ready"](path)
                receipt = tools["read"](Path(job["Package"]) / "ams_cooked.json")
            except (ValueError, OSError) as error:
                self.message(str(error), severity="warning")
            summary = tools["release_summary"](self.project, manifest, receipt, job)
            self.result.update(success=True, summary="\n".join(f"{k}: {v}" for k, v in summary.items()), release=summary)
            return
        if operation in ("cook_mod", "prepare_publish", "publish_mod", "update_release"):
            self.validate()
            for entry in unreal.AssetRegistryHelpers.get_asset_registry().get_assets_by_path("/" + name, recursive=True):
                asset = entry.get_asset()
                if not asset or self.require("AtlasContentAuthoringOptions").is_asset_dirty(asset):
                    raise ValueError("Save this asset before cooking: " + str(entry.object_path if hasattr(entry, "object_path") else entry.package_name))
        if operation == "cook_mod":
            engine = Path(unreal.Paths.convert_relative_path_to_full(unreal.Paths.engine_dir()))
            job_path = tools["start"](self.project, plugin, engine, self.request.get("game_executable", ""))
            self.message("Cook started in the background. Use Build Status; diagnostics: " + str(job_path.parent))
            self.result.update(success=True, summary="Cook started. Editing can continue, but changing this mod invalidates the result.", job=str(job_path))
            return
        job_path = tools["current_job"](self.project, plugin)
        job = tools["read"](job_path)
        if operation in ("playtest_pass", "playtest_fail"):
            verdict = tools["record_playtest"](job_path, operation == "playtest_pass")
            self.result.update(success=True, summary="Private gameplay test: " + verdict)
            return
        if operation == "cook_status":
            self.message("Build status: " + job["Status"] + ". " + job.get("Error", "") + " Report: " + str(job_path))
            next_action = {
                "starting": "Use Build Status again when cooking has started.",
                "cooking": "The cook is in progress. Check Build Status again.",
                "failed": job.get("Error") or "Open the job log, correct the failure and cook again.",
                "cooked": "Choose Install Test Copy to test these cooked files.",
                "installed": "Choose Launch Game to test the installed copy.",
                "launched-unverified": "Check the change in the game, then publish privately or update the existing release.",
            }.get(job["Status"], "Inspect the job log.")
            self.result.update(success=job["Status"] != "failed", summary=f'Build: {job["Status"]}. {next_action}', job=job)
            return
        job = tools["check_ready"](job_path)
        if operation in ("publish_mod", "update_release"):
            provider = self.request.get("publish_provider", "SteamWorkshop")
            if provider not in ("SteamWorkshop", "ModIo"):
                raise ValueError("Choose Steam Workshop or mod.io for direct publishing. Use Export Bundle for manual delivery.")
            python = Path(job["Engine"]) / "Engine/Binaries/ThirdParty/Python3/Win64/python.exe"
            command = [str(python), "-I", str(self.project / "Tools/WizardStoreUpload.py"),
                       str(job_path), provider, self.request.get("published_item_id", "")]
            if operation == "update_release":
                if not self.request.get("published_item_id") or not self.request.get("confirm_publish_target"):
                    raise ValueError("Enter the existing store item ID and confirm the target before updating a release.")
                command.append("--update-release")
            if self.request.get("confirm_publish_target", False):
                command.append("--confirm-existing")
            subprocess.Popen(command, cwd=self.project, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.result.update(success=True, summary="Review the target and confirm the upload in the publishing window. It will show the store receipt or the reason for failure.")
            return
        if operation == "prepare_publish":
            publish_tools = runpy.run_path(str(self.project / "Tools/PublishContentMod.py"))
            result = publish_tools["prepare"](job_path, self.request.get("publish_provider", "SteamWorkshop"),
                self.request.get("published_item_id", ""), self.request.get("confirm_publish_target", False))
            self.message("Verified cooked upload prepared. No network upload was performed. Follow " + result["Guide"])
            self.result.update(success=True, summary="Prepared, not uploaded. Follow PUBLISH.html for store sign-in, upload and download checks.", publication=result)
            if not self.request.get("headless", False):
                unreal.SystemLibrary.launch_url(Path(result["Guide"]).as_uri())
            return
        installed = job_path.parent / "TestInstall"
        if job["Status"] == "cooked":
            settings = unreal.get_default_object(self.require("AtlasModdingDeveloperSettings"))
            previous = unreal.DirectoryPath()
            previous.import_text(prop(settings, "installed_content_root").export_text())
            destination = unreal.DirectoryPath(path=str(installed))
            try:
                settings.set_editor_property("installed_content_root", destination)
                result = unreal.AMSModAuthoringBlueprintLibrary.install_mod_locally_for_testing(job["Package"], False, False)
                if isinstance(result, tuple): result = result[-1]
                if result is None or not prop(result, "success"):
                    raise ValueError("Native install failed: " + (str(prop(result, "messages")) if result else "no result"))
                job.update(Status="installed", InstalledRoot=str(installed), InstallAttempt=str(prop(result, "install_attempt_root")),
                           InstalledModRoot=str(prop(result, "installed_mod_root")))
                job["InstalledFingerprint"] = tools["installed_fingerprint"](job["InstalledModRoot"])
                tools["write"](job_path, job)
            finally:
                settings.set_editor_property("installed_content_root", previous)
        if operation == "install_mod":
            self.message("Installed an isolated test copy using the native installer. Journal: " + job["InstallAttempt"])
            self.result.update(success=True, summary="Test copy installed. Choose Launch Game to play it.", job=job)
            return
        # Every launch receives a separate user directory; normal saves and content preferences stay outside it.
        user = job_path.parent / ("Play-" + uuid.uuid4().hex)
        user.mkdir()
        executable = Path(job["GameExecutable"])
        command = [str(executable), "-windowed", "-ResX=1280", "-ResY=720", "-nosplash", "-log",
                   "-UserDir=" + str(user) + "/", "-abslog=" + str(user / "game.log"),
                   '-ini:Game:[/Script/AtlasModdingSystemRuntime.AtlasModdingDeveloperSettings]:InstalledContentRoot=(Path="' + installed.as_posix() + '")']
        if self.request.get("headless", False):
            command.extend(["-nullrhi", "-unattended", "-nosound", "-NoSteam"])
        process = subprocess.Popen(command, cwd=executable.parent)
        launch = dict(Status="launched-unverified", Pid=process.pid, Command=command, UserDir=str(user), Log=str(user / "game.log"))
        tools["write"](user / "launch.json", launch)
        job.update(Status="launched-unverified", LastLaunch=str(user / "launch.json"))
        job.pop("AuthorPlaytest", None)
        tools["write"](job_path, job)
        self.message("Game launched with the isolated mod installation. In Mods, enable the mod if disabled; include it when hosting a local session. Launching alone does not prove activation or gameplay. Log: " + launch["Log"])
        self.result.update(success=True, summary="Game launched; activation and gameplay still require a playtest.", launch=launch)

    def run(self):
        try:
            operation = self.request.get("operation", "preview")
            if operation == "preview":
                self.preflight()
                self.result.update(success=True, summary="Preflight passed. Planned assets are listed below; nothing was created.")
            elif operation == "craft_exchange":
                self.craft_exchange()
            elif operation in ("capture_quest", "compare_quest"):
                self.quest_receipts(operation == "capture_quest")
            elif operation == "trace_interaction":
                self.trace_interaction()
            elif operation == "measure_shot":
                self.measure_shot()
            elif operation in ("capture_setting", "compare_setting"):
                self.profile_setting(operation == "capture_setting")
            elif operation in ("release_summary", "cook_mod", "cook_status", "install_mod", "launch_mod", "playtest_pass", "playtest_fail", "prepare_publish", "publish_mod", "update_release"):
                self.packaged()
            elif operation in ("create", "resume", "validate", "play", "test_enemy_client"):
                getattr(self, operation)()
            else:
                raise ValueError("Unknown operation: " + operation)
        except Exception as exc:
            if self.journal and self.journal["phase"] == "creating":
                # No pre-existing package is ever in this list (preflight rejects each destination).
                # Cleanup happens synchronously before returning control to the author.
                leftovers = []
                for name in reversed(self.names):
                    path = self.folder + "/" + name
                    if unreal.EditorAssetLibrary.does_asset_exist(path) and not unreal.EditorAssetLibrary.delete_asset(path):
                        leftovers.append(path)
                self.journal.update(phase="creation_failed", retained=leftovers, error=str(exc))
                self.write_journal()
                self.message("Preparation failed before linking the feature. New drafts were removed; retry the same name. Retained paths: " + str(leftovers))
            self.message(str(exc), severity="error")
            self.result.update(success=False, summary="Stopped: " + str(exc))
            unreal.log_warning(self.result["summary"])
        return self.result


def run_request_file(path):
    path = Path(path)
    result = Authoring(json.loads(path.read_text(encoding="utf-8-sig"))).run()
    Path(str(path) + ".result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result
