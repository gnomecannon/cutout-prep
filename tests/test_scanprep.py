import json,sys,tempfile,threading,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from PIL import Image,ImageOps
from cutout_prep import scan_core as c
from unittest.mock import patch

class FakePredictor:
    def predict(self,image,points,box=None):
        a=np.zeros((image.height,image.width),bool);a[5:-5,7:-7]=True;return a,.97

class ScanTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.photos=self.root/'input';self.photos.mkdir();self.projects=[]
        a=np.zeros((48,64,3),np.uint8);a[:]=[120,80,40];Image.fromarray(a).save(self.photos/'rock.png')
    def tearDown(self):
        for p in self.projects:p.close()
        self.temp.cleanup()
    def project(self,paths=None,name='project',mode='object'):
        p=c.Project.create(paths or [self.photos/'rock.png'],self.root/name,mode);self.projects.append(p);return p
    def prepare(self,p):
        p.data['photos'][0]['box']=[.1,.1,.9,.9];c.process_one(p,0,FakePredictor());return p.data['photos'][0]
    def test_full_frame_export_and_original_bytes(self):
        source=self.photos/'rock.png';before=source.read_bytes();p=self.project();r=self.prepare(p);r['approved']=True;p.save();report=c.export(p)
        self.assertEqual(report[0]['status'],'exported');self.assertEqual(source.read_bytes(),before)
        dest=p.root/'Prepared Photos';self.assertEqual((dest/source.name).read_bytes(),before)
        mask=Image.open(dest/(source.name+'.mask.png'));self.assertEqual(mask.size,(64,48));self.assertEqual(set(np.unique(mask)),{0,255})
    def test_unreviewed_low_resolution_is_held(self):
        p=self.project();self.prepare(p);self.assertEqual(c.export(p)[0]['status'],'not_exported_review_required')
    def test_hand_edited_export_is_preserved(self):
        p=self.project();r=self.prepare(p);r['approved']=True;c.export(p);target=p.root/'Prepared Photos/rock.png.mask.png';target.write_bytes(b'manual edit');r['mask_sha256']=c.digest(p.mask_path(r))
        result=c.export(p);self.assertEqual(target.read_bytes(),b'manual edit');self.assertEqual(result[0]['status'],'error')
    def test_external_mask_edit_not_overwritten(self):
        p=self.project();r=self.prepare(p);path=p.mask_path(r);path.write_bytes(b'manual work')
        with self.assertRaisesRegex(ValueError,'edited outside'):c.process_one(p,0,FakePredictor())
        self.assertEqual(path.read_bytes(),b'manual work')
    def test_changed_source_refused(self):
        p=self.project();r=self.prepare(p);Image.new('RGB',(64,48),'green').save(self.photos/'rock.png')
        with self.assertRaisesRegex(ValueError,'changed'):c.process_one(p,0,FakePredictor())
        r['approved']=True;self.assertEqual(c.export(p)[0]['status'],'error')
    def test_concurrent_project_writer_refused(self):
        p=self.project()
        with self.assertRaisesRegex(ValueError,'another app'):c.Project.open(p.root/'Scan Project.json')
    def test_save_reopen_preserves_selection_and_approval(self):
        p=self.project();r=self.prepare(p);r['points']=[[.4,.5,1]];r['approved']=True;p.save();p.close();q=c.Project.open(p.root/'Scan Project.json');self.projects.append(q)
        self.assertEqual(q.data['photos'][0]['points'],[[.4,.5,1]]);self.assertTrue(q.data['photos'][0]['approved'])
    def test_original_exif_orientation_coordinates(self):
        raw=Image.fromarray(np.arange(48,dtype=np.uint8).reshape(6,8))
        forward={1:None,2:Image.Transpose.FLIP_LEFT_RIGHT,3:Image.Transpose.ROTATE_180,4:Image.Transpose.FLIP_TOP_BOTTOM,5:Image.Transpose.TRANSPOSE,6:Image.Transpose.ROTATE_270,7:Image.Transpose.TRANSVERSE,8:Image.Transpose.ROTATE_90}
        for orientation,transform in forward.items():
            with self.subTest(orientation=orientation):
                displayed=raw.transpose(transform) if transform is not None else raw.copy();restored=c.mask_to_raw(displayed,orientation);self.assertTrue(np.array_equal(restored,raw));self.assertEqual(restored.size,raw.size)
    def test_scene_mode_inverts_only_selected_distraction(self):
        p=self.project(mode='scene');r=self.prepare(p);mask=p.read_mask(r);self.assertTrue(mask[0,0]);self.assertFalse(mask[20,30])
    def test_same_name_photos_keep_distinct_masks(self):
        other=self.root/'other';other.mkdir();Image.new('RGB',(64,48),'blue').save(other/'rock.png');p=self.project([self.photos/'rock.png',other/'rock.png'])
        for i,r in enumerate(p.data['photos']):r['box']=[.1,.1,.9,.9];c.process_one(p,i,FakePredictor());r['approved']=True
        report=c.export(p);self.assertEqual(len(report),2);self.assertNotEqual(report[0]['file'],report[1]['file'])
    def test_cancel_before_group_does_not_process(self):
        p=self.project();event=threading.Event();event.set();c.process_group(p,FakePredictor(),event,lambda *a:None);self.assertIsNone(p.data['photos'][0]['mask'])
    def test_malformed_project_does_not_claim_lock(self):
        folder=self.root/'bad';folder.mkdir();(folder/'Scan Project.json').write_text(json.dumps({'schema':c.SCHEMA,'photos':[{'mask':'../elsewhere.png'}]}))
        with self.assertRaisesRegex(ValueError,'mask path'):c.Project.open(folder/'Scan Project.json')
        self.assertFalse((folder/'.scanprep-project.lock').exists())
    def test_approved_masks_are_preserved_on_batch(self):
        p=self.project();r=self.prepare(p);r['approved']=True;before=p.mask_path(r).read_bytes()
        class MustNotRun:
            def predict(self,*a,**k):raise AssertionError('approved mask was regenerated')
        c.process_group(p,MustNotRun(),threading.Event(),lambda *a:None);self.assertEqual(p.mask_path(r).read_bytes(),before)
    def test_lost_target_review_carries_forward_until_new_anchor(self):
        paths=[]
        for i in range(4):
            path=self.photos/f'view{i}.png';Image.new('RGB',(900,900),(20+i,30,40)).save(path);paths.append(path)
        p=self.project(paths);p.data['photos'][0]['box']=[.1,.1,.9,.9];p.data['photos'][3]['box']=[.1,.1,.9,.9]
        class BoxPredictor:
            def predict(self,image,points,box):
                mask=np.zeros((image.height,image.width),bool);mask[100:800,100:800]=True;return mask,.98
        with patch.object(c,'track',side_effect=[(None,0),(np.pad(np.ones((700,700),bool),100),50)]):
            c.process_group(p,BoxPredictor(),threading.Event(),lambda *a:None)
        self.assertEqual([r['status'] for r in p.data['photos']],['Ready','Review','Review','Ready'])
    def test_review_or_exclusion_removes_old_exports_from_import_folder(self):
        p=self.project();r=self.prepare(p);r['approved']=True;c.export(p);photo=p.root/'Prepared Photos/rock.png';before=photo.read_bytes()
        r['approved']=False;r['status']='Review';c.export(p)
        self.assertFalse(photo.exists());copies=list((p.root/'Previous Exports').rglob('rock.png'));self.assertEqual(copies[0].read_bytes(),before)
        r['approved']=True;c.export(p);r['excluded']=True;c.export(p);self.assertFalse(photo.exists())
    def test_modified_old_export_is_never_archived_silently(self):
        p=self.project();r=self.prepare(p);r['approved']=True;c.export(p);photo=p.root/'Prepared Photos/rock.png';photo.write_bytes(b'manual work');r['excluded']=True
        with self.assertRaisesRegex(ValueError,'older export was edited'):c.export(p)
        self.assertEqual(photo.read_bytes(),b'manual work')
    def test_temporal_batch_holds_uncertain_following_views_and_keeps_approval(self):
        paths=[]
        for i in range(4):
            path=self.photos/f'view{i}.png';Image.new('RGB',(900,900),(20+i,30,40)).save(path);paths.append(path)
        p=self.project(paths);p.data['photos'][0]['box']=[.1,.1,.9,.9];p.data['photos'][3]['box']=[.1,.1,.9,.9]
        class Temporal(FakePredictor):
            sequence=None
            def __init__(self):self.scores=iter([.7,.99])
            def seed_sequence(self,image,region):self.sequence=True
            def track_next(self,image):
                region,_=self.predict(image,[],None);return region,next(self.scores)
        c.process_group(p,Temporal(),threading.Event(),lambda *a:None)
        self.assertEqual([r['status'] for r in p.data['photos']],['Ready','Review','Review','Ready'])
        row=p.data['photos'][0];row['approved']=True;before=p.mask_path(row).read_bytes()
        c.process_group(p,Temporal(),threading.Event(),lambda *a:None)
        self.assertEqual(p.mask_path(row).read_bytes(),before);self.assertTrue(row['approved'])
    def test_foreign_photo_cannot_hide_in_current_import_folder(self):
        p=self.project();r=self.prepare(p);r['approved']=True;c.export(p);foreign=p.root/'Prepared Photos/another.png';foreign.write_bytes(b'foreign work')
        with self.assertRaisesRegex(ValueError,'Unrecognized files'):c.export(p)
        self.assertEqual(foreign.read_bytes(),b'foreign work')
    def test_source_filename_cannot_escape_project_on_export(self):
        p=self.project();p.data['photos'][0]['name']='../outside.png';p.save();p.close()
        with self.assertRaisesRegex(ValueError,'source filename'):c.Project.open(p.root/'Scan Project.json')

if __name__=='__main__':unittest.main()
