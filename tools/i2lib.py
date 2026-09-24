# -*- coding: utf-8 -*-
"""Read/write the I2 Localization table (I2.Loc.LanguageSourceAsset) inside a
Unity serialized file.

The build strips type trees, and the generated tree for LanguageSourceAsset has
wrong alignment flags, so the asset is parsed and rebuilt by hand. Layout:

    <28 bytes MonoBehaviour prefix: m_GameObject, m_Enabled+pad, m_Script>
    string  m_Name
    bool    UserAgreesToHaveItOnTheScene          (each bool padded to 4)
    bool    UserAgreesToHaveItInsideThePluginsFolder
    bool    GoogleLiveSyncIsUptoDate
    TermData[] mTerms      { string Term; int TermType;
                             string[] Languages; byte[] Flags; string[] Languages_Touch }
    bool    CaseInsensitiveTerms
    int     OnMissingTranslation
    string  mTerm_AppName
    LanguageData[] mLanguages  { string Name; string Code; byte Flags }
    <tail: Google_* fields and the Assets array, copied verbatim>
"""
import os
import struct

PREFIX_LEN = 28
I2_CLASS = "I2.Loc.LanguageSourceAsset"


class Reader:
    def __init__(self, buf, pos=0):
        self.b = buf
        self.p = pos

    def i32(self):
        v = struct.unpack_from("<i", self.b, self.p)[0]
        self.p += 4
        return v

    def u8(self):
        v = self.b[self.p]
        self.p += 1
        return v

    def align(self):
        self.p = (self.p + 3) & ~3

    def boolean(self):
        v = self.u8()
        self.align()
        return v

    def string(self):
        n = self.i32()
        if n < 0 or self.p + n > len(self.b):
            raise ValueError("bad string length %d at %d" % (n, self.p))
        v = self.b[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        self.align()
        return v

    def byte_array(self):
        n = self.i32()
        v = list(self.b[self.p:self.p + n])
        self.p += n
        self.align()
        return v

    def string_list(self):
        n = self.i32()
        if n < 0 or n > 200000:
            raise ValueError("bad list size %d at %d" % (n, self.p))
        return [self.string() for _ in range(n)]


class Writer:
    def __init__(self):
        self.parts = []
        self.n = 0

    def raw(self, b):
        self.parts.append(b)
        self.n += len(b)

    def i32(self, v):
        self.raw(struct.pack("<i", v))

    def u8(self, v):
        self.raw(bytes([v]))

    def align(self):
        pad = (-self.n) & 3
        if pad:
            self.raw(b"\0" * pad)

    def boolean(self, v):
        self.u8(1 if v else 0)
        self.align()

    def string(self, s):
        data = s.encode("utf-8")
        self.i32(len(data))
        self.raw(data)
        self.align()

    def byte_array(self, values):
        self.i32(len(values))
        self.raw(bytes(values))
        self.align()

    def string_list(self, items):
        self.i32(len(items))
        for s in items:
            self.string(s)

    def result(self):
        return b"".join(self.parts)


def parse(raw):
    """raw = full MonoBehaviour object bytes -> dict"""
    r = Reader(raw, PREFIX_LEN)
    name = r.string()
    b1, b2, b3 = r.boolean(), r.boolean(), r.boolean()
    terms = []
    for _ in range(r.i32()):
        terms.append({
            "Term": r.string(),
            "TermType": r.i32(),
            "Languages": r.string_list(),
            "Flags": r.byte_array(),
            "Languages_Touch": r.string_list(),
        })
    case_insensitive = r.boolean()
    on_missing = r.i32()
    app_name = r.string()
    languages = []
    for _ in range(r.i32()):
        nm, code = r.string(), r.string()
        fl = r.u8()
        r.align()
        languages.append({"Name": nm, "Code": code, "Flags": fl})
    return {
        "_prefix": raw[:PREFIX_LEN],
        "_tail": raw[r.p:],
        "m_Name": name,
        "UserAgreesToHaveItOnTheScene": b1,
        "UserAgreesToHaveItInsideThePluginsFolder": b2,
        "GoogleLiveSyncIsUptoDate": b3,
        "terms": terms,
        "CaseInsensitiveTerms": case_insensitive,
        "OnMissingTranslation": on_missing,
        "mTerm_AppName": app_name,
        "languages": languages,
    }


def serialize(src):
    w = Writer()
    w.raw(src["_prefix"])
    w.string(src["m_Name"])
    w.boolean(src["UserAgreesToHaveItOnTheScene"])
    w.boolean(src["UserAgreesToHaveItInsideThePluginsFolder"])
    w.boolean(src["GoogleLiveSyncIsUptoDate"])
    w.i32(len(src["terms"]))
    for t in src["terms"]:
        w.string(t["Term"])
        w.i32(t["TermType"])
        w.string_list(t["Languages"])
        w.byte_array(t["Flags"])
        w.string_list(t["Languages_Touch"])
    w.boolean(src["CaseInsensitiveTerms"])
    w.i32(src["OnMissingTranslation"])
    w.string(src["mTerm_AppName"])
    w.i32(len(src["languages"]))
    for l in src["languages"]:
        w.string(l["Name"])
        w.string(l["Code"])
        w.u8(l["Flags"])
        w.align()
    w.raw(src["_tail"])
    return w.result()


# --------------------------------------------------------------------------- env
def script_path_ids(data_dir, class_name):
    """pathIDs of the MonoScript objects for `class_name` (they all live in
    globalgamemanagers.assets)."""
    import UnityPy
    env = UnityPy.load(os.path.join(data_dir, "globalgamemanagers.assets"))
    out = set()
    for o in env.objects:
        if o.type.name != "MonoScript":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        ns, cn = d.get("m_Namespace", ""), d.get("m_ClassName", "")
        if (f"{ns}.{cn}" if ns else cn) == class_name:
            out.add(o.path_id)
    return out


def find_language_source(env, script_ids):
    """-> (ObjectReader, raw bytes) for the I2 LanguageSourceAsset."""
    for o in env.objects:
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        if len(raw) < 32:
            continue
        if struct.unpack_from("<q", raw, 20)[0] in script_ids:
            return o, raw
    return None, None


def game_version(data_dir):
    """Game version string (PlayerSettings.bundleVersion, e.g. "1.02"), or None."""
    import UnityPy
    try:
        env = UnityPy.load(os.path.join(data_dir, "globalgamemanagers"))
        for o in env.objects:
            if o.type.name == "PlayerSettings":
                return o.read_typetree().get("bundleVersion") or None
    except Exception:
        pass
    return None


def read_version_file(path):
    """Contents of game_version.txt, or None."""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def find_data_dir(start=None):
    """Locate `<game>/Card Shop Simulator_Data` from the repo location."""
    here = os.path.abspath(start or os.path.join(os.path.dirname(__file__), ".."))
    for base in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        cand = os.path.join(base, "Card Shop Simulator_Data")
        if os.path.isdir(cand):
            return cand
    return None
