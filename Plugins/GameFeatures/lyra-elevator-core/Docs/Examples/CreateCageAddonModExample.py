# Copyright Callback LLP. All Rights Reserved.
import importlib.util
from pathlib import Path

def populate_template(plugin_name, content_id):
    spec=importlib.util.spec_from_file_location('_cage_capability',Path(__file__).with_name('CapabilityModStarter.py'))
    recipe=importlib.util.module_from_spec(spec);spec.loader.exec_module(recipe)
    return recipe.populate_cage(plugin_name,content_id)
