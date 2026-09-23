# -*- coding: utf-8 -*-
"""Full string extraction for TCG Card Shop Simulator (Unity 2021.3.38f1, Mono)."""
import os, sys, json, struct, re, collections, traceback
import UnityPy
from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator
from UnityPy.helpers.TypeTreeNode import TypeTreeNode

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.dirname(REPO)          # the game folder
DATA = os.path.join(ROOT, "Card Shop Simulator_Data")
OUT = os.path.join(REPO, "strings", "raw")
UNITY_VER = "2021.3.38f1"
SCRIPT_HOST = "globalgamemanagers.assets"
TARGETS = ["globalgamemanagers.assets", "level0", "level1", "resources.assets",
           "sharedassets0.assets", "sharedassets1.assets"]

os.makedirs(OUT, exist_ok=True)
gen = TypeTreeGenerator(UNITY_VER)
gen.load_local_game(ROOT)

# ---------------------------------------------------------------- typetrees
SMALL = {"UInt8", "SInt8", "char", "bool"}


def align_fix(node, parent_is_array=False):
    for c in node.m_Children:
        align_fix(c, node.m_Type == "Array")
    if node.m_Type in SMALL and not parent_is_array:
        node.m_MetaFlag = (node.m_MetaFlag or 0) | 0x4000


_cache = {}


def nodes_for(assembly, full_name):
    """-> (plain_root, aligned_root, has_string_field)"""
    key = (assembly, full_name)
    if key in _cache:
        return _cache[key]
    root, used_asm = None, None
    for asm in ([assembly] if assembly else []) + ["Assembly-CSharp.dll"]:
        if not asm:
            continue
        try:
            root = gen.get_nodes_up(asm, full_name)
        except Exception:
            root = None
        if root:
            used_asm = asm
            break
    aligned, has_str = None, False
    if root:
        has_str = any(n.m_Type == "string" for n in root.traverse())
        try:
            flat = gen.get_nodes(used_asm if used_asm.endswith(".dll") else used_asm + ".dll",
                                 full_name)
            aligned = TypeTreeNode.from_list([
                TypeTreeNode(b.m_Level, b.m_Type, b.m_Name, 0, 0, m_MetaFlag=b.m_MetaFlag)
                for b in flat])
            align_fix(aligned)
        except Exception:
            aligned = None
    _cache[key] = (root, aligned, has_str)
    return _cache[key]


# ---------------------------------------------------------------- raw fallback
BAD_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
HAS_LETTER = re.compile(r"[A-Za-z\u00c0-\uffff]")


def raw_scan(raw, start=0):
    """Recover length-prefixed UTF-8 strings from an object we cannot type-parse."""
    out, i, n = [], start, len(raw)
    while i + 4 <= n:
        ln = struct.unpack_from("<i", raw, i)[0]
        if 2 <= ln <= 8192 and i + 4 + ln <= n:
            chunk = raw[i + 4:i + 4 + ln]
            try:
                s = chunk.decode("utf-8")
            except UnicodeDecodeError:
                i += 4
                continue
            if not BAD_CTRL.search(s) and HAS_LETTER.search(s):
                out.append(s)
                i = ((i + 4 + ln) + 3) & ~3
                continue
        i += 4
    return out


