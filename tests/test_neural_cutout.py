import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

from cutout_prep import leaf_batch, leaf_geometry, neural_cutout, process_images as prep
from tools.shape_fixtures import specimen


class EdgeRefinementTests(unittest.TestCase):
    def test_bright_glints_cannot_perforate_confirmed_solid_material(self):
        rgb=np.full((160,160,3),240,np.uint8);rgb[20:140,20:140]=(65,61,52)
        rgb[60:72,65:79]=255
        prior=np.zeros((160,160),np.float32);prior[20:140,20:140]=1
        colors,alpha,_=neural_cutout.refine(rgb,prior)
        self.assertTrue(np.all(alpha[60:72,65:79]==255))
        np.testing.assert_array_equal(colors[60:72,65:79],rgb[60:72,65:79])

    def test_real_holes_and_narrow_connected_stem_remain(self):
        rgba=np.array(specimen('damaged'));rgb=rgba[:,:,:3].copy();rgb[rgba[:,:,3]==0]=235
        colors,alpha,_=neural_cutout.refine(rgb,rgba[:,:,3].astype(np.float32)/255)
        self.assertEqual(int(alpha[235,184]),0)
        self.assertEqual(int(alpha[313,307]),0)
        self.assertEqual(int(alpha[460,257]),255)
        self.assertEqual(ndi.label(alpha>=128,np.ones((3,3)))[1],1)
        np.testing.assert_array_equal(colors[alpha==255],rgb[alpha==255])

    def test_incomplete_prediction_recovers_fine_material_on_verified_dark_backing(self):
        rgba=np.array(specimen('damaged'));rgb=rgba[:,:,:3]
        prior=np.zeros((512,512),np.float32);prior[230:245,250:265]=1
        colors,alpha,details=neural_cutout.refine(rgb,prior)
        expected=rgba[:,:,3]>=128;actual=alpha>=128
        self.assertTrue(details['dark_backing_recovery'])
        self.assertGreater((actual&expected).sum()/expected.sum(),.99)
        self.assertEqual(int(alpha[235,184]),0)
        self.assertFalse(np.any(actual&~expected))
        np.testing.assert_array_equal(colors,rgb)

    def test_dark_recovery_does_not_run_on_bright_backing(self):
        rgba=np.array(specimen('damaged'));rgb=rgba[:,:,:3].copy();rgb[rgba[:,:,3]==0]=240
        prior=np.zeros((512,512),np.float32);prior[230:245,250:265]=1
        self.assertFalse(neural_cutout.refine(rgb,prior)[2]['dark_backing_recovery'])

    def test_malformed_priors_and_unverified_models_are_rejected(self):
        with self.assertRaises(ValueError):neural_cutout.refine(np.zeros((32,32,3),np.uint8),np.zeros((16,16)))
        with tempfile.TemporaryDirectory() as directory:
            model=Path(directory)/'model.onnx';model.write_bytes(b'not a verified model')
            with self.assertRaisesRegex(ValueError,'missing or incomplete'):neural_cutout.Predictor(model)

    def test_separate_subjects_do_not_trigger_a_guessed_stem_turn(self):
        alpha=np.zeros((512,512),np.uint8);alpha[30:280,50:190]=255;alpha[100:390,290:450]=255
        decision=leaf_geometry.stem_direction(alpha)
        self.assertFalse(decision['confident']);self.assertEqual(decision['clockwise_degrees'],0)


