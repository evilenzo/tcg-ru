# -*- coding: utf-8 -*-
"""Turn the raw dumps into translation-ready files."""
import json, os, csv, re, collections

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RAW = os.path.join(REPO, "strings", "raw")
OUT = os.path.join(REPO, "strings")
os.makedirs(OUT, exist_ok=True)

i2 = json.load(open(os.path.join(RAW, "_i2_raw.json"), encoding="utf-8"))
rows = json.load(open(os.path.join(RAW, "_assets_raw.json"), encoding="utf-8"))
code = json.load(open(os.path.join(RAW, "03_code_strings.json"), encoding="utf-8"))

# ------------------------------------------------------------------ 1. I2 table
lang_codes = [l["Code"] for l in i2["languages"]]
lang_names = [l["Name"] for l in i2["languages"]]
TERM_TYPES = {0: "Text", 1: "Font", 2: "Texture", 3: "AudioClip", 4: "GameObject",
              5: "Sprite", 6: "Material", 7: "Child", 8: "Mesh", 9: "TextMeshPFont",
              10: "Object"}

full_terms = []
for t in i2["terms"]:
    tr = {}
    for i, code_ in enumerate(lang_codes):
        tr[code_] = t["Languages"][i] if i < len(t["Languages"]) else ""
    full_terms.append({
        "term": t["Term"],
        "type": TERM_TYPES.get(t["TermType"], str(t["TermType"])),
        "translations": tr,
    })

with open(os.path.join(OUT, "01_i2_localization_full.json"), "w", encoding="utf-8") as f:
    json.dump({"source_asset": "resources.assets :: I2Languages (MonoBehaviour pathID 6144)",
               "languages": [{"name": n, "code": c} for n, c in zip(lang_names, lang_codes)],
               "term_count": len(full_terms),
               "terms": full_terms}, f, ensure_ascii=False, indent=1)

text_terms = [t for t in full_terms if t["type"] == "Text"]
to_translate = [{"key": t["term"], "en": t["translations"].get("en", ""), "ru": ""}
                for t in text_terms]
with open(os.path.join(OUT, "01_i2_translate_ru.json"), "w", encoding="utf-8") as f:
    json.dump(to_translate, f, ensure_ascii=False, indent=1)

with open(os.path.join(OUT, "01_i2_translate_ru.csv"), "w", encoding="utf-8-sig",
          newline="") as f:
    w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(["key", "en", "ru"])
    for r in to_translate:
        w.writerow([r["key"], r["en"], r["ru"]])

# ------------------------------------------------------------------ 2. noise filter
NOISE_FIELD = re.compile(
    r"m_AnimationTriggers|m_PersistentCalls|AssemblyTypeName|m_MethodName|"
    r"m_SortingLayerName|m_TargetAssemblyTypeName|m_ObjectArgumentAssemblyTypeName")
NOISE_CLASS = {"TMPro.TMP_FontAsset", "UnityEngine.EventSystems.EventTrigger",
               "UnityEngine.UI.Button", "ControllerButton", "InputManager"}


def is_noise(r):
    if NOISE_FIELD.search(r["field"]):
        return True
    if r["class"] in NOISE_CLASS and r["field"] not in ("m_Name",):
        return True
    return False


clean = [r for r in rows if not is_noise(r)]

# ------------------------------------------------------------------ 3. UI text
i2_keys = {t["term"] for t in full_terms}
i2_en = {t["translations"].get("en", "") for t in full_terms}
i2_en.discard("")

ui = [r for r in clean if r["field"] in ("m_text", "m_Text")]
static_ui = collections.OrderedDict()
for r in ui:
    v = r["value"]
    if v in i2_keys or v in i2_en:
        continue
    if not re.search(r"[A-Za-z]", v):
        continue
    static_ui.setdefault(v, []).append(
        {"file": r["file"], "path_id": r["path_id"], "object": r["object"]})

with open(os.path.join(OUT, "03_ui_text_static.json"), "w", encoding="utf-8") as f:
    json.dump([{"text": k, "ru": "", "occurrences": len(v), "where": v[:8]}
               for k, v in static_ui.items()], f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ 4. game data
SO_CLASSES = sorted({r["class"] for r in clean
                     if "ScriptableObject" in r["class"] or r["class"].startswith("CC.scrObj")})
so = collections.OrderedDict()
for cls in SO_CLASSES:
    items = collections.OrderedDict()
    for r in clean:
        if r["class"] != cls:
            continue
        items.setdefault(r["value"], []).append(r["field"])
    so[cls] = [{"text": k, "ru": "", "fields": sorted(set(v))[:4], "count": len(v)}
               for k, v in items.items()]
with open(os.path.join(OUT, "02_game_data_strings.json"), "w", encoding="utf-8") as f:
    json.dump(so, f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ 5. I2 term usage map
usage = collections.defaultdict(list)
for r in rows:
    if r["field"] == "mTerm" and r["value"]:
        usage[r["value"]].append({"file": r["file"], "object": r["object"]})
with open(os.path.join(OUT, "04_i2_term_usage.json"), "w", encoding="utf-8") as f:
    json.dump({k: v[:10] for k, v in sorted(usage.items())}, f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ 6. flat CSV
with open(os.path.join(OUT, "05_all_asset_strings.csv"), "w", encoding="utf-8-sig",
          newline="") as f:
    w = csv.writer(f, delimiter=";", quoting=csv.QUOTE_ALL)
    w.writerow(["file", "path_id", "class", "object", "field", "value"])
    for r in rows:
        w.writerow([r["file"], r["path_id"], r["class"], r["object"], r["field"], r["value"]])

# ------------------------------------------------------------------ 7. code strings
CODE_NOISE = re.compile(
    r"^[\s\d.,:%/\\|+\-*#@_]*$|^<[^>]+>$|^\{\d+\}$|^[a-z_]+(\.[a-z_]+)+$", re.I)


def code_interesting(s):
    if len(s) < 2 or len(s) > 400:
        return False
    if CODE_NOISE.match(s):
        return False
    if not re.search(r"[A-Za-z]{2}", s):
        return False
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", s) and " " not in s:
        return False        # identifiers / keys
    return True


code_out = {}
for dll, lst in code.items():
    code_out[dll] = {
        "likely_ui_text": [{"text": s, "ru": ""} for s in lst if code_interesting(s)],
        "all_literals": lst,
    }
with open(os.path.join(OUT, "06_code_strings.json"), "w", encoding="utf-8") as f:
    json.dump(code_out, f, ensure_ascii=False, indent=1)

# ------------------------------------------------------------------ report
stats = {
    "i2_terms_total": len(full_terms),
    "i2_terms_text": len(text_terms),
    "i2_languages": lang_codes,
    "i2_english_filled": sum(1 for t in text_terms if t["translations"].get("en")),
    "asset_string_fields_total": len(rows),
    "asset_string_fields_after_noise_filter": len(clean),
    "static_ui_texts": len(static_ui),
    "game_data_classes": {k: len(v) for k, v in so.items()},
    "code_literals": {k: {"all": len(v["all_literals"]),
                          "likely_ui": len(v["likely_ui_text"])} for k, v in code_out.items()},
}
with open(os.path.join(OUT, "00_stats.json"), "w", encoding="utf-8") as f:
    json.dump(stats, f, ensure_ascii=False, indent=1)
print(json.dumps(stats, ensure_ascii=False, indent=1))
