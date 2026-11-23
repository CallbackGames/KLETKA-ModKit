# Copyright Callback LLP. All Rights Reserved.
"""Finalize/read back Atlas Workshop metadata through the installed game's Steamworks API.

No SDK DLL or credentials are distributed. Steam must already be running and signed in.
Flat API signatures/callback layouts match Steamworks 1.64 shipped with UE 5.8.
"""
import argparse
import ctypes as c
import copy
import hashlib
import json
import os
from pathlib import Path
import time


def bind_manifest(manifest, provider, item):
    """Bind delivery metadata without changing cooked containers or their receipt hash."""
    result = copy.deepcopy(manifest)
    aliases = {'ModIo': {'mod.io','modio','mod_io','mod-io'}, 'SteamWorkshop': {'steamworkshop','steam','workshop'}}[provider]
    reference = dict(provider=provider, providerId=str(item), platformKey='Win64', bPreferred=True,
                     bApprovedForPublic=False, bSupportsAutoInstall=True)
    package = result['package']; artifact = package['artifacts']['Win64']
    for owner in (package, artifact):
        references = owner.get('providerReferences', [])
        for old in references:
            if str(old.get('provider','')).strip().casefold() in aliases and old.get('platformKey','Win64') in ('','Win64') and str(old.get('providerId','')) != str(item):
                raise ValueError('This manifest already points to another item for the same provider.')
        owner['providerReferences'] = [r for r in references if not (str(r.get('provider','')).strip().casefold() in aliases and r.get('platformKey','Win64') in ('','Win64'))] + [reference]
    artifact.update(provider=provider, providerId=str(item))
    return result


def bind_bundle(bundle, data, item):
    if data['Provider'] != 'SteamWorkshop' or not item: raise ValueError('A Steam Workshop item is required.')
    path = bundle/'Package/ams_manifest.json'
    if hashlib.sha256(path.read_bytes()).hexdigest() != data['Files']['ams_manifest.json']:
        raise ValueError('Prepared manifest changed before binding the returned item ID.')
    manifest = json.loads(path.read_text(encoding='utf-8-sig'))
    if manifest['contentId'] != data['ContentId']: raise ValueError('Prepared mod identity changed.')
    bound = bind_manifest(manifest,'SteamWorkshop',item)
    changed = bound != manifest
    if changed:
        temporary = bundle/'bound-manifest.json'
        temporary.write_text(json.dumps(bound,indent=2)+'\n',encoding='utf-8')
        os.replace(temporary,path)
        data['Files']['ams_manifest.json'] = hashlib.sha256(path.read_bytes()).hexdigest()
        temporary = bundle/'bound-publish.json'
        temporary.write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
        os.replace(temporary,bundle/'publish.json')
    (bundle/'binding-result.json').write_text(json.dumps(dict(Changed=changed,PublishedFileId=str(item)))+'\n',encoding='utf-8')


class UpdateResult(c.Structure):
    _fields_ = [('result', c.c_int), ('agreement', c.c_bool), ('item', c.c_uint64)]


class CreateResult(c.Structure):
    _fields_ = [('result', c.c_int), ('item', c.c_uint64), ('agreement', c.c_bool)]


class QueryResult(c.Structure):
    _fields_ = [('handle', c.c_uint64), ('result', c.c_int), ('returned', c.c_uint32),
                ('total', c.c_uint32), ('cached', c.c_bool), ('cursor', c.c_char * 256)]


class ItemDetails(c.Structure):
    # SteamUGCDetails_t in the Windows Steamworks 1.64 SDK.
    _fields_ = [
        ('item', c.c_uint64), ('result', c.c_int), ('file_type', c.c_int),
        ('creator_app', c.c_uint32), ('consumer_app', c.c_uint32),
        ('title', c.c_char * 129), ('description', c.c_char * 8000), ('owner', c.c_uint64),
        ('created', c.c_uint32), ('updated', c.c_uint32), ('added', c.c_uint32),
        ('visibility', c.c_int), ('banned', c.c_bool), ('accepted', c.c_bool),
        ('tags_truncated', c.c_bool), ('tags', c.c_char * 1025), ('file', c.c_uint64),
        ('preview_file', c.c_uint64), ('filename', c.c_char * 260), ('file_size', c.c_int32),
        ('preview_size', c.c_int32), ('url', c.c_char * 256), ('up', c.c_uint32),
        ('down', c.c_uint32), ('score', c.c_float), ('children', c.c_uint32), ('total_size', c.c_uint64),
    ]


