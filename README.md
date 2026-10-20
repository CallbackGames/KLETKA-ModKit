# KLETKA ModKit

Official ModKit distribution by **CallbackGames**.

**[Download a release](https://github.com/CallbackGames/KLETKA-ModKit/releases)** ·
[Русская инструкция](#русская-инструкция)

This repository contains the installer/updater. The complete Unreal project is supplied
as a ZIP in Releases. Git LFS and an Unreal Engine fork are not required to download it.
Install **Unreal Engine 5.8 separately**. Engine binaries are not included.
If Releases is empty, the first distribution is still awaiting its matching game release.

## Install and update

1. Download this repository using **Code → Download ZIP** and extract it.
2. Close Unreal Editor.
3. In PowerShell, run from that extracted directory (replace the example paths):

   ```powershell
   .\Update-ModKit.ps1 -EngineRoot 'C:\Program Files\Epic Games\UE_5.8' -Directory 'D:\Modding\KLETKA_ModKit'
   ```

   If your computer blocks downloaded scripts, review the files and use
   `Unblock-File .\Update-ModKit.ps1`, then run the command again.

4. Open `KLETKA_ModKit.uproject` in the installed directory. Start with its bundled
   `Docs` guides and authoring playground.
5. Create your mod as a Game Feature plugin under
   `Plugins/GameFeatures/<YourModName>`. Keep your own backup/version control.

Run the **same command** to update. `BlueprintBinary` is the default distribution.
For C++ mod development, use a **separate installation directory** and `-Kind NativeSdk`.
The matching Unreal C++ toolchain is required for compiling a native mod.

Use `-Channel beta-test` only for ModKit releases accompanying that game branch.
Use `-Tag <exact-release-tag>` to install a particular release from the selected channel.
The updater does not install a newer beta over a public-channel installation automatically.

## What happens to my mods?

- The updater only manages the exact files listed in the downloaded release inventory.
- Additional files, your mod plugins and `Saved` settings are retained.
- If you edited a supplied SDK file, the updater stops **before replacing files**.
  Keep your edited copy, compare it with the new SDK, and merge deliberately.
- Supplied files removed in a newer release are deleted only if they still match the
  previous installed copy. Untracked files are not cleaned up.
- SHA-256 hashes are checked for the archive and every extracted file.
- Previous managed files and a recovery journal remain in `.modkit-update`.
  Backups require additional disk space. Keep this directory if you may need to roll back.

After an interrupted update:

```powershell
.\Update-ModKit.ps1 -EngineRoot 'C:\Program Files\Epic Games\UE_5.8' -Directory 'D:\Modding\KLETKA_ModKit' -Recover
```

To undo the last update, use `-Rollback` instead of `-Recover`.
Rollback also stops if it would overwrite subsequent edits.

You may also download and extract a release ZIP manually **into a new directory**.
Do not extract a newer ZIP over an existing modding project: that bypasses the updater's
conflict and backup checks.

## Releases and rights

ModKit releases identify the corresponding **Steam Build ID and branch**.
The publisher checks that build is live in Steam before making the download public.
Ordinary game builds and Perforce submits do not create public ModKit releases.

Perforce is the development source of truth; this GitHub repository is a distribution
entry point. Release archives contain their own licence notices and source-distribution
materials. **Only AtlasLuaFramework is licensed under MIT where its included licence
states so.** That licence does not cover the rest of Atlas, KLETKA or Epic material.
Existing third-party notices and applicable Unreal Engine terms remain in effect.

## Русская инструкция

1. Установите Unreal Engine **5.8** отдельно.
2. Скачайте этот репозиторий через **Code → Download ZIP** и распакуйте.
3. Закройте Unreal Editor и выполните команду выше, указав путь к движку и отдельную
   папку ModKit. Для обычной работы с Blueprint ничего менять в `-Kind` не нужно.
4. Откройте `KLETKA_ModKit.uproject`. Руководства находятся в папке `Docs`.
5. Свои моды создавайте в `Plugins/GameFeatures/<ИмяМода>`.

Для обновления повторите ту же команду. Ваши дополнительные файлы и моды сохраняются.
Если вы изменили файл самой поставки, обновление остановится и укажет конфликт.
Сохраните свою версию и перенесите изменения вручную; не удаляйте мод ради обновления.

`-Recover` восстанавливает состояние после прерванной установки.
`-Rollback` отменяет последнее обновление. Резервные копии файлов поставки лежат
в `.modkit-update`; они не заменяют ваши собственные резервные копии модов.

Архивы публикуются вместе с соответствующим выпуском игры в Steam.
Пока раздел Releases пуст, первая поставка ещё ожидает своего игрового релиза.
