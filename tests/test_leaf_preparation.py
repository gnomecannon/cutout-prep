import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from PIL import Image

from cutout_prep import leaf_batch, leaf_geometry, pair_alignment, process_images
from tools.shape_fixtures import specimen


def leaf():
    return np.array(specimen('damaged'))


class LeafGeometryTests(unittest.TestCase):
    def test_only_unambiguous_explicit_roles_form_pairs(self):
        pairs, ambiguous = leaf_geometry.named_pairs(['Oak_Front_Original.jpg', 'Oak_Back_Original.png', 'IMG_100.jpg', 'IMG_101.jpg'])
        self.assertEqual(pairs, [{'front': 'Oak_Front_Original.jpg', 'back': 'Oak_Back_Original.png'}])
        self.assertEqual(ambiguous, [])
        pairs, ambiguous = leaf_geometry.named_pairs(['Oak_Front.jpg', 'Oak_Front.png', 'Oak_Rear.jpg'])
        self.assertEqual(pairs, [])
        self.assertEqual(len(ambiguous), 3)

    def test_clear_stem_quarter_turns_and_round_subject_kept(self):
        alpha = leaf()[:, :, 3]
        self.assertEqual(leaf_geometry.stem_direction(alpha)['clockwise_degrees'], 0)
        self.assertEqual(leaf_geometry.stem_direction(np.flipud(alpha))['clockwise_degrees'], 180)
        right = leaf_geometry.stem_direction(np.rot90(alpha))
        self.assertTrue(right['confident'])
        self.assertEqual(right['clockwise_degrees'], 90)
        circle = np.zeros((256, 256), np.uint8);cv2.circle(circle, (128, 128), 90, 255, -1)
        self.assertFalse(leaf_geometry.stem_direction(circle)['confident'])

    def test_native_layout_roundtrip_keeps_padding(self):
        alpha = leaf()[:, :, 3]
        matrix = leaf_geometry.rotated_frame(alpha, 90, 20)
        uv = leaf_geometry.normalized_transform(matrix, 512)
        np.testing.assert_allclose(process_images.uv_matrix(uv, 512), matrix, atol=1e-10)
        image = leaf_geometry.alpha_canvas(alpha, matrix)
        bounds = Image.fromarray(image[:, :, 3]).getbbox()
        self.assertGreaterEqual(min(bounds[0], bounds[1], 512-bounds[2], 512-bounds[3]), 20)

    def test_wrong_outline_pair_is_not_forced(self):
        a = leaf();b = np.zeros_like(a);b[60:450, 60:450, 3] = 255
        plan = pair_alignment.estimate_alignment(a, b, padding=20)
        self.assertFalse(leaf_geometry.reliable_pair(plan))

    def test_pair_and_rotation_choices_reject_ambiguous_or_escaping_names(self):
        for value in [
            {'rotations': {'../photo.png': 90}},
            {'rotations': {'photo.png': True}},
            {'pairs': [{'front': 'a.png', 'back': 'a.png'}]},
            {'pairs': [{'front': 'a.png', 'back': 'b.png'}, {'front': 'c.png', 'back': 'b.png'}]},
        ]:
            with self.assertRaises(ValueError):leaf_batch.options(value)


