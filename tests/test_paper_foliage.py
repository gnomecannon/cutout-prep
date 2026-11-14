"""Real-photo contracts against the accepted fern, rather than colored circles."""
from pathlib import Path
import unittest

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from cutout_prep import paper_foliage


class ApprovedFernContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).parent/'fixtures/fern-paper'
        cls.rgb=np.array(Image.open(root/'source.jpg').convert('RGB'))
        cls.expected=np.array(Image.open(root/'accepted-mask.png'))
        cls.prior=cv2.resize(np.array(Image.open(root/'model-prior.png')).astype(np.float32)/255,
                             (cls.rgb.shape[1],cls.rgb.shape[0]))
        cls.color,cls.alpha,cls.info=paper_foliage.refine(
            cls.rgb,cls.prior,cls.rgb,np.round(cls.prior*255).astype(np.uint8),[255,255,255])

    def test_matches_approved_real_photo_reference(self):
        self.assertTrue(self.info['paper_foliage_applied'])
        actual=self.alpha>=128; expected=self.expected>=128
        self.assertGreater((actual&expected).sum()/(actual|expected).sum(),.98)
        self.assertGreater((actual&expected).sum()/expected.sum(),.995)
        self.assertLess((actual&~expected).sum()/actual.sum(),.015)

    def test_paper_inside_curled_leaflets_is_open_including_tinted_paper(self):
        expected=self.expected>=128
        holes=ndi.binary_fill_holes(expected)&~expected
        measured_gaps=holes&(ndi.distance_transform_edt(~expected)>=2)
        self.assertGreater(measured_gaps.sum(),1000)
        self.assertLess(((self.alpha>=128)&measured_gaps).sum()/measured_gaps.sum(),.012)

    def test_cleaning_does_not_leave_a_detached_frond(self):
        labels,count=ndi.label(self.alpha>=128,structure=np.ones((3,3)))
        sizes=np.bincount(labels.ravel())[1:]
        self.assertGreater(self.info['stems_recovered'],0)
        self.assertEqual(self.info['uncertain_connections'],0)
        self.assertLess(max(sorted(sizes,reverse=True)[1:],default=0),16)

    def test_deep_captured_tissue_keeps_its_color(self):
        deep=(self.alpha==255)&(ndi.distance_transform_edt(self.alpha>=250)>2)
        self.assertGreater(deep.sum(),10000)
        np.testing.assert_array_equal(self.color[deep],self.rgb[deep])

    def test_pale_subject_is_not_color_keyed(self):
        pale=np.repeat(self.rgb.mean(2).astype(np.uint8)[:,:,None],3,axis=2)
        supplied=np.round(self.prior*255).astype(np.uint8)
        color,alpha,info=paper_foliage.refine(pale,self.prior,pale,supplied,[255,255,255])
        self.assertFalse(info['paper_foliage_applied'])
        np.testing.assert_array_equal(color,pale)
        np.testing.assert_array_equal(alpha,supplied)

    def test_clipped_dark_tissue_does_not_become_a_color_key_hole(self):
        choices=np.argwhere((self.prior>.98)&(ndi.distance_transform_edt(self.expected>=128)>8))
        self.assertGreater(len(choices),0)
        y,x=choices[len(choices)//2]
        rgb=self.rgb.copy();rgb[y-2:y+3,x-2:x+3]=0
        color,alpha,info=paper_foliage.refine(rgb,self.prior,rgb,self.alpha,[255,255,255])
        self.assertTrue(info['paper_foliage_applied'])
        self.assertTrue(np.all(alpha[y-2:y+3,x-2:x+3]==255))
        self.assertTrue(np.all(color[y-2:y+3,x-2:x+3]==0))

    def test_real_separate_fern_shapes_are_not_joined(self):
        part=cv2.resize(self.expected,(384,288),interpolation=cv2.INTER_AREA)
        basis=np.zeros((320,820),np.uint8)
        basis[16:304,16:400]=part; basis[16:304,420:804]=part
        # Separate source subjects are independent even when a prior's
        # rectangular bounding box would contain both of them.
        before=ndi.label(basis>=128,structure=np.ones((3,3)))[1]
        result,_=paper_foliage._recover(basis.copy(),basis,np.full(basis.shape,.65),np.full(basis.shape,125))
        self.assertEqual(ndi.label(result>=128,structure=np.ones((3,3)))[1],before)
        self.assertFalse(result[:,400:420].any())


if __name__=='__main__':unittest.main()
