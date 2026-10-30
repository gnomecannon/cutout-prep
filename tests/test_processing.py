"""Small, independent image and filesystem contracts; no private photographs."""
from __future__ import annotations

import hashlib
import io
import json
import os
import copy
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw

from cutout_prep import process_images as prep


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artwork(color=(175, 71, 32), *, islands=False):
    rgba = np.zeros((64, 64, 4), dtype=np.uint8)
    rgba[..., :3] = (0, 20, 255)  # Hidden color must never bleed into the subject.
    rgba[8:56, 8:56] = (*color, 255)
    if islands:
        rgba[8:56, 8:56, 3] = 0
        rgba[8:56, 8:36] = (*color, 255)
        rgba[12:24, 45:56] = (35, 180, 95, 255)
    return rgba


def render_options(**updates):
    options = {
        **prep.DEFAULTS,
        "size": 64,
        "padding": 8,
        "background": "keep",
        "exposure": "none",
        "shadow_lift": 0,
        "saturation": 1,
        "edge_decontaminate": False,
    }
    options.update(updates)
    return options


def render_pixels(rgba, **updates):
    profile = Path(prep.__file__).with_name("sRGB.icc").read_bytes()
    encoded, details, warnings = prep.render(rgba, render_options(**updates), profile)
    with Image.open(io.BytesIO(encoded)) as image:
        return np.array(image), image.info, details, warnings


class PixelContracts(unittest.TestCase):
    def test_diagonal_connections_and_exact_coverage_samples(self):
        alpha = np.zeros((8, 9), np.uint8)
        alpha[1, 1] = 255
        alpha[2, 2] = 91
        alpha[3, 3] = 17
        alpha[5, 7] = 255
        clean, info = prep.largest_component(alpha)
        expected = alpha.copy()
        expected[5, 7] = 0
        np.testing.assert_array_equal(clean, expected)
        self.assertEqual(info["removed_pixels"], 1)
        np.testing.assert_array_equal(alpha[1:4, 1:4].diagonal(), [255, 91, 17])

    def test_identity_framing_preserves_visible_rgb_and_holes(self):
        rgba = artwork()
        rgba[25:30, 24:31, 3] = 0
        before = rgba.copy()
        out, info, details, _ = render_pixels(rgba, components="all")
        np.testing.assert_array_equal(out[..., 3], rgba[..., 3])
        np.testing.assert_array_equal(out[rgba[..., 3] > 0], rgba[rgba[..., 3] > 0])
        np.testing.assert_array_equal(rgba, before)
        self.assertEqual(details["output_bbox"], [8, 8, 56, 56])
        self.assertTrue(info.get("icc_profile"))
        self.assertNotIn("exif", info)

    def test_components_all_preserves_detached_artwork(self):
        rgba = artwork(islands=True)
        out, _, details, _ = render_pixels(rgba, components="all")
        self.assertGreater(np.count_nonzero((out[..., 1] > out[..., 0]) & (out[..., 3] > 0)), 50)
        self.assertEqual(details["cleanup"]["removed_pixels"], 0)

    def test_largest_components_removes_detached_artwork(self):
        out, _, details, _ = render_pixels(artwork(islands=True), components="largest")
        self.assertEqual(np.count_nonzero((out[..., 1] > out[..., 0]) & (out[..., 3] > 0)), 0)
        self.assertGreater(details["cleanup"]["removed_pixels"], 0)

    def test_resampling_is_linear_light_not_encoded_rgb_average(self):
        checker = (np.indices((96, 96)).sum(axis=0) % 2 * 255).astype(np.uint8)
        rgba = np.dstack((checker, checker, checker, np.full_like(checker, 255)))
        out, _, _, _ = render_pixels(rgba)
        # Equal black/white energy is 0.5 in linear light, or about188 in sRGB.
        expected = round(255 * (1.055 * .5 ** (1 / 2.4) - .055))
        central = out[22:42, 22:42, :3].astype(int)
        self.assertLessEqual(int(np.abs(central - expected).max()), 1)
        self.assertGreater(int(central.min()), 180)

    def test_hidden_blue_never_contaminates_resampled_red_edge(self):
        image = Image.new("RGBA", (96, 96), (0, 0, 255, 0))
        ImageDraw.Draw(image).ellipse((7, 7, 88, 88), fill=(220, 0, 0, 255))
        out, _, _, _ = render_pixels(np.array(image))
        visible = out[..., 3] > 0
        self.assertTrue(np.any((out[..., 3] > 0) & (out[..., 3] < 255)))
        self.assertLessEqual(int(out[..., 1:3][visible].max()), 1)
        self.assertLessEqual(int(np.abs(out[..., 0][visible].astype(int) - 220).max()), 1)

    def test_invisible_rgb_padding_never_changes_visible_samples(self):
        rng = np.random.default_rng(7)
        rgb = rng.random((16, 20, 3), dtype=np.float32)
        alpha = np.zeros((16, 20), np.uint8)
        alpha[4:12, 5:15] = 255
        alpha[3, 7] = 12
        before = rgb.copy()
        filled = prep.edge_fill(rgb, alpha)
        np.testing.assert_array_equal(filled[alpha > 0], before[alpha > 0])
        np.testing.assert_array_equal(rgb, before)
        self.assertTrue(np.isfinite(filled).all())

    def test_invalid_transforms_are_refused(self):
        invalid = (
            [[0, 0, 0], [0, 0, 0], [0, 0, 1]],
            [[1, .2, 0], [0, 1, 0], [0, 0, 1]],
            [[1, 0, 0], [0, 1, 0], [0, .1, 1]],
            [[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]],
        )
        for matrix in invalid:
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                prep.uv_matrix(matrix, 64)

    def test_fully_transparent_input_is_refused(self):
        with self.assertRaises(ValueError):
            render_pixels(np.zeros((16, 16, 4), np.uint8))


