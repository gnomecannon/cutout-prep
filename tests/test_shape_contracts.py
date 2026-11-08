"""Known-alpha natural-shape regressions; real-photo quality is reviewed separately."""
import unittest

import numpy as np
from scipy import ndimage as ndi

from cutout_prep import auto_cutout, leaf_geometry
from tools.shape_fixtures import KINDS, photograph, specimen


class ShapeContracts(unittest.TestCase):
    def test_opaque_photo_extraction_keeps_teeth_lobes_and_branches(self):
        for kind in KINDS:
            with self.subTest(shape=kind):
                expected = np.array(specimen(kind))[:,:,3] >= 128
                photo = np.array(photograph(kind).convert('RGBA'))
                rgba, details = auto_cutout.extract(photo)
                actual = rgba[:,:,3] >= 128
                recall = (actual & expected).sum()/expected.sum()
                leakage = (actual & ~expected).sum()/max(actual.sum(),1)
                # Interior and exterior checks are independent of the extractor.
                self.assertGreater(recall, .97, (kind, recall, details))
                self.assertLess(leakage, .035, (kind, leakage, details))
                self.assertFalse(actual[0].any() or actual[-1].any())

    def test_real_holes_stay_open_and_discolored_tissue_stays_opaque(self):
        photo = np.array(photograph('damaged').convert('RGBA'))
        rgba, _ = auto_cutout.extract(photo)
        self.assertEqual(int(rgba[235,184,3]), 0)
        self.assertEqual(int(rgba[313,307,3]), 0)
        self.assertEqual(int(rgba[233,270,3]), 255)
        np.testing.assert_array_equal(rgba[233,270,:3], photo[233,270,:3])
        # Open background between lobes is not an enclosed leaf interior.
        self.assertEqual(int(rgba[155,370,3]), 0)

    def test_rotation_keeps_thin_branches_holes_and_transparent_padding(self):
        for kind in KINDS:
            with self.subTest(shape=kind):
                alpha = np.array(specimen(kind))[:,:,3]
                result = leaf_geometry.alpha_canvas(alpha, leaf_geometry.rotated_frame(alpha,90,12))[:,:,3]
                self.assertEqual(ndi.label(result>=128, np.ones((3,3)))[1], 1)
                self.assertGreater(np.count_nonzero(result), np.count_nonzero(alpha)*.93)
                self.assertFalse(result[:12].any() or result[-12:].any() or result[:,:12].any() or result[:,-12:].any())
                if kind == 'damaged':
                    holes = ndi.binary_fill_holes(result>=128) & (result<128)
                    self.assertEqual(ndi.label(holes)[1],2)


if __name__ == '__main__':unittest.main()
