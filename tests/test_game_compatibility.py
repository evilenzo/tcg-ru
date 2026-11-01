"""Integration checks against a local game; skipped on CI without game files.

Run: python -m unittest discover -s tests -v
"""
import pathlib
import subprocess
import sys
import tempfile
import shutil
import unittest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import i2lib
import scenepatch
import installer

DATA = i2lib.find_data_dir()


def original_path(name):
    """Prefer restored Steam originals over backups left by an earlier update."""
    path = pathlib.Path(DATA) / name
    if name in installer.FILES:
        ids = i2lib.script_path_ids(DATA, i2lib.I2_CLASS)
        if installer.is_patched(name, path, ids):
            return pathlib.Path(str(path) + ".orig-backup")
    return path


@unittest.skipUnless(DATA, "requires a local installation of the game")
class GameCompatibilityTests(unittest.TestCase):
    def test_scene_rejects_mesh_reference_to_texture_before_patching(self):
        import UnityPy
        data = pathlib.Path(DATA)
        env = UnityPy.load(original_path("level2").read_bytes())
        shared_id = next(i + 1 for i, ref in enumerate(env.file.externals)
                         if ref.path == "sharedassets0.assets")
        with (data / "sharedassets0.assets").open("rb") as stream:
            shared = UnityPy.load(stream)
            texture_id = next(o.path_id for o in shared.objects
                              if o.type.name == "Texture2D")
        mesh = next(o for o in env.objects if o.type.name == "MeshFilter")
        tree = mesh.read_typetree()
        tree["m_Mesh"] = {"m_FileID": shared_id, "m_PathID": texture_id}
        mesh.save_typetree(tree)
        with tempfile.TemporaryDirectory(dir=REPO / "build") as tmp:
            source = pathlib.Path(tmp) / "level2"
            source.write_bytes(i2lib.save_asset_file(env))
            shutil.copy2(data / "sharedassets0.assets", pathlib.Path(tmp) / "sharedassets0.assets")
            ids = i2lib.script_path_ids(DATA, scenepatch.LOCALIZE_DROPDOWN_CLASS)
            with self.assertRaisesRegex(ValueError, "expected Mesh.*Texture2D"):
                scenepatch.patch_scene_file(source, ids)

    def test_cyrillic_fallback_precedes_fonts_with_partial_cyrillic(self):
        import fontpatch
        import UnityPy
        data = pathlib.Path(DATA)
        source = original_path("resources.assets")
        env = UnityPy.load(source.read_bytes())
        context = fontpatch.patch_resources(env, DATA)
        fonts = context["font_ids"]
        self.assertEqual(len(fonts), 2)
        clones = [obj.read_typetree(nodes=fontpatch.schema("font"))
                  for obj in env.objects if obj.path_id in fonts.values()]
        body = next(t for t in clones if t["m_Name"].endswith("border1"))
        first = body["m_FallbackFontAssetTable"][0]
        fallback = env.file.objects[first["m_PathID"]].read_typetree(nodes=fontpatch.schema("font"))
        self.assertEqual(first["m_FileID"], 0)
        self.assertEqual(fallback["m_Name"], "LiberationSans SDF - Fallback")
        self.assertEqual(fallback["m_AtlasPopulationMode"], 1)
        self.assertEqual(len(body["m_CharacterTable"]), 96)
        # Follow the actual serialized graph after saving/reloading. Every
        # Cyrillic character must reach the same dynamic font before CJK fonts.
        saved = UnityPy.load(i2lib.save_asset_file(env))
        font_cache = {}
        alphabet = "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯабвгдеёжзийклмнопрстуфхцчшщъыьэюя"

        def resolve_local(pid, char, seen=None):
            seen = set() if seen is None else seen
            if pid in seen:
                return None
            seen.add(pid)
            if pid not in font_cache:
                font_cache[pid] = saved.file.objects[pid].read_typetree(nodes=fontpatch.schema("font"))
            font = font_cache[pid]
            if font["m_AtlasPopulationMode"] == 1:
                return font["m_Name"]
            if ord(char) in {c["m_Unicode"] for c in font["m_CharacterTable"]}:
                return font["m_Name"]
            for ref in font["m_FallbackFontAssetTable"]:
                if ref["m_FileID"] != 0:
                    self.fail("Cyrillic/Latin reached an original CJK fallback: " + char)
                result = resolve_local(ref["m_PathID"], char, seen)
                if result:
                    return result
            return None

        for pid in fonts.values():
            self.assertEqual({resolve_local(pid, ch) for ch in alphabet},
                             {"LiberationSans SDF - Fallback"})
            self.assertEqual({resolve_local(pid, ch) for ch in "ABCxyz0129"},
                             {"TCGRU FredokaOne-Regular SDF border1"})
        patched, _ = scenepatch.patch_scene_file(original_path("level1"),
            i2lib.script_path_ids(DATA, scenepatch.LOCALIZE_DROPDOWN_CLASS), context)
        scene = scenepatch.Scene(UnityPy.load(patched))
        _, button = scene.by_path("Russian_Button")
        labels = scene.descendant_mbs(button, "Text")
        text = next(o.read_typetree(nodes=fontpatch.schema("text")) for o in labels
                    if scenepatch.aligned_string("Русский") in o.get_raw_data())
        self.assertIn(text["m_fontAsset"]["m_PathID"], fonts.values())

    def test_every_selected_scene_can_be_patched_and_reloaded(self):
        import UnityPy
        ids = i2lib.script_path_ids(DATA, scenepatch.LOCALIZE_DROPDOWN_CLASS)
        for name in scenepatch.SCENES:
            with self.subTest(scene=name):
                data, _ = scenepatch.patch_scene_file(original_path(name), ids)
                scene = scenepatch.Scene(UnityPy.load(data))
                go, _ = scene.by_path("Russian_Button")
                self.assertTrue(go.read().m_IsActive)
                fps, _ = scene.by_path(*scenepatch.FPS_PATH)
                terms = [o.get_raw_data() for o in scene.mbs_of(fps)
                         if scenepatch.script_id(o.get_raw_data()) in ids]
                self.assertEqual(len(terms), 1)
                self.assertIn(scenepatch.string_list(scenepatch.FPS_TERMS), terms[0])

    def test_unchanged_table_and_container_are_byte_identical(self):
        result = subprocess.run(
            [sys.executable, "tools/build_translation.py", "--selftest"],
            cwd=REPO, capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_game_version_is_readable(self):
        self.assertRegex(i2lib.game_version(DATA) or "", r"^\d+\.\d+")

    def test_install_reinstall_restore_and_failed_build_on_copies(self):
        import hashlib
        from unittest.mock import patch

        def digest(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()

        # A temporary game inside the repo: never install into the actual game.
        (REPO / "build").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=REPO / "build") as tmp:
            data = pathlib.Path(tmp) / "Card Shop Simulator_Data"
            data.mkdir()
            originals = {}
            for name in (*installer.FILES, "globalgamemanagers", "globalgamemanagers.assets", "sharedassets0.assets", "level0"):
                shutil.copy2(original_path(name), data / name)
                originals[name] = digest(data / name)
            for name in ("sharedassets1.assets", "sharedassets2.assets"):
                shutil.copy2(pathlib.Path(DATA) / name, data / name)
            output = pathlib.Path(tmp) / "output"
            result = subprocess.run(
                [sys.executable, "tools/build_translation.py", "--game", tmp,
                 "--out", str(output / "resources.assets")],
                cwd=REPO, capture_output=True, encoding="utf-8", errors="replace")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            ids = installer.check_game(str(data))
            # Stale backup from a previous update must be replaced with stock.
            (data / "level1.orig-backup").write_bytes(b"stale backup")
            installer.install(str(data), ids)
            first = {name: digest(data / name) for name in installer.FILES}
            for name in installer.FILES:
                self.assertTrue(installer.is_patched(name, data / name, ids), name)
                self.assertEqual(digest(data / (name + ".orig-backup")), originals[name])
                self.assertEqual(first[name], digest(output / name))
            self.assertEqual(digest(data / "level0"), originals["level0"])
            installer.install(str(data), ids)
            self.assertEqual(first, {name: digest(data / name) for name in installer.FILES})
            installer.restore(str(data))
            for name in installer.FILES:
                self.assertEqual(digest(data / name), originals[name])
            # A scene error after asset construction must not install a partial patch.
            with patch.object(scenepatch, "patch_scene_file", side_effect=ValueError("bad scene")):
                with self.assertRaises(installer.Fail):
                    installer.install(str(data), ids)
            for name in installer.FILES:
                self.assertEqual(digest(data / name), originals[name])


if __name__ == "__main__":
    unittest.main()