class CliContracts(unittest.TestCase):
    def setUp(self):
        test_root = os.environ.get("CUTOUT_PREP_TEST_TMP")
        self.temporary = tempfile.TemporaryDirectory(prefix="cutout-prep-test-", dir=test_root)
        self.root = Path(self.temporary.name)
        self.inputs = self.root / "input"
        self.inputs.mkdir()
        self.output = self.inputs / "Processed"
        self.source = self.inputs / "object.png"
        Image.fromarray(artwork()).save(self.source)

    def tearDown(self):
        self.temporary.cleanup()

    def cli(self, *switches, expected=0):
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS="2", OPENBLAS_NUM_THREADS="2", MKL_NUM_THREADS="2")
        result = subprocess.run(
            [sys.executable, "-B", "-m", "cutout_prep", str(self.inputs),
             "--preset", "artwork", "--size", "64", "--padding", "8", *map(str, switches)],
            cwd=self.root, env=env, capture_output=True, text=True, timeout=90,
        )
        self.assertEqual(result.returncode, expected, result.stdout + "\n" + result.stderr)
        return result

    def report(self):
        return json.loads((self.output / prep.REPORT).read_text(encoding="utf-8"))

    def test_initial_process_and_identical_rerun_preserve_original(self):
        original = digest(self.source)
        self.cli()
        report = self.report()
        self.assertEqual(report["counts"], {"processed": 1})
        exported = self.output / "object_BaseColor.png"
        prepared = digest(exported)
        self.cli()
        self.assertEqual(self.report()["counts"], {"unchanged": 1})
        self.assertEqual(digest(exported), prepared)
        self.assertEqual(digest(self.source), original)
        self.assertFalse((self.output / ".image-preparation.lock").exists())

    def test_changed_source_requires_explicit_update(self):
        self.cli()
        exported = self.output / "object_BaseColor.png"
        previous = digest(exported)
        Image.fromarray(artwork((90, 150, 30))).save(self.source)
        self.cli(expected=2)
        self.assertEqual(self.report()["counts"], {"needs_update": 1})
        self.assertEqual(digest(exported), previous)
        self.cli("--update")
        self.assertEqual(self.report()["counts"], {"processed": 1})
        self.assertNotEqual(digest(exported), previous)

    def test_dependency_provenance_invalidates_cache_without_overwriting_manual_art(self):
        arguments = [str(self.inputs), "--preset", "artwork", "--size", "64", "--padding", "8"]
        base = prep.environment_provenance()
        changed = copy.deepcopy(base)
        changed["libraries"]["Pillow"] = "simulated-different-version"
        later = copy.deepcopy(changed)
        later["libraries"]["NumPy"] = "simulated-later-version"

        def run(environment, switches=()):
            with patch.object(prep, "environment_provenance", return_value=environment):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    return prep.main([*arguments, *switches])

        self.assertEqual(run(base), 0)
        original_signature = self.report()["outputs"]["object_BaseColor.png"]["signature"]
        exported = self.output / "object_BaseColor.png"
        original_pixels = digest(exported)
        self.assertEqual(run(base), 0)
        self.assertEqual(self.report()["counts"], {"unchanged": 1})
        self.assertEqual(run(changed), 2)
        self.assertEqual(self.report()["counts"], {"needs_update": 1})
        self.assertEqual(digest(exported), original_pixels)
        self.assertEqual(run(changed, ("--update",)), 0)
        report = self.report()
        self.assertEqual(report["counts"], {"processed": 1})
        self.assertEqual(report["environment"], changed)
        self.assertNotEqual(report["outputs"][exported.name]["signature"], original_signature)
        exported.write_bytes(b"deliberately edited artist output")
        self.assertEqual(run(later, ("--update",)), 2)
        self.assertEqual(exported.read_bytes(), b"deliberately edited artist output")
        self.assertEqual(self.report()["counts"], {"error": 1})

    def test_manual_output_and_duplicate_alias_are_protected(self):
        self.cli()
        exported = self.output / "object_BaseColor.png"
        with Image.open(exported) as image:
            edited = np.array(image)
        edited[20, 20, :3] = (31, 47, 59)
        Image.fromarray(edited).save(exported)
        manual = digest(exported)
        (self.inputs / "copy.png").write_bytes(self.source.read_bytes())
        self.cli("--update", expected=2)
        self.assertEqual(digest(exported), manual)
        self.assertEqual(sorted(p.name for p in self.output.glob("*.png")), [exported.name])
        self.assertEqual(self.report()["counts"], {"error": 2})

    def test_unmanaged_png_is_not_overwritten(self):
        self.output.mkdir()
        exported = self.output / "object_BaseColor.png"
        exported.write_bytes(b"unmanaged artist file")
        original = digest(exported)
        self.cli("--update", expected=2)
        self.assertEqual(digest(exported), original)
        self.assertEqual(self.report()["counts"], {"error": 1})

    def test_unmanaged_preview_is_not_overwritten(self):
        self.output.mkdir()
        preview = self.output / prep.PREVIEW
        preview.write_bytes(b"unmanaged preview")
        original = digest(preview)
        self.cli(expected=2)
        self.assertEqual(digest(preview), original)
        self.assertTrue(any("Preview" in f.get("message", "") for f in self.report()["files"]))

    def test_duplicate_images_produce_one_export(self):
        (self.inputs / "copy.png").write_bytes(self.source.read_bytes())
        self.cli()
        report = self.report()
        self.assertEqual(report["counts"], {"processed": 1, "duplicate": 1})
        self.assertEqual(len(list(self.output.glob("*.png"))), 1)
        duplicate = next(f for f in report["files"] if f["status"] == "duplicate")
        self.assertIn(duplicate["duplicate_of"], report["outputs"])

    def test_case_insensitive_name_collision_creates_no_exports(self):
        Image.fromarray(artwork((40, 130, 90))).save(self.inputs / "second.png")
        settings = {"images": {"object.png": {"name": "Shared"}, "second.png": {"name": "shared"}}}
        (self.inputs / "image-settings.json").write_text(json.dumps(settings), encoding="utf-8")
        self.cli(expected=2)
        self.assertEqual(self.report()["counts"], {"error": 2})
        self.assertEqual(list(self.output.glob("*.png")), [])

    def test_recursive_rerun_excludes_its_output(self):
        self.cli("--recursive")
        self.cli("--recursive")
        report = self.report()
        self.assertEqual([f["source"] for f in report["files"]], ["object.png"])
        self.assertEqual(report["counts"], {"unchanged": 1})

    def test_recursive_scan_does_not_follow_child_links(self):
        other = self.root / "other"
        other.mkdir()
        outside = other / "unselected.png"
        Image.fromarray(artwork((41, 160, 70))).save(outside)
        original = digest(outside)
        try:
            os.symlink(other, self.inputs / "linked_directory", target_is_directory=True)
            os.symlink(self.source, self.inputs / "linked_file.png")
        except (OSError, NotImplementedError) as exc:
            self.skipTest("This environment does not permit creating test symlinks: " + str(exc))
        self.cli("--recursive")
        self.assertEqual([f["source"] for f in self.report()["files"]], ["object.png"])
        self.assertEqual(digest(outside), original)
        self.assertEqual(len(list(self.output.glob("*.png"))), 1)

    def test_unicode_source_filename_round_trips_through_report(self):
        renamed = self.inputs / "specimen_é_葉.png"
        self.source.rename(renamed)
        original = digest(renamed)
        self.cli()
        report = self.report()
        self.assertEqual(report["files"][0]["source"], renamed.name)
        self.assertTrue((self.output / "specimen_é_葉_BaseColor.png").is_file())
        self.assertEqual(digest(renamed), original)

    def test_optional_mask_is_excluded_from_input_scan(self):
        Image.new("L", (64, 64), 255).save(self.inputs / "mask.png")
        (self.inputs / "image-settings.json").write_text(
            json.dumps({"images": {"object.png": {"mask": "mask.png"}}}), encoding="utf-8")
        self.cli()
        self.assertEqual([f["source"] for f in self.report()["files"]], ["object.png"])
        self.assertEqual(len(list(self.output.glob("*.png"))), 1)

    def test_output_may_not_equal_or_contain_input(self):
        for destination in (self.inputs, self.root):
            with self.subTest(destination=destination):
                self.cli("--output", destination, expected=1)
                self.assertFalse((destination / prep.REPORT).exists())
                self.assertFalse((destination / ".image-preparation.lock").exists())

    def test_existing_lock_is_preserved(self):
        self.output.mkdir()
        lock = self.output / ".image-preparation.lock"
        lock.write_bytes(b"existing batch")
        self.cli(expected=1)
        self.assertEqual(lock.read_bytes(), b"existing batch")
        self.assertFalse((self.output / prep.REPORT).exists())

    def test_existing_empty_or_malformed_report_is_never_replaced(self):
        self.output.mkdir()
        report = self.output / prep.REPORT
        for payload in (b"{}", b"[]", b"null", b"{broken", b'{"tool":"another tool"}'):
            with self.subTest(payload=payload):
                report.write_bytes(payload)
                self.cli("--update", expected=1)
                self.assertEqual(report.read_bytes(), payload)
                self.assertEqual(list(self.output.glob("*.png")), [])

    def test_invalid_settings_leave_sources_untouched(self):
        source_before = digest(self.source)
        settings = self.inputs / "image-settings.json"
        settings.write_text(json.dumps({"defaults": {"unknown_setting": True}}), encoding="utf-8")
        self.cli(expected=1)
        self.assertEqual(digest(self.source), source_before)
        self.assertFalse((self.output / prep.REPORT).exists())
        self.assertEqual(list(self.output.glob("*.png")), [])

    def test_unsafe_output_names_are_refused(self):
        for name in ("../escaped", "CON", "trailing."):
            with self.subTest(name=name):
                (self.inputs / "image-settings.json").write_text(
                    json.dumps({"images": {"object.png": {"name": name}}}), encoding="utf-8")
                self.cli(expected=2)
                self.assertEqual(self.report()["counts"], {"error": 1})
                self.assertEqual(list(self.output.glob("*.png")), [])
                self.assertFalse((self.root / "escaped.png").exists())

    def test_numeric_16bit_png_requires_explicit_conversion(self):
        self.source.unlink()
        numeric = self.inputs / "numeric.png"
        Image.fromarray(np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)).save(numeric)
        original = digest(numeric)
        self.cli(expected=2)
        report = self.report()
        self.assertEqual(report["counts"], {"error": 1})
        self.assertIn("High-bit-depth numeric", report["files"][0]["message"])
        self.assertEqual(digest(numeric), original)
        self.assertEqual(list(self.output.glob("*.png")), [])

    def test_artwork_preset_keeps_disconnected_pieces(self):
        Image.fromarray(artwork(islands=True)).save(self.source)
        self.cli()
        with Image.open(self.output / "object_BaseColor.png") as image:
            out = np.array(image)
        self.assertGreater(np.count_nonzero((out[..., 1] > out[..., 0]) & (out[..., 3] > 0)), 50)
        defaults = self.report()["defaults"]
        self.assertEqual(defaults["components"], "all")
        self.assertEqual(defaults["exposure"], "none")
        self.assertEqual(defaults["shadow_lift"], 0)
        self.assertEqual(defaults["raw_tone"], "neutral")

    def test_automatic_photo_export_requires_review_and_keeps_real_opening(self):
        paper = (221, 225, 228)
        photograph = Image.new("RGB", (128, 128), paper)
        draw = ImageDraw.Draw(photograph)
        draw.ellipse((32, 10, 96, 117), fill=(164, 78, 42))
        draw.ellipse((53, 25, 73, 45), fill=paper)
        photograph.save(self.source)
        original = digest(self.source)
        self.cli("--preset", "photo", "--exposure", "none", "--shadow-lift", "0", expected=2)
        report = self.report()
        self.assertEqual(report["counts"], {"processed": 1, "review_required": 1})
        self.assertTrue(report["files"][0]["review_required"])
        self.assertEqual(digest(self.source), original)
        with Image.open(self.output / "object_BaseColor.png") as image:
            alpha = np.array(image.getchannel("A"))
        self.assertEqual(int(alpha[20, 32]), 0)
        self.assertEqual(int(alpha[37, 32]), 255)
        self.assertTrue(np.all(alpha[:7] == 0))


if __name__ == "__main__":
    unittest.main()