class Steam:
    def __init__(self, library, app_id):
        self.dll = c.CDLL(str(Path(library).resolve(strict=True)))
        self.functions = {}
        def bind(name, result, *args):
            fn = getattr(self.dll, name); fn.restype = result; fn.argtypes = args
            self.functions[name] = fn
            return fn
        ptr, u64, u32, flag = c.c_void_p, c.c_uint64, c.c_uint32, c.c_bool
        bind('SteamAPI_InitFlat', c.c_int, ptr)
        bind('SteamAPI_Shutdown', None)
        bind('SteamAPI_RunCallbacks', None)
        for name in ('SteamUGC_v021', 'SteamUtils_v010', 'SteamUser_v023'):
            bind('SteamAPI_' + name, ptr)
        bind('SteamAPI_ISteamUser_BLoggedOn', flag, ptr)
        bind('SteamAPI_ISteamUser_GetSteamID', u64, ptr)
        bind('SteamAPI_ISteamUGC_GetQueryUGCResult', flag, ptr, u64, u32, c.POINTER(ItemDetails))
        bind('SteamAPI_ISteamUtils_GetAppID', u32, ptr)
        bind('SteamAPI_ISteamUtils_IsAPICallCompleted', flag, ptr, u64, c.POINTER(flag))
        bind('SteamAPI_ISteamUtils_GetAPICallResult', flag, ptr, u64, ptr, c.c_int, c.c_int, c.POINTER(flag))
        bind('SteamAPI_ISteamUGC_StartItemUpdate', u64, ptr, u32, u64)
        bind('SteamAPI_ISteamUGC_CreateItem', u64, ptr, u32, c.c_int)
        for field in ('Title','Description','Content','Preview'):
            bind('SteamAPI_ISteamUGC_SetItem'+field, flag, ptr, u64, c.c_char_p)
        bind('SteamAPI_ISteamUGC_SetItemVisibility', flag, ptr, u64, c.c_int)
        bind('SteamAPI_ISteamUGC_SetItemMetadata', flag, ptr, u64, c.c_char_p)
        bind('SteamAPI_ISteamUGC_RemoveItemKeyValueTags', flag, ptr, u64, c.c_char_p)
        bind('SteamAPI_ISteamUGC_AddItemKeyValueTag', flag, ptr, u64, c.c_char_p, c.c_char_p)
        bind('SteamAPI_ISteamUGC_SubmitItemUpdate', u64, ptr, u64, c.c_char_p)
        bind('SteamAPI_ISteamUGC_CreateQueryUGCDetailsRequest', u64, ptr, c.POINTER(u64), u32)
        bind('SteamAPI_ISteamUGC_SetReturnMetadata', flag, ptr, u64, flag)
        bind('SteamAPI_ISteamUGC_SetAllowCachedResponse', flag, ptr, u64, u32)
        bind('SteamAPI_ISteamUGC_SendQueryUGCRequest', u64, ptr, u64)
        bind('SteamAPI_ISteamUGC_GetQueryUGCMetadata', flag, ptr, u64, u32, ptr, u32)
        bind('SteamAPI_ISteamUGC_ReleaseQueryUGCRequest', flag, ptr, u64)
        self.previous_env = {key: os.environ.get(key) for key in ('SteamAppId', 'SteamGameId')}
        os.environ.update(SteamAppId=str(app_id), SteamGameId=str(app_id))
        self.initialized = False
        try:
            error = c.create_string_buffer(1024)
            if self.call('InitFlat', error) != 0:
                raise RuntimeError('Start Steam and sign in to the Workshop owner account, then retry. ' + error.value.decode('utf-8', errors='replace'))
            self.initialized = True
            self.ugc = self.call('SteamUGC_v021'); self.utils = self.call('SteamUtils_v010'); user = self.call('SteamUser_v023')
            if not self.ugc or not self.utils or not user or not self.call('ISteamUser_BLoggedOn', user):
                raise RuntimeError('The Steam client has no signed-in Workshop user.')
            if self.call('ISteamUtils_GetAppID', self.utils) != app_id:
                raise RuntimeError('Steam initialized for a different game; no metadata was changed.')
            self.app_id = app_id
            self.user_id = self.call("ISteamUser_GetSteamID", user)
        except Exception:
            self.close()
            raise

    def call(self, name, *args):
        return self.functions['SteamAPI_' + name](*args)

    def close(self):
        if self.initialized:
            self.call('Shutdown'); self.initialized = False
        for key, value in self.previous_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value

    def wait(self, call, cls, callback, timeout=120):
        if not call: raise RuntimeError('Steam rejected the asynchronous request.')
        deadline = time.monotonic() + timeout; failed = c.c_bool()
        while time.monotonic() < deadline:
            self.call('RunCallbacks')
            if self.call('ISteamUtils_IsAPICallCompleted', self.utils, call, c.byref(failed)):
                value = cls()
                if failed.value or not self.call('ISteamUtils_GetAPICallResult', self.utils, call, c.byref(value), c.sizeof(value), callback, c.byref(failed)) or failed.value:
                    raise RuntimeError('Steam could not complete the metadata request.')
                if value.result != 1: raise RuntimeError('Steam metadata operation failed: EResult=' + str(value.result))
                return value
            time.sleep(.05)
        raise TimeoutError('Steam metadata operation timed out; keep this bundle and retry the same item.')

    def query(self, item):
        return self.inspect_item(item)[0]

    def inspect_item(self, item):
        identity = c.c_uint64(item)
        handle = self.call('ISteamUGC_CreateQueryUGCDetailsRequest', self.ugc, c.byref(identity), 1)
        if handle == 2**64-1: raise RuntimeError('Steam could not create the item query.')
        try:
            if not self.call('ISteamUGC_SetReturnMetadata', self.ugc, handle, True) or not self.call('ISteamUGC_SetAllowCachedResponse', self.ugc, handle, 0):
                raise RuntimeError('Steam cannot query fresh item metadata.')
            result = self.wait(self.call('ISteamUGC_SendQueryUGCRequest', self.ugc, handle), QueryResult, 3401)
            if result.handle != handle or result.returned != 1: raise RuntimeError('Workshop item is unavailable to this Steam account.')
            details = ItemDetails()
            if not self.call('ISteamUGC_GetQueryUGCResult', self.ugc, handle, 0, c.byref(details)):
                raise RuntimeError('Steam could not read item visibility and ownership.')
            if (details.result != 1 or details.item != item or details.consumer_app != self.app_id
                    or details.owner != self.user_id):
                raise ValueError('The selected Workshop item must belong to this game and the signed-in owner.')
            buffer = c.create_string_buffer(5000)
            if not self.call('ISteamUGC_GetQueryUGCMetadata', self.ugc, handle, 0, buffer, len(buffer)) or not buffer.value:
                return None, details.visibility
            try:
                return json.loads(buffer.value.decode('utf-8')), details.visibility
            except (ValueError, UnicodeError) as error:
                raise ValueError('This Workshop item has non-Atlas metadata. Select your own matching mod item or create a new private item; no update was made.') from error
        finally: self.call('ISteamUGC_ReleaseQueryUGCRequest', self.ugc, handle)

    def create(self):
        return self.wait(self.call('ISteamUGC_CreateItem',self.ugc,self.app_id,0),CreateResult,3403)

    def update(self, item, metadata, payload=None):
        handle = self.call('ISteamUGC_StartItemUpdate', self.ugc, self.app_id, item)
        if handle == 2**64-1 or not self.call('ISteamUGC_SetItemMetadata', self.ugc, handle, json.dumps(metadata, separators=(',', ':')).encode('utf-8')):
            raise RuntimeError('Steam rejected the Atlas metadata update.')
        content_id = metadata.get('content_id')
        if not content_id or not self.call('ISteamUGC_RemoveItemKeyValueTags', self.ugc, handle, b'atlas_content_id') or not self.call(
                'ISteamUGC_AddItemKeyValueTag', self.ugc, handle, b'atlas_content_id', content_id.encode('utf-8')):
            raise RuntimeError('Steam rejected the searchable cross-store content identity. Nothing was submitted.')
        if payload:
            fields={'Title':payload['Title'],'Description':payload['Description'],'Content':payload['Package']}
            if payload.get('PreviewPath'): fields['Preview']=payload['PreviewPath']
            for field,value in fields.items():
                if not self.call('ISteamUGC_SetItem'+field,self.ugc,handle,str(value).encode('utf-8')):
                    raise RuntimeError('Steam rejected the item '+field.lower()+'.')
            if payload.get('SetPrivate') and not self.call('ISteamUGC_SetItemVisibility',self.ugc,handle,2):
                raise RuntimeError('Steam could not set Private visibility. Nothing was submitted.')
        notes = (payload.get('Changelog') if payload else None) or 'Atlas release metadata'
        result = self.wait(self.call('ISteamUGC_SubmitItemUpdate', self.ugc, handle, notes.encode('utf-8')), UpdateResult, 3404)
        if result.item != item: raise RuntimeError('Steam returned a different Workshop item.')
        if result.agreement: raise RuntimeError('Accept the Steam Workshop agreement on the item page, then retry this same bundle.')


