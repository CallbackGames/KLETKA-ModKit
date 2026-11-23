# Copyright Callback LLP. All Rights Reserved.
import importlib.util
from pathlib import Path


def populate_template(plugin_name, content_id):
    spec = importlib.util.spec_from_file_location('_subtitle_capability', Path(__file__).with_name('CapabilityModStarter.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.populate_subtitles(plugin_name, content_id)
