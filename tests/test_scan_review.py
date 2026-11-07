"""Review framing separately from uncertain target identity across a batch."""
import tempfile,threading,unittest
from pathlib import Path
import numpy as np
from PIL import Image
from cutout_prep import scan_core as core


class Temporal:
    def __init__(self,scores=None,border=True):self.scores=iter(scores or [.99]*5);self.border=border;self.sequence=None
    def predict(self,image,points,box=None):
        mask=np.zeros((image.height,image.width),bool);mask[100:700,0 if self.border else 100:700]=True
        return mask,.99
    def seed_sequence(self,image,mask):self.sequence=True
    def track_next(self,image):
        assert self.sequence
        mask=np.zeros((image.height,image.width),bool);mask[100:700,100:700]=True
        return mask,next(self.scores)


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.projects=[]
        self.paths=[]
        for i in range(4):
            path=self.root/f'{i}.png';Image.new('RGB',(1000,900),(i*30,80,100)).save(path);self.paths.append(path)
    def tearDown(self):
        for p in self.projects:p.close()
        self.temp.cleanup()
    def project(self,mode='object'):
        p=core.Project.create(self.paths,self.root/'project',mode);self.projects.append(p)
        p.data['photos'][0]['box']=[0,.1,.8,.9];return p
    def process(self,p,predictor,start=0):core.process_group(p,predictor,threading.Event(),lambda *a:None,start)
    def test_border_review_does_not_poison_following_views(self):
        p=self.project();self.process(p,Temporal())
        self.assertEqual([r['status'] for r in p.data['photos']],['Review','Ready','Ready','Ready'])
        self.assertFalse(p.data['photos'][0]['tracking_uncertain'])
        self.assertEqual(sum(r['status']=='exported' for r in core.export(p)),3)
    def test_surface_setting_is_saved_and_suppresses_only_border_warning(self):
        p=self.project();p.data['allow_border']=True;p.save();p.close()
        p=core.Project.open(p.root/'Scan Project.json');self.projects.append(p)
        self.assertTrue(p.data['allow_border']);self.process(p,Temporal(scores=[.3,.99,.99]))
        self.assertEqual(p.data['photos'][0]['status'],'Ready')
        self.assertEqual([r['status'] for r in p.data['photos'][1:]],['Review']*3)
        self.assertTrue(p.data['photos'][2]['tracking_uncertain'])
    def test_scene_removal_at_edge_is_expected(self):
        p=self.project('scene');self.process(p,Temporal())
        self.assertEqual([r['status'] for r in p.data['photos']],['Ready']*4)
    def test_new_anchor_recovers_identity_after_uncertain_tracking(self):
        p=self.project();p.data['allow_border']=True;p.data['photos'][3]['box']=[.1,.1,.8,.9]
        self.process(p,Temporal(scores=[.3,.99]))
        self.assertEqual([r['status'] for r in p.data['photos']],['Ready','Review','Review','Ready'])
    def test_resume_from_boundary_only_review_seeds_tracker(self):
        p=self.project();core.process_one(p,0,Temporal())
        self.assertEqual(p.data['photos'][0]['status'],'Review')
        self.process(p,Temporal(),start=1)
        self.assertEqual([r['status'] for r in p.data['photos'][1:]],['Ready']*3)
    def test_old_project_warning_is_conservative_for_identity(self):
        self.assertTrue(core.tracking_uncertain({'status':'Review','warnings':['An earlier view needs review: reselect.']}))
        self.assertFalse(core.tracking_uncertain({'status':'Review','warnings':['Selection touches the photo border; check.']}))


if __name__=='__main__':unittest.main()
