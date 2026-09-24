# -*- coding: utf-8 -*-
"""Install / uninstall the Russian translation.

    python tools/install.py            # back up the original, copy the build in
    python tools/install.py --restore  # put the original back
    python tools/install.py --status   # show what is currently installed

Installs `resources.assets` (I2 table with the Russian column) and the scenes
`level0`/`level1` (Russian button, localized FPS dropdown). Each original is kept next
to it as `<name>.orig-backup`, so the game can always be reverted without a Steam
re-download.
"""
import argparse
import hashlib
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i2lib  # noqa: E402
from installer import FILES, is_patched  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BUILD_DIR = os.path.join(REPO, "build")


def md5(path, limit=None):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 22)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", help="game folder (auto-detected by default)")
    ap.add_argument("--restore", action="store_true", help="revert to the original files")
    ap.add_argument("--status", action="store_true", help="report current state")
    ap.add_argument("-y", "--yes", action="store_true", help="do not ask for confirmation")
    args = ap.parse_args()

    data_dir = (os.path.join(args.game, "Card Shop Simulator_Data") if args.game
                else i2lib.find_data_dir())
    if not data_dir or not os.path.isdir(data_dir):
        sys.exit("Could not find 'Card Shop Simulator_Data'. Pass --game <game folder>.")

    # (name, installed file, backup, build output)
    files = [(n, os.path.join(data_dir, n), os.path.join(data_dir, n) + ".orig-backup",
              os.path.join(BUILD_DIR, n)) for n in FILES]

    if args.status:
        script_ids = i2lib.script_path_ids(data_dir, i2lib.I2_CLASS)
        print("game   : %s" % data_dir)
        for name, dst, backup, build in files:
            print("%-17s backup: %-7s build: %-7s installed: %s" % (
                name, "present" if os.path.exists(backup) else "absent",
                "present" if os.path.exists(build) else "absent",
                "russian" if is_patched(name, dst, script_ids) else "original"))
        return

    if args.restore:
        restored = 0
        for name, dst, backup, _ in files:
            if os.path.exists(backup):
                shutil.copy2(backup, dst)
                print("Restored the original %s (backup kept)." % name)
                restored += 1
        if not restored:
            sys.exit("No backups in %s — nothing to restore." % data_dir)
        return

    missing = [build for _, _, _, build in files if not os.path.exists(build)]
    if missing:
        sys.exit("Build incomplete (missing %s). Run:  python tools/build_translation.py"
                 % ", ".join(os.path.basename(m) for m in missing))

    for name, dst, backup, build in files:
        print("%-17s %.1f MB -> %s" % (name, os.path.getsize(build) / 1048576, dst))
    if not args.yes:
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            sys.exit("Cancelled.")

    for name, dst, backup, build in files:
        if not os.path.exists(backup):
            print("Backing up the original -> %s" % os.path.basename(backup))
            shutil.copy2(dst, backup)
        shutil.copy2(build, dst)
    print("Done. Start the game and pick «Русский» in Settings -> Language.")


if __name__ == "__main__":
    main()
