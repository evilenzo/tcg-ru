# -*- coding: utf-8 -*-
"""Standalone installer: build the translation and install it in one step.

Install logic plus a console mode; the release .exe is the GUI in installer_gui.py,
which calls into this module (see tools/build_installer.py). Unlike
build_translation.py + install.py it needs no repo checkout: `ru.json` is bundled
into the exe, and the patched asset is written straight into the game folder.

    python tools/installer.py              # interactive: install / update / remove
    python tools/installer.py --restore    # put the original back
    python tools/installer.py --status     # show what is installed
    python tools/installer.py --game "D:/.../TCG Card Shop Simulator" -y

Installs three files: `resources.assets` (I2 table with the Russian column) and the
scenes `level0`/`level1` (Russian button, localized FPS dropdown — see scenepatch.py).
Each gets a `<name>.orig-backup`.

Unlike build_translation.py it does not trust an existing backup blindly: if an
installed file carries no patch, it is the original (possibly a newer one after a
Steam update), so its backup is refreshed from it before building.
"""
import argparse
import filecmp
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i2lib  # noqa: E402
import scenepatch  # noqa: E402
from build_translation import LANG_CODE, load_translation, patch  # noqa: E402

ASSET = "resources.assets"
FILES = (ASSET,) + scenepatch.SCENES

