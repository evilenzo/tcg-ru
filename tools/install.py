# -*- coding: utf-8 -*-
"""Install / uninstall the Russian translation.

    python tools/install.py            # back up the original, copy the build in
    python tools/install.py --restore  # put the original back
    python tools/install.py --status   # show what is currently installed

The original `resources.assets` is kept next to it as `resources.assets.orig-backup`,
so the game can always be reverted without a Steam re-download.
"""
import argparse
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i2lib  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD = os.path.join(REPO, "build", "resources.assets")


def md5(path, limit=None):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 22)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def russian_terms(path, data_dir):
    """Number of terms with Cyrillic text in the French column (None if unreadable)."""
    import UnityPy
    ids = i2lib.script_path_ids(data_dir, i2lib.I2_CLASS)
    env = UnityPy.load(path)
    obj, raw = i2lib.find_language_source(env, ids)
    if obj is None:
        return None
    src = i2lib.parse(raw)
    idx = [l["Code"] for l in src["languages"]].index("fr")
    return sum(1 for t in src["terms"]
               if any("Ѐ" <= ch <= "ӿ" for ch in t["Languages"][idx]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", help="game folder (auto-detected by default)")
    ap.add_argument("--restore", action="store_true", help="revert to the original file")
    ap.add_argument("--status", action="store_true", help="report current state")
    ap.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    data_dir = (os.path.join(args.game, "Card Shop Simulator_Data") if args.game
                else i2lib.find_data_dir())
    if not data_dir or not os.path.isdir(data_dir):
        sys.exit("Could not find 'Card Shop Simulator_Data'. Pass --game <game folder>.")

    target = os.path.join(data_dir, "resources.assets")
    backup = target + ".orig-backup"

    if args.status:
        print("game   : %s" % data_dir)
        print("backup : %s" % ("present" if os.path.exists(backup) else "absent"))
        print("build  : %s" % (BUILD if os.path.exists(BUILD) else "not built yet"))
        n = russian_terms(target, data_dir)
        print("installed: %s" % ("unknown" if n is None else
                                 "%d Russian terms in the French slot" % n if n else "original"))
        return

    if args.restore:
        if not os.path.exists(backup):
            sys.exit("No backup at %s — nothing to restore." % backup)
        shutil.copy2(backup, target)
        print("Restored the original resources.assets.")
        print("The backup was kept at %s" % backup)
        return

    if not os.path.exists(BUILD):
        sys.exit("No build found. Run:  python tools/build_translation.py")

    if not os.path.exists(backup):
        print("Backing up the original -> %s" % os.path.basename(backup))
        shutil.copy2(target, backup)
    else:
        print("Backup already exists, keeping it.")

    size = os.path.getsize(BUILD) / 1048576
    print("Installing %s (%.1f MB) -> %s" % (BUILD, size, target))
    if not args.yes:
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Cancelled.")

    shutil.copy2(BUILD, target)
    print("Done. %s Russian terms installed." % russian_terms(target, data_dir))
    print("Start the game and pick Francais in Settings -> Language: it shows Russian.")


if __name__ == "__main__":
    main()
