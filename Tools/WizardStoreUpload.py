# Copyright Callback LLP. All Rights Reserved.
"""Publish a verified ModKit cook in a separate process so Unreal stays responsive."""
import argparse
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import queue
import sys
import threading
import webbrowser

# The editor launches this file with isolated Python. Only import adjacent ModKit tools.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ModIoPublisher
import ContentModWorkflow as workflow
import PublishContentMod as packages
import SteamWorkshopMetadata as workshop


@contextmanager
def locked(path):
    import msvcrt
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise RuntimeError("Another upload of this mod to this store is still running.") from None
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    packages.write(temporary, state)
    os.replace(temporary, path)


def publish(job_path, provider, existing="", confirmed=False, agreed=False, notify=lambda text: None,
            email_login=None, *, update_release=False):
    job_path = Path(job_path).resolve(strict=True)
    job = packages.read(job_path)
    project = Path(job["Project"])
    config = packages.read(project / "Config/ModKitPublishing.json")
    if provider not in ("SteamWorkshop", "ModIo"):
        raise ValueError("Select Steam Workshop or mod.io.")
    if update_release and (not existing or not confirmed):
        raise ValueError("Enter and confirm the item ID to update an existing release.")
    if existing and not confirmed:
        raise ValueError("Confirm the existing store item in the wizard before uploading.")
    author = packages.read(Path(job["Plugin"]).parent / "ams_manifest.json")
    content = author["contentId"]
    key = hashlib.sha256((provider + ":" + config[provider]["GameId"] + ":" + content).encode()).hexdigest()
    folder = project / "Saved/AtlasAuthoring/StoreTargets"
    state_path = folder / (key + ".json")
    with locked(folder / (key + ".lock")):
        state = packages.read(state_path) if state_path.exists() else {}
        item = str(state.get("Item", ""))
        previous = Path(state["Bundle"]) if state.get("Bundle") else None
        if previous:
            for filename, field in (("workshop-target.json", "PublishedFileId"), ("modio-target.json", "Id")):
                target = previous / filename
                if target.is_file():
                    item = str(packages.read(target)[field])
        if existing and item and existing != item:
            raise ValueError("This ContentId is already bound to item " + item)
        if previous and not item and not existing and any(previous.glob(".*-create-pending")):
            raise RuntimeError("The result of the previous creation is unknown. Find the item in your store account and confirm its ID in the wizard.")
        notify("Checking the saved sources, game build and cooked files...")
        record = packages.prepare(job_path, provider, existing or item, confirmed or bool(item), create_modio=True, update_release=update_release)
        bundle = Path(record["Bundle"])
        # Keep the creation receipt across preparing a fresh bundle if the first transfer was interrupted.
        if provider == "SteamWorkshop" and previous and (previous / "workshop-target.json").is_file():
            receipt = packages.read(previous / "workshop-target.json")
            if receipt.get("ContentId") == content and str(receipt.get("PublishedFileId")) == (existing or item):
                packages.write(bundle / "workshop-target.json", receipt)
        state = dict(Bundle=str(bundle), Item=existing or item)
        save_state(state_path, state)
        client = None
        try:
            if provider == "SteamWorkshop":
                library = Path(record["SteamApiLibrary"])
                if packages.digest(library) != record["SteamApiSha256"]:
                    raise ValueError("Steamworks changed since verification.")
                client = workshop.Steam(library, int(record["GameId"]))
                notify("Uploading Workshop item and verifying its release metadata...")
                result = workshop.upload(client, bundle, packages.read(bundle / "publish.json"))
            else:
                api = ModIoPublisher.ModIo(config["ModIo"])
                if email_login:
                    email_login(api)
                else:
                    candidates = {p.resolve() for parent in list(Path(job["GameExecutable"]).parents)[:4]
                                  for p in parent.glob("Engine/Binaries/ThirdParty/Steamworks/Steamv164/Win64/steam_api64.dll")}
                    if len(candidates) != 1:
                        raise ValueError("Choose Steam's installed KLETKA game or sign in to mod.io by email.")
                    client = workshop.Steam(candidates.pop(), int(config["SteamWorkshop"]["GameId"]))
                    notify("Signing in to mod.io with the Steam account...")
                    api.authenticate(client, agreed)
                notify("Uploading the mod.io release and checking the file hash...")
                result = ModIoPublisher.publish(api, bundle, record, state_path.with_suffix(".multipart"))
            save_state(state_path, dict(Bundle=str(bundle), Item=result["PublishedFileId"]))
            return result
        finally:
            if client:
                client.close()


