# -*- coding: utf-8 -*-
"""Lint `translation/ru.json` before it ships.

    python tools/check_translation.py

Errors (exit code 1):
  - the key list differs from the game's term list (strings/01_i2_localization_full.json);
  - a translation loses or duplicates a placeholder XXX / YYY / ZZZ;
  - a translation changes the number of <nobr> / </nobr> tags;
  - the English text ends with a space and the translation does not.
Warnings: the English text has line breaks and the translation has none.
"""
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TRANSLATION = os.path.join(REPO, "translation", "ru.json")
TERMS = os.path.join(REPO, "strings", "01_i2_localization_full.json")
TOKENS = ("XXX", "YYY", "ZZZ", "<nobr>", "</nobr>")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    with open(TRANSLATION, encoding="utf-8") as f:
        rows = json.load(f)
    with open(TERMS, encoding="utf-8") as f:
        terms = [t["term"] for t in json.load(f)["terms"]]

    errors, warnings = [], []
    if not isinstance(rows, list) or not all(
            isinstance(r, dict) and isinstance(r.get("key"), str)
            and isinstance(r.get("en"), str) and isinstance(r.get("ru"), str) for r in rows):
        sys.exit("ru.json: expected a list of {key, en, ru} string objects")
    if [r["key"] for r in rows] != terms:
        missing = set(terms) - {r["key"] for r in rows}
        extra = {r["key"] for r in rows} - set(terms)
        errors.append("key list differs from the game terms (missing %d, extra %d, or reordered)"
                      % (len(missing), len(extra)))

    for r in rows:
        en, ru = r["en"], r["ru"]
        if not ru.strip():
            continue
        where = r["key"][:60]
        for tok in TOKENS:
            if en.count(tok) != ru.count(tok):
                errors.append("%s: %r x%d in en, x%d in ru" % (where, tok, en.count(tok), ru.count(tok)))
        if en.endswith(" ") and not ru.endswith(" "):
            errors.append("%s: lost the trailing space" % where)
        if "\n" in en and "\n" not in ru:
            warnings.append("%s: en has line breaks, ru has none" % where)

    for w in warnings:
        print("warning: %s" % w)
    for e in errors:
        print("error: %s" % e)
    done = sum(1 for r in rows if r["ru"].strip())
    print("%d/%d translated, %d errors, %d warnings" % (done, len(rows), len(errors), len(warnings)))
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