FROZEN = getattr(sys, "frozen", False)
# PyInstaller unpacks bundled data to sys._MEIPASS; from source, use the repo.
BUNDLE = getattr(sys, "_MEIPASS", os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
TRANSLATION = os.path.join(BUNDLE, "translation", "ru.json")
GAME_DIR_NAME = "TCG Card Shop Simulator"
DATA_DIR_NAME = "Card Shop Simulator_Data"


class Fail(Exception):
    pass


def version():
    try:
        with open(os.path.join(BUNDLE, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return "dev"


# ------------------------------------------------------------------ locating the game
def steam_libraries():
    """Steam library roots from the registry and libraryfolders.vdf (Windows only)."""
    try:
        import winreg
    except ImportError:
        return []
    roots = []
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.append(os.path.normpath(winreg.QueryValueEx(k, value)[0]))
        except OSError:
            pass
    libs = list(roots)
    for root in roots:
        try:
            with open(os.path.join(root, "steamapps", "libraryfolders.vdf"), encoding="utf-8") as f:
                vdf = f.read()
        except OSError:
            continue
        for path in re.findall(r'"path"\s+"([^"]+)"', vdf):
            libs.append(os.path.normpath(path.replace("\\\\", "\\")))
    seen = set()
    return [p for p in libs if not (p.lower() in seen or seen.add(p.lower()))]


def data_dir_of(game):
    game = game.strip().strip('"')
    for cand in (os.path.join(game, DATA_DIR_NAME), game):
        if os.path.basename(os.path.normpath(cand)) == DATA_DIR_NAME and os.path.isdir(cand):
            return cand
    return None


def detect_game():
    """Data dir found without asking the user, or None."""
    # 1) exe placed inside the game folder (or ru-translation/ next to it)
    here = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
    d = i2lib.find_data_dir(here)
    if d:
        return d
    # 2) Steam libraries
    for lib in steam_libraries():
        d = data_dir_of(os.path.join(lib, "steamapps", "common", GAME_DIR_NAME))
        if d:
            return d
    return None


def find_game(explicit):
    if explicit:
        d = data_dir_of(explicit)
        if not d:
            raise Fail("В папке %s нет %s." % (explicit, DATA_DIR_NAME))
        return d
    d = detect_game()
    if d:
        return d
    print("Не удалось найти игру автоматически.")
    while True:
        path = input("Вставьте путь к папке игры (где лежит Card Shop Simulator.exe): ")
        if not path.strip():
            raise Fail("Путь не указан.")
        d = data_dir_of(path)
        if d:
            return d
        print("Там нет папки %s, попробуйте ещё раз." % DATA_DIR_NAME)


# ------------------------------------------------------------------ asset helpers
def load_table(source, script_ids, in_memory=False):
    """-> (env, obj, src) for the I2 table in `source`.

    in_memory=True reads the file into RAM instead of keeping it open: UnityPy holds
    its file handles, and Windows will not let us replace a file that is open.
    """
    import UnityPy
    if in_memory:
        with open(source, "rb") as f:
            env = UnityPy.load(f.read())
    else:
        env = UnityPy.load(source)
    obj, raw = i2lib.find_language_source(env, script_ids)
    if obj is None:
        raise Fail("Таблица локализации не найдена в %s — версия игры не поддерживается?" % source)
    return env, obj, i2lib.parse(raw)


def russian_terms(src):
    """Terms with Cyrillic in the Russian column (0 if there is no such column)."""
    codes = [l["Code"] for l in src["languages"]]
    if LANG_CODE not in codes:
        return 0
    idx = codes.index(LANG_CODE)
    return sum(1 for t in src["terms"] if any("Ѐ" <= ch <= "ӿ" for ch in t["Languages"][idx]))


def is_patched(name, path, script_ids):
    if name == ASSET:
        _, _, src = load_table(path, script_ids, in_memory=True)
        return russian_terms(src) > 0
    return scenepatch.is_patched(path)


# ------------------------------------------------------------------ actions
def status(data_dir, script_ids):
    for name in FILES:
        path = os.path.join(data_dir, name)
        print("%-17s бэкап: %-4s сейчас: %s" % (
            name, "есть" if os.path.exists(path + ".orig-backup") else "нет",
            "русский" if is_patched(name, path, script_ids) else "оригинал"))


def restore(data_dir):
    restored = 0
    for name in FILES:
        path = os.path.join(data_dir, name)
        if os.path.exists(path + ".orig-backup"):
            replace_file(path + ".orig-backup", path, copy=True)
            restored += 1
    if not restored:
        raise Fail("Бэкапов нет — восстанавливать нечего.\n"
                   "Можно проверить целостность файлов игры в Steam.")
    print("Оригинальные файлы возвращены. Бэкапы оставлены на месте.")


def refresh_backups(data_dir, script_ids):
    """Make sure every file has a backup of the current original."""
    for name in FILES:
        path = os.path.join(data_dir, name)
        backup = path + ".orig-backup"
        if not is_patched(name, path, script_ids):
            # The installed file is an original: fresh game or a Steam update.
            if not os.path.exists(backup):
                print("Делаю бэкап оригинала -> %s" % os.path.basename(backup))
                shutil.copy2(path, backup)
            elif not filecmp.cmp(path, backup, shallow=False):
                print("Игра обновилась — обновляю бэкап %s." % name)
                shutil.copy2(path, backup)
        elif not os.path.exists(backup):
            raise Fail("%s уже с переводом, но бэкапа оригинала нет.\n"
                       "Проверьте целостность файлов игры в Steam и запустите установщик снова."
                       % name)


def build_asset(backup, script_ids):
    """-> (bytes, stats) of resources.assets with the Russian column."""
    env, obj, src = load_table(backup, script_ids)
    codes = [l["Code"] for l in src["languages"]]
    if "en" not in codes:
        raise Fail("В таблице нет английской колонки.")
    stats = patch(src, load_translation(TRANSLATION), codes.index("en"))
    new_raw = i2lib.serialize(src)

    check = i2lib.parse(new_raw)
    n = len(check["languages"])
    if (len(check["terms"]) != len(src["terms"])
            or any(len(t["Languages"]) != n or len(t["Flags"]) != n for t in check["terms"])):
        raise Fail("Собранная таблица не прошла проверку — установка отменена.")
    obj.set_raw_data(new_raw)
    return env.file.save(), stats


def install(data_dir, script_ids):
    print("Проверяю установленные файлы...")
    refresh_backups(data_dir, script_ids)

    print("Собираю перевод (около минуты)...")
    backups = {name: os.path.join(data_dir, name) + ".orig-backup" for name in FILES}
    built = {}
    built[ASSET], stats = build_asset(backups[ASSET], script_ids)
    localize_ids = i2lib.script_path_ids(data_dir, scenepatch.LOCALIZE_DROPDOWN_CLASS)
    for scene in scenepatch.SCENES:
        try:
            built[scene], _ = scenepatch.patch_scene_file(backups[scene], localize_ids)
        except ValueError as e:
            raise Fail("Не удалось пропатчить %s (%s) — версия игры не поддерживается?\n"
                       "Установка отменена, файлы игры не тронуты." % (scene, e))

    # Everything is built; only now touch the game files.
    for name, data in built.items():
        target = os.path.join(data_dir, name)
        tmp = target + ".ru-tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        replace_file(tmp, target)

    total = stats["translated"] + stats["fallback_to_english"]
    print("\nГотово! Переведено %d из %d терминов (%.0f%%), остальное — на английском."
          % (stats["translated"], total, 100.0 * stats["translated"] / total))
    print("Запустите игру и выберите «Русский» в Settings -> Language.")


def replace_file(src, dst, copy=False):
    try:
        if copy:
            shutil.copy2(src, dst)
        else:
            os.replace(src, dst)
    except PermissionError:
        if not copy and os.path.exists(src):
            os.remove(src)
        raise Fail("Не удалось записать %s — закройте игру и попробуйте снова." % dst)


# ------------------------------------------------------------------ main
def ask(prompt, choices):
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return choices[answer]


VERSION_MISMATCH = ("Версии не совпадают. Перевод, скорее всего, встанет, но новые строки\n"
                    "будут на английском. Проверьте, нет ли свежего релиза перевода.\n"
                    "Если игра поведёт себя странно — удалите перевод.")


def versions(data_dir):
    """-> (installed game version, version the translation was made for); None if unknown."""
    return (i2lib.game_version(data_dir),
            i2lib.read_version_file(os.path.join(BUNDLE, "game_version.txt")))


def has_backup(data_dir):
    return any(os.path.exists(os.path.join(data_dir, n) + ".orig-backup") for n in FILES)


def check_game(data_dir):
    """-> I2 script ids; raises Fail if the folder is not a supported game."""
    for name in FILES:
        if not os.path.exists(os.path.join(data_dir, name)):
            raise Fail("Нет файла %s." % os.path.join(data_dir, name))
    script_ids = i2lib.script_path_ids(data_dir, i2lib.I2_CLASS)
    if not script_ids:
        raise Fail("Скрипт локализации не найден — версия игры не поддерживается?")
    return script_ids


def run(args):
    print("Русификатор TCG Card Shop Simulator %s\n" % version())
    data_dir = find_game(args.game)
    print("Игра: %s" % os.path.dirname(data_dir))
    game_ver, made_for = versions(data_dir)
    print("Версия игры: %s, перевод сделан для %s\n" % (game_ver or "?", made_for or "?"))
    if game_ver and made_for and game_ver != made_for:
        print("Внимание: %s\n" % VERSION_MISMATCH)
    script_ids = check_game(data_dir)

    if args.status:
        return status(data_dir, script_ids)
    if args.restore:
        return restore(data_dir)
    if not args.yes:
        if has_backup(data_dir):
            action = ask("1 — установить или обновить перевод\n"
                         "2 — удалить перевод (вернуть оригинал)\n"
                         "0 — выход\n> ", {"1": "install", "2": "restore", "0": None})
        else:
            action = ask("Установить перевод? [Д/н] ",
                         {"": "install", "д": "install", "y": "install",
                          "н": None, "n": None})
        print()
        if action is None:
            return
        if action == "restore":
            return restore(data_dir)
    install(data_dir, script_ids)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description="Установка русификатора TCG Card Shop Simulator")
    ap.add_argument("--game", help="папка игры (по умолчанию ищется автоматически)")
    ap.add_argument("--restore", action="store_true", help="вернуть оригинальный файл")
    ap.add_argument("--status", action="store_true", help="показать, что установлено")
    ap.add_argument("-y", "--yes", action="store_true", help="установить без вопросов")
    args = ap.parse_args()

    code = 0
    try:
        run(args)
    except Fail as e:
        print("\nОшибка: %s" % e)
        code = 1
    except KeyboardInterrupt:
        code = 130
    except Exception:
        import traceback
        traceback.print_exc()
        print("\nНепредвиденная ошибка. Приложите текст выше к issue на GitHub.\n"
              "Вернуть оригинал: запустите установщик с --restore.")
        code = 1

    # Double-clicked exe: keep the console window open so the result can be read.
    if FROZEN and not args.yes:
        try:
            input("\nНажмите Enter, чтобы закрыть окно...")
        except EOFError:
            pass
    sys.exit(code)


if __name__ == "__main__":
    main()
