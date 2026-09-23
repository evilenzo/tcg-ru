# -*- coding: utf-8 -*-
"""Build a patched `resources.assets` with the Russian translation in the I2 table.

The game's language menu is a fixed set of buttons in the scenes, so a new column would
not be selectable. Instead the Russian text replaces the French column: picking
"Francais" in Settings -> Language shows Russian.

    python tools/build_translation.py              # build -> build/resources.assets
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

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TARGET_CODE = "fr"  # column that receives the Russian text


def load_translation(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, str)}
    return {row["key"]: row.get("ru", "") for row in data if row.get("key") is not None}


def patch(src, table, en_index):
    """Overwrite the TARGET_CODE column with Russian. Returns coverage stats."""
    codes = [l["Code"] for l in src["languages"]]
    if TARGET_CODE not in codes:
        sys.exit("No '%s' column in the source table." % TARGET_CODE)
    idx = codes.index(TARGET_CODE)

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
        langs[idx] = ru
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

    total = stats["translated"] + stats["fallback_to_english"]
    print("\nwrote  : %s (%.1f MB)" % (args.out, os.path.getsize(args.out) / 1048576))
    print("russian: in the '%s' column, %d/%d terms translated (%.1f%%), %d fall back to English"
          % (TARGET_CODE, stats["translated"], total,
             100.0 * stats["translated"] / total, stats["fallback_to_english"]))
    print("\nNext:  python tools/install.py")


if __name__ == "__main__":
    main()