def dialog(args):
    import tkinter as tk
    from tkinter import ttk, messagebox, simpledialog
    root = tk.Tk()
    action = "Update existing release" if args.update_release else "Publish privately"
    root.title("KLETKA ModKit | " + action)
    root.minsize(525, 280)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill="both", expand=True)
    job = packages.read(args.job)
    manifest = packages.read(Path(job["Plugin"]).parent / "ams_manifest.json")
    label = "Steam Workshop" if args.provider == "SteamWorkshop" else "mod.io"
    ttk.Label(frame, text=manifest["profile"]["displayName"], font=("Segoe UI", 14)).pack(anchor="w")
    ttk.Label(frame, text=f'{label}  |  {manifest["release"]["version"]}  |  {job["BaseRelease"]}').pack(anchor="w")
    receipt = packages.read(Path(job["Package"]) / "ams_cooked.json")
    summary = workflow.release_summary(job["Project"], manifest, receipt, job)
    ttk.Label(frame, text="\n".join(f"{k}: {v}" for k, v in summary.items()),
              wraplength=600, justify="left").pack(anchor="w", pady=6)
    ttk.Label(frame, text=("Keep current store visibility. " if args.update_release else "Visibility: Private. ") + ("Update item " + args.item if args.item else "Create or resume this mod's store item.")).pack(anchor="w", pady=5)
    status = tk.StringVar(value="Ready to publish.")
    terms = tk.BooleanVar(value=False)
    method = tk.StringVar(value="Steam")
    if args.provider == "ModIo":
        ttk.Combobox(frame, textvariable=method, values=["Steam", "Email"], state="readonly").pack(anchor="w")
        links = ttk.Frame(frame)
        links.pack(anchor="w")
        for title, url in (("Terms of Use", "https://mod.io/terms"), ("Privacy Policy", "https://mod.io/privacy")):
            ttk.Button(links, text=title, command=lambda dest=url: webbrowser.open(dest)).pack(side="left")
        ttk.Checkbutton(frame, text="I agree to the mod.io Terms of Use and Privacy Policy", variable=terms).pack(anchor="w")
    ttk.Label(frame, textvariable=status, wraplength=510).pack(anchor="w", pady=8)
    messages = queue.Queue()
    running = False

    def begin():
        nonlocal running
        if running:
            return
        use_email = args.provider == "ModIo" and method.get() == "Email"
        address = simpledialog.askstring("mod.io sign-in", "Email address", parent=root) if use_email else None
        agreed = terms.get()
        if use_email and not address:
            return
        if use_email and not agreed:
            status.set("Review and accept the mod.io terms to continue with email sign-in.")
            return
        running = True
        button.state(["disabled"])

        def email_login(api):
            api.request("POST", "/oauth/emailrequest", {"email": address})
            reply = queue.Queue()
            messages.put(("code", reply))
            code = reply.get()
            if not code:
                raise RuntimeError("Email sign-in was cancelled.")
            api.token = api.request("POST", "/oauth/emailexchange", {"email": address, "security_code": code})["access_token"]

        def worker():
            try:
                result = publish(args.job, args.provider, args.item, args.confirm_existing, agreed,
                                 lambda update: messages.put(("status", update)), email_login if use_email else None,
                                 update_release=args.update_release)
                messages.put(("success", result))
            except Exception as error:
                messages.put(("error", str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def refresh():
        nonlocal running
        while not messages.empty():
            kind, value = messages.get_nowait()
            if kind == "code":
                value.put(simpledialog.askstring("mod.io sign-in", "Code from mod.io", parent=root))
            elif kind == "success":
                running = False
                status.set("Upload verified. Item ID " + value["PublishedFileId"])
                button.configure(text="Open store item", command=lambda url=value["Url"]: webbrowser.open(url))
                button.state(["!disabled"])
            elif kind == "error":
                running = False
                status.set(value)
                button.state(["!disabled"])
            else:
                status.set(value)
        root.after(150, refresh)

    def close():
        if running:
            messagebox.showinfo("Upload in progress", "Wait for the store receipt before closing this window.")
        else:
            root.destroy()
    button = ttk.Button(frame, text=action, command=begin)
    button.pack(anchor="e")
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(150, refresh)
    root.mainloop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("provider", choices=("SteamWorkshop", "ModIo"))
    parser.add_argument("item", nargs="?", default="")
    parser.add_argument("--confirm-existing", action="store_true")
    parser.add_argument("--update-release", action="store_true")
    dialog(parser.parse_args())
