# -*- coding: utf-8 -*-
"""Build the release files into release/ (used by CI, also runs locally).

    pip install -r requirements.txt pyinstaller
    python tools/build_installer.py --version v1.2.0

    release/tcg-ru-installer.exe   standalone GUI installer (installer_gui.py) with ru.json bundled in
    release/tcg-ru-<version>.zip   ru.json + tools/ for those who run it with Python

Needs no game files: the translation is built on the player's machine.
"""
import argparse
import os
import shutil
import zipfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = os.path.join(REPO, "release")
WORK = os.path.join(REPO, "build", "installer")
NAME = "tcg-ru-installer"
PACKAGE_FILES = ["README.md", "requirements.txt", "game_version.txt", "translation/ru.json",
                 "tools/i2lib.py", "tools/scenepatch.py", "tools/build_translation.py", "tools/install.py",
                 "tools/installer.py", "tools/installer_gui.py"]


def build_exe(version):
    import PyInstaller.__main__

    version_file = os.path.join(WORK, "version.txt")
    with open(version_file, "w", encoding="utf-8") as f:
        f.write(version)

    def data(src, dest):
        return "--add-data=%s%s%s" % (src, os.pathsep, dest)

    PyInstaller.__main__.run([
        os.path.join(REPO, "tools", "installer_gui.py"),
        "--name", NAME,
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--distpath", OUT,
        "--workpath", os.path.join(WORK, "work"),
        "--specpath", WORK,
        "--paths", os.path.join(REPO, "tools"),
        # UnityPy reads its type-tree database (resources/*.tpk) at runtime.
        "--collect-all", "UnityPy",
        data(os.path.join(REPO, "translation", "ru.json"), "translation"),
        data(version_file, "."),
        data(os.path.join(REPO, "game_version.txt"), "."),
    ])


def build_zip(version):
    path = os.path.join(OUT, "tcg-ru-%s.zip" % version)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in PACKAGE_FILES:
            z.write(os.path.join(REPO, rel), "ru-translation/" + rel)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="dev", help="release tag, shown by the installer")
    args = ap.parse_args()

    shutil.rmtree(OUT, ignore_errors=True)
    os.makedirs(WORK, exist_ok=True)
    build_exe(args.version)
    build_zip(args.version)
    for name in sorted(os.listdir(OUT)):
        print("%-40s %6.1f MB" % (name, os.path.getsize(os.path.join(OUT, name)) / 1048576))


if __name__ == "__main__":
    main()
