# Copyright Callback LLP. All Rights Reserved.
"""Optional DA recipe. Provider checks happen before the first new asset is created."""
import importlib.util
from pathlib import Path
import unreal

def populate_template(plugin_name, content_id):
    if not hasattr(unreal, 'LeDungeonArchitectAuthoringLibrary') or not hasattr(unreal, 'LeDungeonArchitectFloorGenerationConfig'):
        raise RuntimeError('Install compatible Dungeon Architect, enable KLETKA Dungeon Architect Adapter, and restart the editor.')
    path = Path(__file__).with_name('CreateFloorModExample.py')
    spec = importlib.util.spec_from_file_location('_kletka_da_floor_base', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def create_map(package_name, unused_layout_class):
        return unreal.LeDungeonArchitectAuthoringLibrary.create_example_map(package_name)
    result = module.populate_template(plugin_name, content_id, _create_map=create_map)
    floor = unreal.load_asset('/' + plugin_name + '/FloorExample/DA_Floor')
    generation = unreal.new_object(unreal.LeFloorGenerationFragment, outer=floor)
    config = unreal.new_object(unreal.LeDungeonArchitectFloorGenerationConfig, outer=generation)
    config.set_editor_property('dungeon_actor_tag', 'KletkaModDungeon')
    config.set_editor_property('generation_by_player_count', {1: unreal.LeDungeonArchitectBuildConfig()})
    generation.set_editor_property('backend_config', config)
    floor.set_editor_property('fragments', [*floor.get_editor_property('fragments'), generation])
    if not unreal.EditorAssetLibrary.save_loaded_asset(floor, only_if_is_dirty=False):
        raise RuntimeError('Could not save the new DA floor configuration.')
    return result