class ReaderContracts(unittest.TestCase):
    def test_auto_exposure_keeps_white_glints_in_normalized_gamut(self):
        rgba=np.zeros((128,128,4),np.uint8);rgba[12:116,12:116]=(28,26,24,255);rgba[40:50,40:50]=(255,255,255,255)
        for ev in (.0001,.65,1.1471,2.):
            values=prep.exposure_curve(rgba[:,:,:3].astype(np.float32)/255,ev)
            self.assertLessEqual(float(values.max()),1.)
        profile=Path(prep.__file__).with_name('sRGB.icc').read_bytes()
        encoded,_,_=prep.render(rgba,{**prep.DEFAULTS,'size':128,'padding':12},profile,matte_prepared=True)
        image=np.array(Image.open(io.BytesIO(encoded)))
        self.assertTrue(np.any(np.all(image[:,:,:3]==255,axis=2)&(image[:,:,3]==255)))
    def test_supplied_alpha_bypasses_neural_extraction(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'Leaf.png';rgba=np.array(specimen('damaged'));Image.fromarray(rgba).save(source)
            with patch.object(neural_cutout,'extract',side_effect=AssertionError('Authored alpha was replaced')):
                actual,*_=prep.read_input(source,{**prep.DEFAULTS,'cutout_method':'detailed'},root)
            np.testing.assert_array_equal(actual,rgba)

    def test_leaf_batch_keeps_separate_supplied_pieces_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'Inputs';source.mkdir()
            rgba=np.zeros((128,128,4),np.uint8);rgba[15:95,20:60]=(70,100,40,255);rgba[22:50,92:112]=(90,110,40,255)
            Image.fromarray(rgba).save(source/'Pieces.png')
            with contextlib.redirect_stdout(io.StringIO()):
                code=leaf_batch.prepare(source,root/'Results',512,{'orient_stems':False,'align_pairs':False})
            self.assertIn(code,(0,2))
            alpha=np.array(Image.open(root/'Results/Pieces_BaseColor.png'))[:,:,3]
            self.assertEqual(ndi.label(alpha>=128,np.ones((3,3)))[1],2)
            saved=json.loads((root/'Results/LeafPreparation.json').read_text())
            self.assertTrue(saved['options']['keep_separate_objects'])


class FineStructureContracts(unittest.TestCase):
    def test_solid_rock_glints_do_not_trigger_local_resegmentation(self):
        rgba=np.array(specimen('rock'));rgb=rgba[:,:,:3].copy();rgb[rgba[:,:,3]==0]=255
        rgb[220:240,240:260]=255
        backend=unittest.mock.Mock();backend.predict.side_effect=AssertionError('Solid material was resegmented')
        prior=rgba[:,:,3].astype(np.float32)/255
        actual,ceiling,evidence=neural_cutout.fine_structure(rgb,prior,backend)
        np.testing.assert_array_equal(actual,prior);self.assertIsNone(ceiling)
        self.assertEqual(evidence['fine_structure_tiles'],0)

    def test_pale_subject_does_not_trigger_chromatic_paper_cleanup(self):
        rgba=np.array(specimen('sprig'));rgb=np.full_like(rgba[:,:,:3],255);rgb[rgba[:,:,3]>0]=(240,242,238)
        prior=ndi.binary_dilation(rgba[:,:,3]>0,iterations=1).astype(np.float32)
        backend=unittest.mock.Mock();backend.predict.side_effect=AssertionError('Pale subject was resegmented')
        actual,ceiling,_=neural_cutout.fine_structure(rgb,prior,backend)
        np.testing.assert_array_equal(actual,prior);self.assertIsNone(ceiling)

    def test_local_crops_remove_false_paper_without_losing_colored_branches_or_pale_detail(self):
        rgba=np.array(specimen('sprig'));subject=rgba[:,:,3]>0;rgb=rgba[:,:,:3].copy();rgb[~subject]=255
        # A pale detail belongs to the photographed subject, not the backing.
        rgb[258:270,240:251]=(241,243,239);subject[258:270,240:251]=True
        y,x=np.indices(subject.shape)
        false_paper=ndi.binary_dilation(subject,iterations=1)&~subject&((x+y)%8==0)
        prior=(subject|false_paper).astype(np.float32)
        class LocalModel:
            def predict(self,image):
                keep=(image.min(axis=2)<250).astype(np.float32)
                return np.asarray(Image.fromarray(keep).resize((1024,1024),Image.Resampling.BILINEAR))
        actual,ceiling,evidence=neural_cutout.fine_structure(rgb,prior,LocalModel())
        self.assertEqual(evidence['fine_structure_tiles'],4)
        _,alpha,_=neural_cutout.refine(rgb,actual,coverage_ceiling=ceiling)
        self.assertGreater(((alpha>=128)&subject).sum()/subject.sum(),.995)
        self.assertLess(((alpha>=128)&~subject).sum(),((prior>=.5)&~subject).sum()*.1)
        self.assertTrue(np.all(alpha[260:268,242:249]==255))

    def test_edge_projection_cannot_grow_rejected_paper_back(self):
        rgb=np.full((128,128,3),255,np.uint8);rgb[20:108,30:96]=(65,105,38)
        rgb[45:80,60:63]=255;prior=np.zeros((128,128),np.float32);prior[20:108,30:96]=1
        ceiling=np.ones_like(prior);ceiling[45:80,60:63]=0
        _,alpha,_=neural_cutout.refine(rgb,prior,coverage_ceiling=ceiling)
        self.assertTrue(np.all(alpha[45:80,60:63]==0))
        self.assertTrue(np.all(alpha[25:40,40:80]==255))

    def test_malformed_fine_coverage_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'fine-structure coverage'):
            neural_cutout.refine(np.zeros((32,32,3),np.uint8),np.zeros((32,32)),coverage_ceiling=np.zeros((16,16)))
