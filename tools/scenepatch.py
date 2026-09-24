# -*- coding: utf-8 -*-
"""Patch the Settings screen in the scenes `level0` (title) and `level1` (game).

Both scenes carry their own copy of `Canvas/SettingScreen`. Two fixes per scene:

1. Russian button. The language menu is a fixed set of buttons, not a list built
   from the I2 table. The developer left an unfinished `Russian_Button` in
   `.../LanguageScreen/UIGroup`: inactive, labelled "Done", off the grid and wired to
   `SetItemPriceScreen.OnPressConfirm`. The code side already works:
   `SettingScreen.OnPressLanguageSelect("Russian")` sets the I2 language code "ru".
   We activate the button, move it next to Portuguese, copy Portuguese's onClick call
   with the argument "Russian" and relabel it "Русский" (the label font has
   RussianOutline in its fallback chain).

2. FPS dropdown. UniversalSettings fills it from code ("30 FPS" ... "Unlimited FPS"),
   with nothing localizing it. We add an I2 `LocalizeDropdown` (a clone of the one on
   the quality dropdown) with FPS_TERMS as its terms; build_translation.py adds these
   terms to the I2 table. It goes last on the GameObject, so its OnEnable/Start run
   after FpsController has created the options, and it only swaps the texts.

GameObject and RectTransform are native types and go through UnityPy's typetrees.
The MonoBehaviours have no typetree in the build and are patched as raw bytes with
strict checks on every assumption.
"""
import struct

import attr

SCENES = ("level0", "level1")
LOCALIZE_DROPDOWN_CLASS = "I2.Loc.LocalizeDropdown"

# -- Russian button
LANG_SCREEN = "LanguageScreen"
TEMPLATE_BUTTON = "Portuguese_Button"
TARGET_BUTTON = "Russian_Button"
CALL_ARGUMENT = "Russian"
LABEL = "Русский"
GRID_X = 0.0  # 3 columns at x = -450 / 0 / 450; Portuguese holds (-450, -357)
OLD_LABEL = "Done"
TEMPLATE_TYPE = "SettingScreen, Assembly-CSharp"
TEMPLATE_METHOD = "OnPressLanguageSelect"
TEMPLATE_ARGUMENT = "Portuguese"
PLACEHOLDER_TYPE = "SetItemPriceScreen, Assembly-CSharp"

# -- FPS dropdown
# UniversalSettingsRunner.fpsOptions is [30, 60, 120, 240, -1] in both scenes;
# UpdateFpsOptions() renders them as "{n} FPS" / "Unlimited FPS".
FPS_TERMS = ("30 FPS", "60 FPS", "120 FPS", "240 FPS", "Unlimited FPS")
FPS_PATH = ("DisplaySettingScreen", "FPS Text_TMP", "FPS Dropdown")
QUALITY_PATH = ("DisplaySettingScreen", "Quality Preset_TMP", "Quality Dropdown")

PREFIX_LEN = 28  # m_GameObject PPtr, m_Enabled + pad, m_Script PPtr


def aligned_string(s):
    """Unity serialized string: int32 length, UTF-8 bytes, pad to 4."""
    b = s.encode("utf-8")
    return struct.pack("<i", len(b)) + b + b"\0" * (-len(b) % 4)


def string_list(items):
    return struct.pack("<i", len(items)) + b"".join(aligned_string(s) for s in items)


class Scene:
    def __init__(self, env):
        self.env = env
        self.objs = env.file.objects
        self.names = {}
        for o in env.objects:
            if o.type.name == "GameObject":
                self.names[o.path_id] = o.read().m_Name

    def transform_of(self, go):
        for c in go.m_Component:
            o = self.objs[getattr(c, "component", c).m_PathID]
            if o.type.name in ("Transform", "RectTransform"):
                return o
        raise ValueError("GameObject %r has no transform" % go.m_Name)

    def children(self, tf_obj):
        """-> [(name, go_obj, tf_obj)]"""
        out = []
        for ch in tf_obj.read().m_Children:
            t = self.objs[ch.m_PathID]
            gp = t.read().m_GameObject.m_PathID
            out.append((self.names[gp], self.objs[gp], t))
        return out

    def child(self, tf_obj, name):
        hits = [c for c in self.children(tf_obj) if c[0] == name]
        if len(hits) != 1:
            raise ValueError("expected one child %r, found %d" % (name, len(hits)))
        return hits[0]

    def by_path(self, first, *rest):
        """The unique GameObject `first/rest...` -> (go_obj, tf_obj)."""
        roots = [p for p, n in self.names.items() if n == first]
        if len(roots) != 1:
            raise ValueError("expected one %s, found %d" % (first, len(roots)))
        go = self.objs[roots[0]]
        tf = self.transform_of(go.read())
        for name in rest:
            _, go, tf = self.child(tf, name)
        return go, tf

    def mbs_of(self, go_obj):
        out = []
        for c in go_obj.read().m_Component:
            o = self.objs[getattr(c, "component", c).m_PathID]
            if o.type.name == "MonoBehaviour":
                out.append(o)
        return out

    def descendant_mbs(self, tf_obj, go_name):
        """MonoBehaviour objects on descendants named `go_name`."""
        out = []
        for name, go_obj, t in self.children(tf_obj):
            if name == go_name:
                out += self.mbs_of(go_obj)
            out += self.descendant_mbs(t, go_name)
        return out


def find_one(raw, needle, what):
    n = raw.count(needle)
    if n != 1:
        raise ValueError("%s: expected 1 occurrence, found %d" % (what, n))
    return raw.index(needle)


def script_id(raw):
    return struct.unpack_from("<q", raw, 20)[0]


