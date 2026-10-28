"""Use one Cyrillic fallback while preserving the game's Latin glyphs/atlases.

Game 1.04 removed RussianOutline. Fredoka's fallback graph now finds a handful
of Cyrillic glyphs in CJK fonts before reaching TMP's default Liberation Sans.
Clone the two Fredoka entry points into resources.assets and put the embedded
dynamic Liberation Sans ahead of CJK fallbacks on the clone with Latin glyphs.
Scene text references use these clones; sharedassets files stay untouched.

fontpatch_schema.json is the Unity 6000.0.66f2 TMP field layout generated from
Unity.TextMeshPro.dll, with standalone UInt8/bool fields aligned to 4 bytes.
Every read/write must round-trip exactly before we change a serialized object.
No generator or .NET runtime is required by the installer.
"""
import json
from functools import lru_cache
from pathlib import Path
import struct

import attr
import UnityPy
from UnityPy.helpers.TypeTreeNode import TypeTreeNode
from UnityPy.helpers import TypeTreeHelper
from UnityPy.streams import EndianBinaryWriter, EndianBinaryReader

import i2lib

NAMES = ("FredokaOne-Regular SDF border", "FredokaOne-Regular SDF border1")


@lru_cache(maxsize=2)
def schema(kind):
    with Path(__file__).with_name("fontpatch_schema.json").open(encoding="utf-8") as f:
        return TypeTreeNode.from_list(json.load(f)[kind])


def encode(tree, kind, asset):
    writer = EndianBinaryWriter(endian=asset.header.endian)
    TypeTreeHelper.write_typetree(tree, schema(kind), writer, asset)
    return writer.bytes


def read_checked(obj, kind):
    raw = obj.data if obj.data is not None else obj.get_raw_data()
    tree = read_tree(obj, kind, raw)
    if encode(tree, kind, obj.assets_file) != raw:
        raise ValueError("TMP %s #%d does not round-trip exactly" % (kind, obj.path_id))
    return tree


def read_tree(obj, kind, raw):
    return TypeTreeHelper.read_typetree(schema(kind),
        EndianBinaryReader(raw, endian=obj.assets_file.header.endian), as_dict=True,
        assetsfile=obj.assets_file, byte_size=len(raw), check_read=True)


def named_font(env, name):
    # Inspect the MonoBehaviour name only; unrelated objects need no type tree.
    hits = []
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = obj.get_raw_data()
        if len(raw) > 32 and i2lib.Reader(raw, 28).string() == name:
            hits.append(obj)
    if len(hits) != 1:
        raise ValueError("expected one font %r, found %d" % (name, len(hits)))
    return hits[0]


def external_id(asset, name):
    hits = [i + 1 for i, ref in enumerate(asset.externals)
            if Path(ref.path.replace('\\', '/')).name == name]
    if len(hits) != 1:
        raise ValueError("expected one external %s, found %d" % (name, len(hits)))
    return hits[0]


def patch_resources(env, data_dir):
    with open(Path(data_dir) / "sharedassets0.assets", "rb") as f:
        shared = UnityPy.load(f.read())
    dynamic = named_font(env, "LiberationSans SDF - Fallback")
    dynamic_tree = read_checked(dynamic, "font")
    if dynamic_tree["m_AtlasPopulationMode"] != 1 or not dynamic_tree["m_SourceFontFile"]["m_PathID"]:
        raise ValueError("Liberation Sans fallback has no dynamic source font")
    templates = [named_font(shared, name) for name in NAMES]
    trees = [read_checked(obj, "font") for obj in templates]
    # The wrapper has no characters, so Latin must first reach border1. Only
    # border1 gets the dynamic fallback first; putting it on the wrapper would
    # also replace the game's Latin typeface.
    if trees[0]["m_CharacterTable"] or not trees[1]["m_CharacterTable"]:
        raise ValueError("unexpected Fredoka wrapper/body character tables")
    if trees[0]["m_FallbackFontAssetTable"][0] != {"m_FileID": 0, "m_PathID": templates[1].path_id}:
        raise ValueError("unexpected Fredoka fallback order")
    start = max(env.file.objects) + 1
    font_ids = {obj.path_id: start + i for i, obj in enumerate(templates)}
    shared_id = external_id(env.file, "sharedassets0.assets")
    externals = {i + 1: external_id(env.file, Path(ref.path.replace('\\', '/')).name)
                 for i, ref in enumerate(shared.file.externals)}

    def remap(value):
        if isinstance(value, dict):
            if set(value) == {"m_FileID", "m_PathID"}:
                fid, pid = value["m_FileID"], value["m_PathID"]
                if not pid:
                    return dict(value)
                if fid == 0:
                    return {"m_FileID": 0 if pid in font_ids else shared_id,
                            "m_PathID": font_ids.get(pid, pid)}
                return {"m_FileID": externals[fid], "m_PathID": pid}
            return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item) for item in value]
        return value

    for original, tree in zip(templates, trees):
        tree = remap(tree)
        tree["m_Name"] = "TCGRU " + tree["m_Name"]
        if original is templates[1]:
            tree["m_FallbackFontAssetTable"].insert(0, {"m_FileID": 0, "m_PathID": dynamic.path_id})
        raw = encode(tree, "font", env.file)
        clone = attr.evolve(dynamic, path_id=font_ids[original.path_id], data=raw,
            reader=EndianBinaryReader(raw, endian=env.file.header.endian),
            byte_start=0, byte_size=len(raw))
        env.file.objects[clone.path_id] = clone
    env.file.mark_changed()
    context = {"font_ids": font_ids, "text_ids":
               i2lib.script_path_ids(data_dir, "TMPro.TextMeshProUGUI") |
               i2lib.script_path_ids(data_dir, "TMPro.TextMeshPro")}
    patch_text_fonts(env, context, resources=True)
    return context


def patch_text_fonts(env, context, resources=False):
    shared_id = external_id(env.file, "sharedassets0.assets")
    resource_id = 0 if resources else external_id(env.file, "resources.assets")
    changed = 0
    for obj in env.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        raw = obj.data if obj.data is not None else obj.get_raw_data()
        if len(raw) < 32 or struct.unpack_from('<q', raw, 20)[0] not in context["text_ids"]:
            continue
        tree = read_tree(obj, "text", raw)
        old = tree["m_fontAsset"]
        if old["m_FileID"] != shared_id or old["m_PathID"] not in context["font_ids"]:
            continue
        # Keep every other text byte, including material, outline, spacing,
        # gradients and layout. The clones use the original Latin atlases.
        before = struct.pack('<iq', old["m_FileID"], old["m_PathID"])
        after = struct.pack('<iq', resource_id, context["font_ids"][old["m_PathID"]])
        if raw.count(before) != 1:
            raise ValueError("TMP text #%d has an ambiguous font reference" % obj.path_id)
        obj.set_raw_data(raw.replace(before, after))
        changed += 1
    return changed
