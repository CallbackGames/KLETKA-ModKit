# Copyright Callback LLP. All Rights Reserved.
"""Private mod.io publication. Bearer tokens and Steam tickets stay in process memory."""
import base64
import ctypes
import hashlib
import http.client
import json
import mimetypes
from pathlib import Path
import shutil
from urllib.parse import urlencode
import uuid
import zipfile

from PublishContentMod import bind_manifest, contained, digest, read, write


class StoreError(RuntimeError):
    def __init__(self, status, response):
        error = response.get("error", {})
        self.status = status
        self.reference = error.get("error_ref")
        message = error.get("message", "No error message returned")
        hint = {
            15024: "Check the game, item ID, and whether the signed-in account has access to this private mod.",
            11019: "Choose Email, or ask the game administrator to enable Steam under Platform authentication.",
            11074: "Review the Terms of Use and Privacy Policy, then select the agreement checkbox to continue.",
            14037: "Ask the game administrator to enable per-platform files and Windows in Platform approvals. Retry to resume the same private item.",
        }.get(self.reference, "")
        super().__init__(f"mod.io HTTP {status} ({self.reference}): {message} {hint}".rstrip())


class ModIo:
    def __init__(self, settings):
        self.game = int(settings["GameId"])
        self.host = f"g-{self.game}.modapi.io"
        self.key = settings["PublicApiKey"]
        self.token = None

    def request(self, method, path, fields=None, file=None, raw=None, headers=None):
        headers = dict(headers or {})
        headers.update({"Accept": "application/json", "User-Agent": "KLETKA ModKit"})
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        else:
            path += ("&" if "?" in path else "?") + urlencode({"api_key": self.key})
        parts = []
        if file:
            field, source = file
            boundary = uuid.uuid4().hex
            for name, value in (fields or {}).items():
                parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
            suffix = source.suffix.lower()
            mime = mimetypes.guess_type("file" + suffix)[0] or "application/octet-stream"
            parts.extend([f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="upload{suffix}"\r\nContent-Type: {mime}\r\n\r\n'.encode(), source, f'\r\n--{boundary}--\r\n'.encode()])
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        elif raw is not None:
            parts.append(raw)
        elif fields is not None:
            parts.append(urlencode(fields).encode())
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if parts or method in ("PUT", "POST"):
            headers["Content-Length"] = str(sum(p.stat().st_size if isinstance(p, Path) else len(p) for p in parts))
        connection = http.client.HTTPSConnection(self.host, timeout=120)
        try:
            connection.putrequest(method, "/v1" + path)
            for name, value in headers.items():
                connection.putheader(name, value)
            connection.endheaders()
            for part in parts:
                if isinstance(part, Path):
                    with part.open("rb") as stream:
                        connection.send(stream)
                else:
                    connection.send(part)
            response = connection.getresponse()
            content = response.read()
            try:
                result = json.loads(content) if content else {}
            except ValueError:
                raise RuntimeError(f"mod.io HTTP {response.status}: response was not JSON") from None
            if not 200 <= response.status < 300:
                raise StoreError(response.status, result)
            return result
        finally:
            connection.close()

    def authenticate(self, steam, agreed):
        class TicketResult(ctypes.Structure):
            _fields_ = [("result", ctypes.c_int)]
        user = steam.call("SteamUser_v023")
        request = steam.dll.SteamAPI_ISteamUser_RequestEncryptedAppTicket
        request.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
        request.restype = ctypes.c_uint64
        get = steam.dll.SteamAPI_ISteamUser_GetEncryptedAppTicket
        get.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        get.restype = ctypes.c_bool
        steam.wait(request(user, None, 0), TicketResult, 154)
        size = ctypes.c_uint32()
        buffer = ctypes.create_string_buffer(4096)
        if not get(user, buffer, len(buffer), ctypes.byref(size)) or not 0 < size.value <= len(buffer):
            raise RuntimeError("Steam could not return the encrypted KLETKA ticket.")
        result = self.request("POST", "/external/steamauth", {
            "appdata": base64.b64encode(buffer.raw[:size.value]).decode("ascii"),
            "terms_agreed": "true" if agreed else "false"})
        self.token = result["access_token"]


def bound_archive(bundle, data, item):
    package = bundle / "Package"
    manifest = bind_manifest(read(package / "ams_manifest.json"), "ModIo", item)
    prepared = Path(data["Archive"])
    archive = bundle / f"{prepared.stem}-{item}.zip"
    temporary = archive.with_suffix(".tmp")
    with zipfile.ZipFile(temporary, "w", allowZip64=True) as result:
        for relative, expected in sorted(data["Files"].items()):
            path = contained(package, relative)
            if digest(path) != expected:
                raise ValueError("Prepared file changed: " + relative)
            info = zipfile.ZipInfo(relative)
            info.compress_type = zipfile.ZIP_DEFLATED
            with result.open(info, "w", force_zip64=True) as dest:
                if relative == "ams_manifest.json":
                    dest.write((json.dumps(manifest, indent=2) + "\n").encode("utf-8"))
                else:
                    with path.open("rb") as src:
                        shutil.copyfileobj(src, dest)
    temporary.replace(archive)
    return archive


def large_upload(client, route, archive, state_path):
    state = read(state_path) if state_path.exists() else {}
    digest_value = digest(archive)
    if state.get("sha256") != digest_value:
        state = client.request("POST", route + "/multipart", {"filename": archive.name})
        state.update(sha256=digest_value, offset=0)
        write(state_path, state)
    uid = urlencode({"upload_id": state["upload_id"]})
    size = archive.stat().st_size
    with archive.open("rb") as stream:
        stream.seek(state["offset"])
        while block := stream.read(50 * 1024 * 1024):
            start = stream.tell() - len(block)
            client.request("PUT", route + "/multipart?" + uid, raw=block, headers={
                "Content-Range": f"bytes {start}-{stream.tell()-1}/{size}",
                "Content-Type": "application/octet-stream",
                "Digest": "sha-256=" + base64.b64encode(hashlib.sha256(block).digest()).decode()})
            state["offset"] = stream.tell()
            write(state_path, state)
    if not state.get("completed"):
        client.request("POST", route + "/multipart/complete?" + uid)
        state["completed"] = True
        write(state_path, state)
    return state["upload_id"]


def check_target(client, item, content_id, require_private=False):
    if not str(item).isascii() or not str(item).isdigit() or int(item) <= 0:
        raise ValueError("Enter a numeric mod.io item ID.")
    page = f"/games/{client.game}/mods/{item}"
    remote = client.request("GET", page)
    metadata = json.loads(remote.get("metadata_blob") or "{}")
    if int(remote["game_id"]) != client.game or metadata.get("content_id") != content_id:
        raise ValueError("The mod.io page is not bound to this ContentId and game. No existing item was overwritten.")
    initial_visibility = int(remote["visible"])
    if require_private and initial_visibility != 0:
        raise ValueError("The selected mod.io item is public. Private publishing requires a hidden item.")
    return initial_visibility


def publish(client, bundle, data, multipart_state):
    route = f"/games/{client.game}/mods"
    item = data["ExistingItemId"]
    preserve = data.get("Visibility") == "Preserve"
    if preserve and not item:
        raise ValueError("An existing mod.io item ID is required to update a release.")
    target = bundle / "modio-target.json"
    pending = bundle / ".modio-create-pending"
    if target.is_file():
        saved = read(target)
        if saved["ContentId"] != data["ContentId"] or (item and item != str(saved["Id"])):
            raise ValueError("Saved mod.io target differs from this release.")
        item = str(saved["Id"])
    profile = {"name": data["Title"], "summary": data["Summary"], "description": data["Description"],
               "metadata_blob": data["MetadataBlob"]}
    logo = contained(bundle / "Package", data["Preview"])
    if not item:
        if pending.exists():
            raise RuntimeError("A previous creation has an unknown outcome. Inspect your mod.io creator dashboard and enter the returned ID before retrying.")
        pending.touch(exist_ok=False)
        try:
            created = client.request("POST", route, dict(profile, visible=0), ("logo", logo))
        except StoreError as error:
            if error.status in (400, 401, 403, 422):
                pending.unlink()
            raise
        item = str(int(created["id"]))
        write(target, {"ContentId": data["ContentId"], "Id": item})
        pending.unlink()
    page = route + "/" + item
    initial_visibility = check_target(client, item, data["ContentId"], require_private=not preserve)
    archive = bound_archive(bundle, data, item)
    with archive.open("rb") as stream:
        md5 = hashlib.file_digest(stream, "md5").hexdigest()
    files = page + "/files"
    matches = client.request("GET", files + "?" + urlencode({"version": data["Version"], "_limit": 100}))["data"]
    matches = [f for f in matches if f.get("version") == data["Version"]]
    if matches and any(f["filehash"]["md5"].lower() != md5 for f in matches):
        raise ValueError("This version already exists with different bytes. Increment the version in the wizard.")
    if matches:
        file_id = matches[0]["id"]
    else:
        fields = {"version": data["Version"], "active": "true", "filehash": md5, "platforms[]": "windows"}
        if data["Changelog"]:
            fields["changelog"] = data["Changelog"]
        if archive.stat().st_size > 100 * 1024 * 1024:
            fields["upload_id"] = large_upload(client, files, archive, multipart_state)
            uploaded = client.request("POST", files, fields)
        else:
            uploaded = client.request("POST", files, fields, ("filedata", archive))
        file_id = uploaded["id"]
    details = client.request("GET", files + "/" + str(file_id))
    if (details["mod_id"] != int(item) or details["version"] != data["Version"] or
            details["filehash"]["md5"].lower() != md5 or details["filesize"] != archive.stat().st_size):
        raise ValueError("mod.io file readback differs from the uploaded archive.")
    client.request("POST", page, profile, ("logo", logo))
    remote = client.request("GET", page)
    if int(remote["visible"]) != initial_visibility or json.loads(remote["metadata_blob"]) != json.loads(data["MetadataBlob"]):
        raise ValueError("mod.io visibility or release metadata did not match after upload.")
    receipt = dict(Status="file-verified" if preserve else "private-file-verified", ContentId=data["ContentId"], PublishedFileId=item,
                   ModFileId=file_id, Url=remote["profile_url"], Visibility="Public" if initial_visibility else "Private",
                   Archive=archive.name, ArchiveSha256=digest(archive), Platforms=details.get("platforms", []))
    write(bundle / "upload-result.json", receipt)
    return receipt