# ------------------------------------------------------------------ Russian button
def call_block_start(raw, type_name, what):
    """Offset of m_OnClick.m_PersistentCalls.m_Calls (int32 count, then calls)."""
    pos = find_one(raw, aligned_string(type_name), what)
    start = pos - 12 - 4  # PPtr m_Target (int32 FileID + int64 PathID), then count
    if struct.unpack_from("<i", raw, start)[0] != 1:
        raise ValueError("%s: expected exactly one persistent call" % what)
    return start


def onclick_button(scene, button_tf):
    """The UI.Button under `<button>/.../BtnRaycast`; m_OnClick is its last field."""
    mbs = scene.descendant_mbs(button_tf, "BtnRaycast")
    hits = [o for o in mbs if b"Assembly-CSharp" in o.get_raw_data()]
    if len(hits) != 1:
        raise ValueError("expected one UI.Button with a persistent call, found %d" % len(hits))
    return hits[0]


def enable_russian_button(scene):
    _, group = scene.by_path(LANG_SCREEN, "UIGroup")
    _, _, tmpl_tf = scene.child(group, TEMPLATE_BUTTON)
    _, ru_go, ru_tf = scene.child(group, TARGET_BUTTON)

    go = ru_go.read_typetree()
    go["m_IsActive"] = True
    ru_go.save_typetree(go)

    tmpl_pos = tmpl_tf.read_typetree()["m_AnchoredPosition"]
    tf = ru_tf.read_typetree()
    tf["m_AnchoredPosition"] = {"x": GRID_X, "y": tmpl_pos["y"]}
    ru_tf.save_typetree(tf)

    tmpl_btn, ru_btn = onclick_button(scene, tmpl_tf), onclick_button(scene, ru_tf)
    t_raw, r_raw = tmpl_btn.get_raw_data(), ru_btn.get_raw_data()
    block = t_raw[call_block_start(t_raw, TEMPLATE_TYPE, TEMPLATE_BUTTON):]
    find_one(block, aligned_string(TEMPLATE_METHOD), "template method")
    old_arg = aligned_string(TEMPLATE_ARGUMENT)
    find_one(block, old_arg, "template argument")
    block = block.replace(old_arg, aligned_string(CALL_ARGUMENT))
    ru_btn.set_raw_data(r_raw[:call_block_start(r_raw, PLACEHOLDER_TYPE, TARGET_BUTTON)] + block)

    old = aligned_string(OLD_LABEL)
    labels = [o for o in scene.descendant_mbs(ru_tf, "Text") if old in o.get_raw_data()]
    if len(labels) != 1:
        raise ValueError("expected one %r label, found %d" % (OLD_LABEL, len(labels)))
    raw = labels[0].get_raw_data()
    pos = find_one(raw, old, "label")
    labels[0].set_raw_data(raw[:pos] + aligned_string(LABEL) + raw[pos + len(old):])
    return "%s at (%.0f, %.0f) -> %s(%r)" % (TARGET_BUTTON, GRID_X, tmpl_pos["y"],
                                            TEMPLATE_METHOD, CALL_ARGUMENT)


# ------------------------------------------------------------------ FPS dropdown
def localize_fps_dropdown(scene, localize_ids):
    """Add a LocalizeDropdown with FPS_TERMS to the FPS dropdown."""
    fps_go, _ = scene.by_path(*FPS_PATH)
    if any(script_id(o.get_raw_data()) in localize_ids for o in scene.mbs_of(fps_go)):
        raise ValueError("FPS dropdown already has a LocalizeDropdown")
    quality_go, _ = scene.by_path(*QUALITY_PATH)
    tmpl = [o for o in scene.mbs_of(quality_go) if script_id(o.get_raw_data()) in localize_ids]
    if len(tmpl) != 1:
        raise ValueError("expected one LocalizeDropdown on the quality dropdown, found %d"
                         % len(tmpl))
    tmpl = tmpl[0]
    t_raw = tmpl.get_raw_data()
    # LocalizeDropdown = prefix, string m_Name (empty), List<string> _Terms.
    if t_raw[PREFIX_LEN:PREFIX_LEN + 4] != b"\0\0\0\0":
        raise ValueError("template LocalizeDropdown has an unexpected m_Name")

    new_id = max(scene.objs) + 1
    raw = (t_raw[:4] + struct.pack("<q", fps_go.path_id) + t_raw[12:PREFIX_LEN]
           + aligned_string("") + string_list(FPS_TERMS))
    clone = attr.evolve(tmpl, path_id=new_id, data=raw)
    scene.objs[new_id] = clone
    scene.env.file.mark_changed()

    go = fps_go.read_typetree()
    go["m_Component"].append({"component": {"m_FileID": 0, "m_PathID": new_id}})
    fps_go.save_typetree(go)
    return "LocalizeDropdown #%d on %s" % (new_id, "/".join(FPS_PATH))


def is_patched(path):
    """True if the scene file carries our patch (stock scenes have no "Русский")."""
    with open(path, "rb") as f:
        return LABEL.encode("utf-8") in f.read()


def patch_scene_file(path, localize_ids):
    """Read the scene at `path` into memory (so the file itself can be replaced
    afterwards on Windows), patch it -> (bytes, description)."""
    import UnityPy
    with open(path, "rb") as f:
        env = UnityPy.load(f.read())
    what = patch_scene(env, localize_ids)
    return env.file.save(), what


def patch_scene(env, localize_ids):
    """Patch one scene in place. `localize_ids` = MonoScript pathIDs of
    LocalizeDropdown (i2lib.script_path_ids(data_dir, LOCALIZE_DROPDOWN_CLASS)).
    Returns a short description of what changed."""
    scene = Scene(env)
    return "; ".join((enable_russian_button(scene), localize_fps_dropdown(scene, localize_ids)))