def finalize(client, item, content_id, version, check_only=False):
    current = client.query(item) if item else None
    if current and (not isinstance(current, dict) or current.get('content_id') != content_id):
        raise ValueError('Existing Workshop metadata belongs to another content ID; no update was made.')
    if check_only: return {'Status': 'steam-account-and-target-checked'}
    if not item: raise ValueError('A published Workshop item ID is required.')
    expected = dict(content_id=content_id, ams_version=version)
    client.update(item, expected)
    if client.query(item) != expected:
        raise RuntimeError('Workshop metadata readback differs. Publication is unconfirmed; retry the same item.')
    return dict(Status='upload-metadata-verified', PublishedFileId=str(item), Metadata=expected,
                GameplayAcceptance='requires-fresh-download-and-playtest')


def upload(client, bundle, data):
    if data.get('Provider') != 'SteamWorkshop': raise ValueError('This is not a Workshop bundle.')
    package=(bundle/'Package').resolve()
    actual={p.relative_to(package).as_posix() for p in package.rglob('*') if p.is_file()}
    if actual != set(data['Files']): raise ValueError('Upload file membership changed. Prepare a new bundle.')
    for relative,expected in data['Files'].items():
        path=(package/relative).resolve(strict=True)
        if not path.is_relative_to(package):
            raise ValueError('Upload path escapes the prepared package: '+relative)
        digest=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
        if digest.hexdigest()!=expected:
            raise ValueError('Upload file changed: '+relative)
    target=bundle/'workshop-target.json';pending=bundle/'.steam-create-pending'
    item=int(data.get('ExistingItemId') or 0)
    preserve = data.get('Visibility') == 'Preserve'
    if preserve and not item:
        raise ValueError('Updating a Workshop release requires an existing item ID.')
    created_here = target.is_file()
    new_now = False
    if target.is_file():
        saved=json.loads(target.read_text(encoding='utf-8'))
        if saved['ContentId']!=data['ContentId'] or (item and item!=int(saved['PublishedFileId'])):
            raise ValueError('Stored Workshop item belongs to another target.')
        item=int(saved['PublishedFileId'])
    if not item:
        if pending.exists(): raise RuntimeError('A previous item creation has an unknown outcome. Inspect your Workshop items and use the existing item ID; do not create a duplicate.')
        pending.write_text('Creation started; preserve this marker if Steam returns no item ID.\n',encoding='utf-8')
        created=client.create(); item=int(created.item)
        created_here = True
        new_now = True
        if not item: raise RuntimeError('Steam created no identifiable item. Inspect your Workshop items before retrying.')
        target.write_text(json.dumps(dict(ContentId=data['ContentId'],PublishedFileId=str(item)))+'\n',encoding='utf-8')
        pending.unlink()
        if created.agreement: raise RuntimeError('Workshop item '+str(item)+' was created. Accept the Workshop agreement on its page, then retry this same bundle.')
    metadata, visibility = client.inspect_item(item)
    if metadata is None:
        if not created_here:
            raise ValueError('The existing Workshop item has no Atlas ContentId binding.')
    elif not isinstance(metadata, dict) or metadata.get('content_id') != data['ContentId']:
        raise ValueError('The Workshop item belongs to another content ID.')
    if not preserve and visibility != 2 and not new_now:
        raise ValueError('Use Update Existing Release to update an item that is not private.')
    bind_bundle(bundle,data,item)
    expected=dict(content_id=data['ContentId'],ams_version=data['Version'])
    fingerprint = hashlib.sha256(json.dumps(data['Files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    expected['ams_payload_sha256'] = fingerprint
    if preserve and metadata and metadata.get('ams_version') == data['Version'] and metadata.get('ams_payload_sha256') != fingerprint:
        raise ValueError('Increment the version before replacing the bytes of a Workshop release.')
    payload=dict(data,SetPrivate=new_now,Package=str(package),PreviewPath=str(package/data['Preview']) if data.get('Preview') else '')
    client.update(item,expected,payload)
    actual, final_visibility = client.inspect_item(item)
    if actual != expected or final_visibility != (visibility if preserve else 2):
        raise RuntimeError('Workshop release metadata or visibility differs after upload. Inspect the existing item before retrying.')
    result=dict(Status='upload-metadata-verified',ContentId=data['ContentId'],PublishedFileId=str(item),
                Url='https://steamcommunity.com/sharedfiles/filedetails/?id='+str(item),Visibility={0:'Public',1:'FriendsOnly',2:'Private',3:'Unlisted'}.get(final_visibility,str(final_visibility)),
                GameplayAcceptance='requires-fresh-download-and-playtest')
    (bundle/'upload-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--item-id', default='0')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--require-private', action='store_true')
    parser.add_argument('--confirm-update', action='store_true')
    parser.add_argument('--bind-package', action='store_true')
    parser.add_argument('--upload', action='store_true')
    args = parser.parse_args()
    if args.upload and (not args.confirm_update or args.check or args.bind_package):
        parser.error('--upload requires --confirm-update and cannot be combined with --check or --bind-package.')
    if not args.check and not args.confirm_update and not args.bind_package: parser.error('Explicit --confirm-update is required.')
    data = json.loads((args.bundle/'publish.json').read_text(encoding='utf-8-sig'))
    if not args.item_id.isascii() or not args.item_id.isdecimal() or int(args.item_id) >= 2**64:
        raise ValueError('Invalid Workshop item ID.')
    if args.bind_package:
        bind_bundle(args.bundle,data,int(args.item_id));return
    dll = Path(data['SteamApiLibrary'])
    if hashlib.sha256(dll.read_bytes()).hexdigest() != data['SteamApiSha256']:
        raise ValueError('The installed Steamworks library changed. Prepare a new upload bundle.')
    client = Steam(dll, int(data['GameId']))
    try:
        if args.upload:
            print(json.dumps(upload(client,args.bundle,data)));return
        if args.require_private and int(args.item_id) and client.inspect_item(int(args.item_id))[1] != 2:
            raise ValueError('Private upload requires a private Workshop item.')
        result = finalize(client, int(args.item_id), data['ContentId'], data['Version'], args.check)
        if not args.check:
            (args.bundle/'steam-metadata-result.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result))
    finally: client.close()


if __name__ == '__main__': main()