class LeafBatchTests(unittest.TestCase):
    def test_prepared_artwork_keeps_translucency_and_separate_islands(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'Artwork';source.mkdir()
            image=np.zeros((128,128,4),np.uint8);image[30:80,20:65]=[180,75,35,90];image[85:105,95:110]=[40,110,170,150]
            Image.fromarray(image).save(source/'Card.png')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIn(process_images.main([str(source),'--output',str(root/'Baseline'),'--size','512','--preset','artwork']), (0,2))
                self.assertIn(leaf_batch.prepare(source,root/'Result',512,{'preserve_artwork':True}), (0,2))
            np.testing.assert_array_equal(np.array(Image.open(root/'Baseline/Card_BaseColor.png')),np.array(Image.open(root/'Result/Card_BaseColor.png')))
            saved=json.loads((root/'Result/LeafPreparation.json').read_text())
            self.assertIsNone(saved['analysis_size']);self.assertFalse(saved['options']['balance_lighting'])
    def test_one_missing_mask_does_not_block_other_photos(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'Photos';source.mkdir()
            Image.fromarray(leaf()).save(source/'Good.png');Image.fromarray(leaf()).save(source/'Bad.png')
            (source/'image-settings.json').write_text(json.dumps({'defaults':{'padding':20},'images':{'Bad.png':{'mask':'missing.png'}}}))
            with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(leaf_batch.prepare(source,root/'Results',512),2)
            report=json.loads((root/'Results/ProcessingReport.json').read_text())
            self.assertEqual(report['counts']['processed'],1)
            self.assertEqual(report['counts']['error'],1)
            self.assertTrue((root/'Results/Good_BaseColor.png').is_file())
    def test_color_and_real_hole_match_existing_processor_and_edits_survive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);source = root/'Photos';source.mkdir()
            original = source/'Leaf_Front.png';Image.fromarray(leaf()).save(original)
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIn(process_images.main([str(source), '--output', str(root/'Baseline'), '--size', '512', '--padding', '20']), (0, 2))
                # A saved framing preference remains authoritative.
                (source/'image-settings.json').write_text(json.dumps({'defaults': {'padding': 20}}))
                self.assertIn(leaf_batch.prepare(source, root/'Improved', 512, {'orient_stems': False, 'align_pairs': False}), (0, 2))
            baseline = np.array(Image.open(root/'Baseline/Leaf_Front_BaseColor.png'))
            output = root/'Improved/Leaf_Front_BaseColor.png'
            np.testing.assert_array_equal(np.array(Image.open(output)), baseline)
            output.write_bytes(b'manually edited export')
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(leaf_batch.prepare(source, root/'Improved', 512, {'rotations': {'Leaf_Front.png': 90}}), 2)
                self.assertEqual(leaf_batch.prepare(source, root/'Improved', 512), 2)
            saved=json.loads((root/'Improved/LeafPreparation.json').read_text())
            self.assertEqual(saved['options']['rotations'], {'Leaf_Front.png': 90})
            self.assertEqual(output.read_bytes(), b'manually edited export')
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)
            self.assertFalse(any(p.name.startswith('.leaf-previews-') for p in (root/'Improved').iterdir()))

    def test_automatic_pair_and_saved_recipe_are_respected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);source = root/'Photos';source.mkdir()
            front = leaf();Image.fromarray(front).save(source/'Oak_Front.png')
            rear = front[:, ::-1].copy();rear[:, :, :3] = (100, 80, 30)
            Image.fromarray(rear).save(source/'Oak_Back.png')
            (source/'image-settings.json').write_text(json.dumps({'defaults': {'padding': 20}}))
            with contextlib.redirect_stdout(io.StringIO()):self.assertIn(leaf_batch.prepare(source, root/'Pair', 512), (0, 2))
            report = json.loads((root/'Pair/LeafPreparation.json').read_text())
            self.assertEqual(report['counts']['aligned_pairs'], 1)
            a = np.array(Image.open(root/'Pair/Oak_Front_BaseColor.png'))[:, :, 3] > 127
            b = np.array(Image.open(root/'Pair/Oak_Back_BaseColor.png'))[:, :, 3] > 127
            self.assertGreater((a & b).sum() / (a | b).sum(), .96)
            # An excluded back (for example an unsuitable photograph) stays excluded.
            (source/'image-settings.json').write_text(json.dumps({'defaults': {'padding': 20}, 'images': {'Oak_Back.png': {'skip': True}, 'Oak_Front.png': {'rotation_degrees': 90}}}))
            with contextlib.redirect_stdout(io.StringIO()):self.assertIn(leaf_batch.prepare(source, root/'Saved', 512), (0, 2))
            saved = json.loads((root/'Saved/LeafPreparation.json').read_text())
            self.assertNotIn('Oak_Back.png', saved['files'])
            self.assertEqual(saved['files']['Oak_Front.png']['orientation']['reason'], 'Saved leaf geometry preserved')
