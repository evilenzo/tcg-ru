# -*- coding: utf-8 -*-
"""Build the Russian translation: a Russian column in the I2 table
(`resources.assets`) plus the patched Settings screen in `level0`/`level1`
(Russian button, localized FPS dropdown — see scenepatch.py).

    python tools/build_translation.py              # build -> build/resources.assets, level0, level1
    python tools/build_translation.py --selftest   # prove the rebuild is lossless
    python tools/build_translation.py --game "D:/.../TCG Card Shop Simulator"

Reads `translation/ru.json`: [{"key": ..., "en": ..., "ru": ...}].
Terms with an empty "ru" fall back to their English text (not French), so the build
works (and is installable) at any level of translation completeness.
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i2lib  # noqa: E402
import scenepatch  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LANG_NAME = "Russian"
LANG_CODE = "ru"  # what SettingScreen.OnPressLanguageSelect("Russian") selects


def load_translation(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, str)}
    return {row["key"]: row.get("ru", "") for row in data if row.get("key") is not None}


def add_terms(src, terms):
    """Append missing terms whose text is the same in every language (the FPS
    dropdown labels that scenepatch localizes). Layout mirrors the stock terms:
    TermType 0 (Text), one flag byte per language, empty Languages_Touch."""
    have = {t["Term"] for t in src["terms"]}
    n = len(src["languages"])
    for term in terms:
        if term not in have:
            src["terms"].append({"Term": term, "TermType": 0, "Languages": [term] * n,
                                 "Flags": [0] * n, "Languages_Touch": []})


def patch(src, table, en_index):
    """Add (or overwrite) the Russian column. Returns coverage stats."""
    add_terms(src, scenepatch.FPS_TERMS)
    codes = [l["Code"] for l in src["languages"]]
    if LANG_CODE in codes:
        idx = codes.index(LANG_CODE)
    else:
        idx = len(src["languages"])
        src["languages"].append({"Name": LANG_NAME, "Code": LANG_CODE, "Flags": 0})

    translated = fallback = 0
    for t in src["terms"]:
        langs = t["Languages"]
        english = langs[en_index] if en_index < len(langs) else ""
        # Trailing spaces are significant ("Cost : " + number), so only test for blank.
        ru = table.get(t["Term"]) or ""
        if ru.strip():
            translated += 1
        else:
            ru = english
            fallback += 1
        while len(langs) <= idx:
            langs.append("")
        langs[idx] = ru
        while len(t["Flags"]) <= idx:
            t["Flags"].append(0)
        # Languages_Touch is empty in this build; keep it that way.
    return {"translated": translated, "fallback_to_english": fallback,
            "language_index": idx, "languages": [l["Code"] for l in src["languages"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", help="game folder (auto-detected by default)")
    ap.add_argument("--translation", default=os.path.join(REPO, "translation", "ru.json"))
    ap.add_argument("--out", default=os.path.join(REPO, "build", "resources.assets"))
    ap.add_argument("--selftest", action="store_true",
                    help="rebuild the asset unchanged and check it is byte-identical")
    args = ap.parse_args()

    import UnityPy

    data_dir = (os.path.join(args.game, "Card Shop Simulator_Data") if args.game
                else i2lib.find_data_dir())
    if not data_dir or not os.path.isdir(data_dir):
        sys.exit("Could not find 'Card Shop Simulator_Data'. Pass --game <game folder>.")

    # Always build from a pristine source: prefer the install backup if present.
    target = os.path.join(data_dir, "resources.assets")
    backup = target + ".orig-backup"
    source = backup if os.path.exists(backup) else target
    print("source : %s" % source)
    game_ver = i2lib.game_version(data_dir)
    made_for = i2lib.read_version_file(os.path.join(REPO, "game_version.txt"))
    print("game   : %s (game_version.txt: %s)" % (game_ver, made_for))
    if game_ver and made_for and game_ver != made_for:
        print("WARNING: the game is %s but game_version.txt says %s. If the game updated,\n"
              "         re-extract strings and update game_version.txt before releasing."
              % (game_ver, made_for))

    script_ids = i2lib.script_path_ids(data_dir, i2lib.I2_CLASS)
    if not script_ids:
        sys.exit("MonoScript for %s not found." % i2lib.I2_CLASS)

    env = UnityPy.load(source)
    obj, raw = i2lib.find_language_source(env, script_ids)
    if obj is None:
        sys.exit("I2 LanguageSourceAsset not found in %s" % source)
    print("asset  : %s (pathID %d, %d bytes)" % (obj.type.name, obj.path_id, len(raw)))

    src = i2lib.parse(raw)
    codes = [l["Code"] for l in src["languages"]]
    print("table  : %r, %d terms, languages %s"
          % (src["m_Name"], len(src["terms"]), codes))

    if args.selftest:
        rebuilt = i2lib.serialize(src)
        if rebuilt != raw:
            sys.exit("SELFTEST FAILED: rebuilt asset differs from the original "
                     "(%d vs %d bytes)" % (len(rebuilt), len(raw)))
        obj.set_raw_data(rebuilt)
        if env.file.save() != open(source, "rb").read():
            sys.exit("SELFTEST FAILED: repacked file differs from the original")
        print("SELFTEST OK: object and container both round-trip byte-identically")
        return

    if "en" not in codes:
        sys.exit("No English column in the source table.")
    table = load_translation(args.translation)
    print("input  : %s (%d entries, %d non-empty)"
          % (args.translation, len(table), sum(1 for v in table.values() if v.strip())))

    stats = patch(src, table, codes.index("en"))
    new_raw = i2lib.serialize(src)

    # Verify the bytes we are about to ship parse back to what we intended.
    check = i2lib.parse(new_raw)
    assert len(check["terms"]) == len(src["terms"]), "term count changed"
    have = {t["Term"] for t in check["terms"]}
    assert all(t in have for t in scenepatch.FPS_TERMS), "FPS terms missing"
    assert [l["Code"] for l in check["languages"]] == stats["languages"], "language list changed"
    bad = [t["Term"] for t in check["terms"]
           if len(t["Languages"]) != len(check["languages"])
           or len(t["Flags"]) != len(check["languages"])]
    if bad:
        sys.exit("Inconsistent term rows: %s" % bad[:5])

    obj.set_raw_data(new_raw)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "wb") as f:
        f.write(env.file.save())

    print("\nwrote  : %s (%.1f MB)" % (args.out, os.path.getsize(args.out) / 1048576))

    localize_ids = i2lib.script_path_ids(data_dir, scenepatch.LOCALIZE_DROPDOWN_CLASS)
    for scene in scenepatch.SCENES:
        scene_target = os.path.join(data_dir, scene)
        scene_backup = scene_target + ".orig-backup"
        data, what = scenepatch.patch_scene_file(
            scene_backup if os.path.exists(scene_backup) else scene_target, localize_ids)
        scene_out = os.path.join(os.path.dirname(args.out), scene)
        with open(scene_out, "wb") as f:
            f.write(data)
        print("wrote  : %s (%s)" % (scene_out, what))

    total = stats["translated"] + stats["fallback_to_english"]
    print("russian: column %d, %d/%d terms translated (%.1f%%), %d fall back to English"
          % (stats["language_index"], stats["translated"], total,
             100.0 * stats["translated"] / total, stats["fallback_to_english"]))
    print("\nNext:  python tools/install.py")


if __name__ == "__main__":
    main()
