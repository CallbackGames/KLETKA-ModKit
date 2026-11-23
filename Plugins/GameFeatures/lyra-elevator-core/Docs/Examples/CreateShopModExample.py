# Copyright Callback LLP. All Rights Reserved.
"""Add a mod-owned inventory item to the published KLETKA shop assortment."""
import unreal


def populate_template(plugin_name, content_id):
    folder = '/' + plugin_name + '/ShopExample'
    names = ('DA_ShopItem', 'DA_InventoryContent')
    if any(unreal.EditorAssetLibrary.does_asset_exist(folder + '/' + name) or
           unreal.find_object(None, folder + '/' + name + '.' + name) for name in names):
        raise RuntimeError('Shop starter destination already contains assets.')
    feature = unreal.load_asset('/' + plugin_name + '/' + plugin_name)
    if feature is None or list(feature.get_editor_property('actions')):
        raise RuntimeError('Shop starter requires a new empty Game Feature Data.')
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    factory = unreal.DataAssetFactory()
    factory.set_editor_property('data_asset_class', unreal.AtlasInventoryItemDefinition)
    item = tools.create_asset(names[0], folder, unreal.AtlasInventoryItemDefinition, factory)
    if item is None:
        raise RuntimeError('Could not create the shop item.')
    item.set_editor_property('display_name', 'Example shop item')
    # A visible placeholder makes the first shop run testable before the author supplies artwork.
    world_class = unreal.load_class(None, '/Script/AtlasInventorySystemRuntime.InventoryFragment_WorldActor')
    cube = unreal.load_asset('/Engine/BasicShapes/Cube')
    if world_class is None or cube is None:
        raise RuntimeError('World Presentation or the engine placeholder mesh is unavailable.')
    world = unreal.new_object(world_class, outer=item)
    world.set_editor_property('static_mesh', cube)
    world.set_editor_property('pickup_display_name', 'Example shop item')
    item.set_editor_property('fragments', [world])
    content_class = unreal.load_class(None, '/Script/AtlasInventorySystemRuntime.AtlasInventoryContentSet')
    if content_class is None:
        raise RuntimeError('Inventory content set API is unavailable.')
    factory.set_editor_property('data_asset_class', content_class)
    content = tools.create_asset(names[1], folder, content_class, factory)
    if content is None:
        raise RuntimeError('Could not create inventory registration.')
    content.set_editor_property('content_id', content_id + '.shop')
    content.set_editor_property('items', [item])
    inventory_class = unreal.load_class(None, '/Script/AtlasInventorySystemRuntime.AtlasGameFeatureAction_AddInventoryContent')
    inventory = unreal.new_object(inventory_class, outer=feature)
    inventory.set_editor_property('content', content)
    shop = unreal.new_object(unreal.LeGameFeatureAction_AddShopContent, outer=feature)
    target = unreal.PrimaryAssetId()
    if not target.import_text('ShopAssortment:kletka.shop.default'):
        raise RuntimeError('Could not set the published shop identity.')
    shop.set_editor_property('target_assortment', target)
    offer = unreal.LeShopOffer()
    offer.set_editor_property('offer_id', content_id + '.example')
    offer.set_editor_property('item', item)
    offer.set_editor_property('base_cost', 12)
    offer.set_editor_property('weight', 100.0)
    change = unreal.LeShopOfferChange()
    change.set_editor_property('offer', offer)
    shop.set_editor_property('changes', [change])
    feature.set_editor_property('actions', [inventory, shop])
    assets = [item, content, feature]
    for asset in assets:
        if not unreal.EditorAssetLibrary.save_loaded_asset(asset, only_if_is_dirty=False):
            raise RuntimeError('Could not save ' + asset.get_path_name())
    return {'plugin': plugin_name, 'id': content_id, 'assets': [asset.get_path_name() for asset in assets]}