# ---------------------------------------------------------------- I2 parser
class R:
    def __init__(self, b, p=0):
        self.b = b
        self.p = p

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

    def bool_a(self):
        v = self.u8()
        self.align()
        return v

    def s(self):
        n = self.i32()
        if n < 0 or self.p + n > len(self.b):
            raise ValueError("bad string length")
        v = self.b[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        self.align()
        return v

    def bytes_a(self):
        n = self.i32()
        v = self.b[self.p:self.p + n]
        self.p += n
        self.align()
        return v

    def str_list(self):
        n = self.i32()
        if n < 0 or n > 200000:
            raise ValueError("bad list size")
        return [self.s() for _ in range(n)]


def parse_i2(raw):
    r = R(raw, 28)
    name = r.s()
    r.bool_a()
    r.bool_a()
    r.bool_a()
    terms = []
    for _ in range(r.i32()):
        terms.append({
            "Term": r.s(), "TermType": r.i32(), "Languages": r.str_list(),
            "Flags": list(r.bytes_a()), "Languages_Touch": r.str_list(),
        })
    case_insensitive = r.bool_a()
    on_missing = r.i32()
    app_name = r.s()
    langs = []
    for _ in range(r.i32()):
        nm, code, fl = r.s(), r.s(), r.u8()
        r.align()
        langs.append({"Name": nm, "Code": code, "Flags": fl})
    return {"name": name, "languages": langs, "terms": terms,
            "CaseInsensitiveTerms": case_insensitive, "OnMissingTranslation": on_missing,
            "mTerm_AppName": app_name, "_consumed": r.p, "_size": len(raw)}


# ---------------------------------------------------------------- walk
def walk(value, path, out):
    if isinstance(value, str):
        if value:
            out.append((path, value))
    elif isinstance(value, dict):
        for k, v in value.items():
            walk(v, f"{path}.{k}" if path else k, out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            walk(v, f"{path}[{i}]", out)


def mb_prefix(raw):
    if len(raw) < 32:
        return None
    go_path = struct.unpack_from("<q", raw, 4)[0]
    sc_path = struct.unpack_from("<q", raw, 20)[0]
    nlen = struct.unpack_from("<i", raw, 28)[0]
    name = raw[32:32 + nlen].decode("utf-8", "replace") if 0 < nlen < 4096 else ""
    return go_path, sc_path, name


# ---------------------------------------------------------------- main
SCRIPTS = {}


def load_scripts():
    env = UnityPy.load(os.path.join(DATA, SCRIPT_HOST))
    for o in env.objects:
        if o.type.name != "MonoScript":
            continue
        try:
            d = o.read_typetree()
        except Exception:
            continue
        ns, cn = d.get("m_Namespace", ""), d.get("m_ClassName", "")
        SCRIPTS[o.path_id] = (d.get("m_AssemblyName", ""), f"{ns}.{cn}" if ns else cn)
    print("MonoScript table: %d" % len(SCRIPTS), flush=True)


STATE = {"i2": None}
rows = []
recovered = []


def process(fname):
    env = UnityPy.load(os.path.join(DATA, fname))
    objs = list(env.objects)
    go_names, tf_parent, go_tf = {}, {}, {}
    for o in objs:
        try:
            if o.type.name == "GameObject":
                go_names[o.path_id] = o.read_typetree().get("m_Name", "")
            elif o.type.name in ("Transform", "RectTransform"):
                d = o.read_typetree()
                tf_parent[o.path_id] = (d["m_GameObject"]["m_PathID"], d["m_Father"]["m_PathID"])
                go_tf[d["m_GameObject"]["m_PathID"]] = o.path_id
        except Exception:
            pass

    def go_path(pid):
        parts, cur, depth = [], go_tf.get(pid), 0
        while cur and depth < 24:
            gp, father = tf_parent.get(cur, (None, 0))
            parts.append(go_names.get(gp, "?"))
            cur = father or None
            depth += 1
        return "/".join(reversed(parts)) if parts else go_names.get(pid, "")

    fails = collections.Counter()
    for o in objs:
        if o.type.name != "MonoBehaviour":
            continue
        try:
            raw = o.get_raw_data()
        except Exception:
            continue
        pre = mb_prefix(raw)
        if not pre:
            continue
        go_pid, sc_pid, mb_name = pre
        asm, cls = SCRIPTS.get(sc_pid, ("", ""))
        if cls == "I2.Loc.LanguageSourceAsset":
            try:
                res = parse_i2(raw)
                STATE["i2"] = res
                print("   I2 table %r: %d terms, %d languages"
                      % (res["name"], len(res["terms"]), len(res["languages"])), flush=True)
            except Exception:
                traceback.print_exc()
            continue
        plain, aligned, has_str = nodes_for(asm, cls) if cls else (None, None, False)
        if plain is None:
            fails[cls or "<unknown>"] += 1
            continue
        if not has_str:
            continue
        tree, err = None, None
        for nodes in (plain, aligned):
            if nodes is None:
                continue
            try:
                tree = o.read_typetree(nodes)
                err = None
                break
            except Exception as e:
                err = e
        ctx = go_path(go_pid) or mb_name
        if tree is None:
            fails["%s (%s)" % (cls, err)] += 1
            for s in raw_scan(raw, 28):
                recovered.append({"file": fname, "path_id": o.path_id, "class": cls,
                                  "object": ctx, "field": "<raw-scan>", "value": s})
            continue
        found = []
        walk(tree, "", found)
        for fld, val in found:
            rows.append({"file": fname, "path_id": o.path_id, "class": cls,
                         "object": ctx, "field": fld, "value": val})
    if fails:
        print("   unparsed: " + "; ".join("%s x%d" % (k, v) for k, v in fails.most_common(6)),
              file=sys.stderr, flush=True)


if __name__ == "__main__":
    load_scripts()
    for f in TARGETS:
        print("-> %s" % f, flush=True)
        try:
            process(f)
        except Exception:
            traceback.print_exc()
    print("asset string fields: %d  (+%d raw-recovered)" % (len(rows), len(recovered)), flush=True)
    with open(os.path.join(OUT, "_i2_raw.json"), "w", encoding="utf-8") as fh:
        json.dump(STATE["i2"], fh, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "_assets_raw.json"), "w", encoding="utf-8") as fh:
        json.dump(rows + recovered, fh, ensure_ascii=False, indent=1)
    print("done")
