"""Photo-group masks. Source photographs are read-only and never reframed."""
from __future__ import annotations
import hashlib, io, json, os, shutil, tempfile, threading
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps

from . import __version__ as VERSION
SCHEMA='cutout-prep-scan-project-1'
EXTENSIONS={'.jpg','.jpeg','.png','.tif','.tiff','.heic','.heif','.webp','.bmp'}
cv2.setNumThreads(4)
try:
    import pi_heif
    pi_heif.register_heif_opener()
except ImportError:pass


def border_warning(project, region):
    """Image edges are expected for scene exclusions and user-selected surfaces."""
    if project.data['mode']=='scene' or project.data.get('allow_border',False):return []
    if region[0].any() or region[-1].any() or region[:,0].any() or region[:,-1].any():
        return ['Selection touches the photo border; check for a cropped subject or extra background.']
    return []


def tracking_uncertain(row):
    """Boundary/framing warnings alone must not poison subsequent tracking."""
    if row.get('approved'):return False
    if 'tracking_uncertain' in row:return bool(row['tracking_uncertain'])
    identity=('Low model confidence','View changed','Mask differs','Uncertain target',
              'Target size','An earlier view needs review','Tracking identity')
    return row.get('status')=='Error' or any(w.startswith(identity) for w in row.get('warnings',[]))

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def atomic(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.scanprep-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data)
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def save_json(path,data):atomic(path,json.dumps(data,indent=2,ensure_ascii=False).encode('utf-8'))

def image_info(path):
    with Image.open(path) as im:
        raw_size=im.size;orientation=int(im.getexif().get(274,1));oriented=ImageOps.exif_transpose(im)
        return {'raw_size':list(raw_size),'size':list(oriented.size),'orientation':orientation}

def load_photo(path,max_side=1280):
    with Image.open(path) as im:
        im=ImageOps.exif_transpose(im).convert('RGB')
        if max_side:im.thumbnail((max_side,max_side),Image.Resampling.LANCZOS)
        return im.copy()

def mask_to_raw(mask,orientation):
    inverse={2:Image.Transpose.FLIP_LEFT_RIGHT,3:Image.Transpose.ROTATE_180,4:Image.Transpose.FLIP_TOP_BOTTOM,5:Image.Transpose.TRANSPOSE,6:Image.Transpose.ROTATE_90,7:Image.Transpose.TRANSVERSE,8:Image.Transpose.ROTATE_270}
    return mask.transpose(inverse[orientation]) if orientation in inverse else mask.copy()

def png_bytes(im):
    b=io.BytesIO();im.save(b,format='PNG');return b.getvalue()

def inside_point(mask):
    distance=cv2.distanceTransform(mask.astype(np.uint8),cv2.DIST_L2,5)
    y,x=np.unravel_index(np.argmax(distance),distance.shape)
    return [float(x/mask.shape[1]),float(y/mask.shape[0]),1]

def mask_box(mask,margin=.10):
    y,x=np.nonzero(mask)
    if not len(x):raise ValueError('Empty mask. Add a keep point on the subject.')
    h,w=mask.shape;left,right=x.min()/w,(x.max()+1)/w;top,bottom=y.min()/h,(y.max()+1)/h
    dx=(right-left)*margin;dy=(bottom-top)*margin
    return [max(0,float(left-dx)),max(0,float(top-dy)),min(1,float(right+dx)),min(1,float(bottom+dy))]

class Project:
    def __init__(self,root,data):self.root=Path(root).resolve();self.data=data;self.lock=None
    @classmethod
    def create(cls,paths,root,mode='object'):
        root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
        if (root/'Scan Project.json').exists():raise ValueError('A scan project already exists here. Open it or choose another output folder.')
        rows=[];seen=set()
        for path in sorted({str(Path(p).resolve()) for p in paths},key=str.casefold):
            f=Path(path)
            if f.suffix.lower() not in EXTENSIONS or '.mask.' in f.name.lower():continue
            sha=digest(f)
            if sha in seen:continue
            seen.add(sha);info=image_info(f)
            rows.append({'path':str(f),'name':f.name,'sha256':sha,**info,'points':[],'box':None,'excluded':False,'approved':False,'mask':None,'mask_sha256':None,'status':'Not processed','warnings':[],'score':None})
        if not rows:raise ValueError('No supported photographs were selected.')
        obj=cls(root,{'schema':SCHEMA,'version':VERSION,'mode':mode,'margin':0,'allow_border':False,'photos':rows});obj.acquire();obj.save();return obj
    @classmethod
    def open(cls,filename):
        f=Path(filename).resolve();data=json.loads(f.read_text(encoding='utf-8'))
        if data.get('schema')!=SCHEMA or not isinstance(data.get('photos'),list):raise ValueError('This is not a Scan Prep project.')
        for r in data['photos']:
            if r.get('mask') and (Path(r['mask']).name!=r['mask'] or not r['mask'].endswith('.png')):raise ValueError('Invalid project mask path.')
            name=r.get('name')
            if not isinstance(name,str) or not name or '/' in name or '\\' in name or Path(name).name!=name:raise ValueError('Invalid source filename in project.')
        obj=cls(f.parent,data);obj.acquire();return obj
    def acquire(self):
        lock=self.root/'.scanprep-project.lock'
        try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
        except FileExistsError:raise ValueError('This project is open in another app, or has an interrupted-run lock. Close the other app before recovering its lock.')
        os.write(fd,str(os.getpid()).encode());os.close(fd);self.lock=lock
    def close(self):
        if self.lock and self.lock.exists():self.lock.unlink()
        self.lock=None
    def save(self):save_json(self.root/'Scan Project.json',self.data)
    def mask_path(self,row):return self.root/'Masks'/row['mask'] if row.get('mask') else None
    def read_mask(self,row,size=None):
        path=self.mask_path(row)
        if not path or not path.exists():return None
        with Image.open(path) as im:
            mask=im.convert('L')
            if size:mask=mask.resize(size,Image.Resampling.NEAREST)
            return np.asarray(mask)>127
    def store_mask(self,row,mask,score,warnings,uncertain=False):
        if not (self.root/'Masks').resolve().is_relative_to(self.root):raise ValueError('Mask folder points outside this project.')
        previous=self.mask_path(row)
        if previous and previous.exists() and row.get('mask_sha256') and digest(previous)!=row['mask_sha256']:
            raise ValueError('This mask was edited outside the app. It is preserved; duplicate the project before regenerating it.')
        name=row['sha256'][:16]+'.png';im=Image.fromarray(mask.astype(np.uint8)*255).resize(tuple(row['size']),Image.Resampling.NEAREST)
        path=self.root/'Masks'/name
        if path.exists() and previous is None:raise ValueError('An unrecognized mask already exists here; it was preserved.')
        atomic(path,png_bytes(im));row.update(mask=name,mask_sha256=digest(path),score=float(score),warnings=list(warnings),tracking_uncertain=bool(uncertain),approved=False,status='Review' if warnings else 'Ready');self.save()

class Predictor:
    """A local safetensors-only CPU backend, loaded lazily off the UI thread."""
    def __init__(self,model_dir):
        os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1';os.environ['CUDA_VISIBLE_DEVICES']=''
        os.environ['HF_HUB_DISABLE_PROGRESS_BARS']='1';os.environ['HF_HUB_DISABLE_TELEMETRY']='1'
        import torch
        from transformers import Sam2Model,Sam2Processor
        from transformers.utils.logging import disable_progress_bar
        disable_progress_bar()
        self.torch=torch;torch.set_num_threads(4)
        self.processor=Sam2Processor.from_pretrained(str(model_dir),local_files_only=True)
        self.model=Sam2Model.from_pretrained(str(model_dir),local_files_only=True,use_safetensors=True).eval().to('cpu')
        self.model_dir=Path(model_dir);self.video_model=None;self.sequence=None
    def predict(self,image,points,box=None):
        w,h=image.size;kwargs={'images':image,'return_tensors':'pt'}
        if points:
            kwargs['input_points']=[[[[p[0]*w,p[1]*h] for p in points]]]
            kwargs['input_labels']=[[[int(p[2]) for p in points]]]
        if box:kwargs['input_boxes']=[[[box[0]*w,box[1]*h,box[2]*w,box[3]*h]]]
        inputs=self.processor(**kwargs)
        with self.torch.inference_mode():output=self.model(**inputs,multimask_output=True)
        masks=self.processor.post_process_masks(output.pred_masks.cpu(),inputs['original_sizes'])[0][0].numpy()>0
        scores=output.iou_scores[0,0].cpu().numpy();choices=[]
        for mask,score in zip(masks,scores):
            fraction=float(mask.mean())
            if fraction<.0001 or fraction>.995:continue
            violations=sum(bool(mask[min(h-1,int(y*h)),min(w-1,int(x*w))])!=(label==1) for x,y,label in points)
            box_penalty=0
            if box:
                x0,y0,x1,y1=[int(v) for v in [box[0]*w,box[1]*h,box[2]*w,box[3]*h]]
                coverage=mask[max(0,y0):min(h,y1),max(0,x0):min(w,x1)].sum()/max(1,mask.sum())
                box_penalty=max(0,.75-float(coverage))*3
            choices.append((violations+box_penalty,-float(score),mask,float(score)))
        if not choices:raise ValueError('No usable mask. Draw a tighter box or add keep/remove points.')
        choices.sort(key=lambda c:(c[0],c[1]));_,_,mask,score=choices[0]
        return mask,score
    def seed_sequence(self,image,region):
        if self.video_model is None:
            from transformers import Sam2VideoModel,Sam2VideoProcessor
            self.video_processor=Sam2VideoProcessor.from_pretrained(str(self.model_dir),local_files_only=True)
            self.video_model=Sam2VideoModel.from_pretrained(str(self.model_dir),local_files_only=True,use_safetensors=True).eval().to('cpu')
        self.sequence=self.video_processor.init_video_session(inference_device='cpu',max_vision_features_cache_size=1)
        self.sequence.video_height=image.height;self.sequence.video_width=image.width
        self.video_processor.add_inputs_to_inference_session(inference_session=self.sequence,frame_idx=0,obj_ids=1,input_masks=region)
        self.track_next(image)
    def track_next(self,image):
        if self.sequence is None:raise ValueError('Select the subject on a starting view before processing this sequence.')
        if (self.sequence.video_width,self.sequence.video_height)!=image.size:
            self.sequence=None;raise ValueError('Photo dimensions changed. Select the target on this view to begin a new sequence.')
        inputs=self.video_processor(images=image,return_tensors='pt')
        with self.torch.inference_mode():output=self.video_model(inference_session=self.sequence,frame=inputs.pixel_values[0])
        logits=self.video_processor.post_process_masks([output.pred_masks],original_sizes=inputs.original_sizes,binarize=False)[0][0,0].cpu().numpy()
        region=logits>0
        presence=float(output.object_score_logits.sigmoid().min())
        stability=float((logits>1).sum()/max(1,(logits>-1).sum()))
        return region,min(presence,stability)

def track(previous,current,mask):
    """Track foreground features, never stationary turntable/background features."""
    a=cv2.cvtColor(np.asarray(previous),cv2.COLOR_RGB2GRAY);b=cv2.cvtColor(np.asarray(current),cv2.COLOR_RGB2GRAY)
    if a.shape!=b.shape:return None,0
    sift=cv2.SIFT_create(nfeatures=1800,contrastThreshold=.012)
    eroded=cv2.erode(mask.astype(np.uint8)*255,np.ones((5,5),np.uint8))
    ka,da=sift.detectAndCompute(a,eroded);kb,db=sift.detectAndCompute(b,None)
    if da is None or db is None or len(ka)<8 or len(kb)<8:return None,0
    pairs=cv2.BFMatcher().knnMatch(da,db,k=2);good=[m for pair in pairs if len(pair)==2 for m,n in [pair] if m.distance<.72*n.distance]
    if len(good)<8:return None,0
    pa=np.float32([ka[m.queryIdx].pt for m in good]);pb=np.float32([kb[m.trainIdx].pt for m in good])
    H,inside=cv2.findHomography(pa,pb,cv2.RANSAC,3.0)
    if H is None or inside is None or int(inside.sum())<8:return None,0
    warped=cv2.warpPerspective(mask.astype(np.uint8),H,(b.shape[1],b.shape[0]),flags=cv2.INTER_NEAREST)>0
    ratio=float(warped.sum()/max(1,mask.sum()))
    if not .35<ratio<2.8:return None,0
    return warped,int(inside.sum())

def process_one(project,index,predictor,previous=None):
    row=project.data['photos'][index]
    if digest(row['path'])!=row['sha256']:raise ValueError('Source photograph changed. Import it into a new project; the old mask is preserved.')
    image=load_photo(row['path']);points=[list(p) for p in row.get('points',[])];box=row.get('box');warnings=[];tracked=None
    if not points and not box:
        if previous:
            previous_image,previous_region=previous;tracked,n=track(previous_image,image,previous_region)
            if tracked is not None:points=[inside_point(tracked)];box=mask_box(tracked,.12)
            else:
                warnings.append('View changed or tracking was lost: add a target box/point and preview this photo.')
                if previous_region.shape==(image.height,image.width):points=[inside_point(previous_region)];box=mask_box(previous_region,.20)
        if not points and not box:raise ValueError('Choose the subject on a starting photo before processing the group.')
    if not any(p[2]==1 for p in points) and not box:raise ValueError('Add a keep point on the target region or draw a box.')
    region,score=predictor.predict(image,points,box)
    if score<.85:warnings.append('Low model confidence: inspect the silhouette.')
    if min(row['size'])<800:warnings.append('Low-resolution image; this may be an exported thumbnail.')
    warnings.extend(border_warning(project,region))
    if tracked is not None:
        union=np.logical_or(region,tracked).sum();iou=float(np.logical_and(region,tracked).sum()/max(1,union))
        if iou<.35:warnings.append('Mask differs substantially from the tracked subject; inspect target identity.')
    margin=int(project.data.get('margin',0))
    if margin:
        kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(abs(margin)*2+1,abs(margin)*2+1))
        region=(cv2.dilate if margin>0 else cv2.erode)(region.astype(np.uint8),kernel)>0
    keep=~region if project.data['mode']=='scene' else region
    if not keep.any():raise ValueError('The mask would remove the entire photograph. It was not saved.')
    identity=any(w.startswith(('Low model confidence','View changed','Mask differs')) for w in warnings)
    project.store_mask(row,keep,score,warnings,uncertain=identity)
    return image,region

def process_temporal_group(project,predictor,cancel,progress,start=0):
    predictor.sequence=None;previous=None;trusted=True
    if start>0:
        row=project.data['photos'][start-1];image=load_photo(row['path']);mask=project.read_mask(row,image.size)
        if mask is not None and not tracking_uncertain(row):
            if digest(row['path'])!=row['sha256'] or digest(project.mask_path(row))!=row['mask_sha256']:
                raise ValueError('The preceding photo or mask changed. Reopen and review that view before continuing.')
            previous=~mask if project.data['mode']=='scene' else mask;predictor.seed_sequence(image,previous)
    for index in range(start,len(project.data['photos'])):
        if cancel.is_set():break
        row=project.data['photos'][index]
        if row.get('excluded'):progress(index,'Excluded');continue
        try:
            if digest(row['path'])!=row['sha256']:raise ValueError('Source photograph changed. Import it into a new project.')
            image=load_photo(row['path']);anchored=bool(row.get('points') or row.get('box'))
            if row.get('approved'):
                mask=project.read_mask(row,image.size)
                if mask is None or digest(project.mask_path(row))!=row['mask_sha256']:raise ValueError('Approved mask changed or is missing. Inspect it before processing.')
                region=~mask if project.data['mode']=='scene' else mask;trusted=True;predictor.seed_sequence(image,region)
            elif anchored:
                _,region=process_one(project,index,predictor);predictor.seed_sequence(image,region);trusted=not tracking_uncertain(row)
            else:
                region,score=predictor.track_next(image);warnings=[];fraction=float(region.mean())
                if fraction<.0001 or fraction>.995:raise ValueError('The tracker lost the selected target. Add a box or point on this view.')
                if score<.85:warnings.append('Uncertain target boundary or visibility: inspect the silhouette.')
                if min(row['size'])<800:warnings.append('Low-resolution image; this may be an exported thumbnail.')
                warnings.extend(border_warning(project,region))
                if previous is not None:
                    ratio=float(region.sum()/max(1,previous.sum()))
                    if not .35<ratio<2.8:warnings.append('Target size changed abruptly. Check its identity or start a new anchor.')
                identity=not trusted or any(w.startswith(('Uncertain target','Target size')) for w in warnings)
                if not trusted:warnings.append('Tracking identity is uncertain after an earlier view: add a new selection or approve this silhouette.')
                margin=int(project.data.get('margin',0));keep_region=region
                if margin:
                    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(abs(margin)*2+1,abs(margin)*2+1))
                    keep_region=(cv2.dilate if margin>0 else cv2.erode)(region.astype(np.uint8),kernel)>0
                keep=~keep_region if project.data['mode']=='scene' else keep_region
                if not keep.any():raise ValueError('The mask would remove the entire photograph. It was not saved.')
                project.store_mask(row,keep,score,warnings,uncertain=identity);trusted=not identity
            previous=region;progress(index,row['status'])
        except Exception as exc:
            row['status']='Error';row['approved']=False;row['tracking_uncertain']=True;row['warnings']=[str(exc)];project.save();progress(index,str(exc));predictor.sequence=None;previous=None;trusted=False

def process_group(project,predictor,cancel,progress,start=0):
    if hasattr(predictor,'seed_sequence'):return process_temporal_group(project,predictor,cancel,progress,start)
    previous=None;trusted=True
    if start>0:
        r=project.data['photos'][start-1];im=load_photo(r['path']);m=project.read_mask(r,im.size)
        if m is not None:
            previous=(im,~m if project.data['mode']=='scene' else m);trusted=not tracking_uncertain(r)
    for index in range(start,len(project.data['photos'])):
        if cancel.is_set():break
        row=project.data['photos'][index]
        if row.get('excluded'):progress(index,'Excluded');continue
        try:
            if row.get('approved') and project.read_mask(row) is not None:
                im=load_photo(row['path']);m=project.read_mask(row,im.size);previous=(im,~m if project.data['mode']=='scene' else m);trusted=True
            else:
                anchored=bool(row.get('points') or row.get('box'))
                previous=process_one(project,index,predictor,previous)
                if not anchored and not trusted:
                    row['warnings'].append('An earlier view needs review: reselect the target or approve this silhouette before export.')
                    row['status']='Review';row['tracking_uncertain']=True;project.save()
                trusted=not tracking_uncertain(row)
            progress(index,row['status'])
        except Exception as exc:
            row['status']='Error';row['tracking_uncertain']=True;row['warnings']=[str(exc)];project.save();progress(index,str(exc));previous=None;trusted=False

def export(project,include_review=False,cancel=None):
    destination=project.root/'Prepared Photos'
    if not destination.resolve().is_relative_to(project.root):raise ValueError('Export folder points outside this project.')
    destination.mkdir(exist_ok=True)
    manifest_path=project.root/'Export Report.json';prior={}
    if manifest_path.exists():
        old=json.loads(manifest_path.read_text(encoding='utf-8'))
        if old.get('schema')!='cutout-prep-scan-export-1':raise ValueError('Unrecognized export report; existing files were left unchanged.')
        prior=old.get('managed',{})
    managed=dict(prior);report=[];names={}
    for r in project.data['photos']:names.setdefault(r['name'].casefold(),[]).append(r)
    def export_name(row):
        source=Path(row['path']);name=row['name']
        return source.stem+'_'+row['sha256'][:8]+source.suffix if len(names[name.casefold()])>1 else name
    wanted=set()
    for row in project.data['photos']:
        if row.get('excluded') or not row.get('mask'):continue
        if row['status']!='Ready' and not row.get('approved') and not include_review:continue
        name=export_name(row);wanted.update([name,name+'.mask.png'])
        if Path(row['path']).with_suffix('.xmp').exists():wanted.add(Path(name).stem+'.xmp')
    unexpected=[p.name for p in destination.iterdir() if p.is_file() and p.name not in wanted and p.name not in prior]
    if unexpected:raise ValueError('Unrecognized files are in Prepared Photos. Choose a separate empty output project; existing files were preserved.')
    # Keep the import folder current without destroying a previous export.
    stale=[name for name in prior if name not in wanted and (destination/name).exists()]
    for name in stale:
        path=destination/name
        if Path(name).name!=name or digest(path)!=prior[name]:
            raise ValueError('An older export was edited and is preserved: '+name+'. Choose a new project/output folder before importing again.')
    if stale:
        archive=project.root/'Previous Exports'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        if not archive.resolve().is_relative_to(project.root):raise ValueError('Archive folder points outside this project.')
        archive.mkdir(parents=True)
        for name in stale:
            (destination/name).replace(archive/name);managed.pop(name,None)
        save_json(manifest_path,{'schema':'cutout-prep-scan-export-1','version':VERSION,'managed':managed,'photos':[]})
    def write_owned(target,data):
        if target.exists():
            actual=digest(target);wanted=hashlib.sha256(data).hexdigest()
            if actual==wanted:managed[target.name]=wanted;return
            if prior.get(target.name)!=actual:raise ValueError('Existing file was edited or is not owned by this project: '+target.name)
        atomic(target,data);managed[target.name]=digest(target)
    for row in project.data['photos']:
        if cancel and cancel.is_set():break
        if row.get('excluded') or not row.get('mask'):continue
        if row['status']!='Ready' and not row.get('approved') and not include_review:
            report.append({'file':row['name'],'status':'not_exported_review_required'});continue
        try:
            source=Path(row['path'])
            if digest(source)!=row['sha256']:raise ValueError('Source changed; export refused.')
            maskpath=project.mask_path(row)
            if row.get('mask_sha256')!=digest(maskpath):raise ValueError('Mask edited outside app; inspect and approve it in the app first.')
            name=export_name(row)
            raw=mask_to_raw(Image.open(maskpath).convert('L'),row.get('orientation',1))
            if list(raw.size)!=row['raw_size']:raise ValueError('Mask dimensions differ from original pixel dimensions.')
            write_owned(destination/name,source.read_bytes());write_owned(destination/(name+'.mask.png'),png_bytes(raw))
            xmp=source.with_suffix('.xmp')
            if xmp.exists():write_owned(destination/(Path(name).stem+'.xmp'),xmp.read_bytes())
            report.append({'file':name,'status':'exported','source_sha256':row['sha256'],'mask':name+'.mask.png','raw_size':row['raw_size'],'reviewed':row.get('approved',False),'warnings':row.get('warnings',[])})
        except Exception as exc:report.append({'file':row['name'],'status':'error','error':str(exc)})
        save_json(manifest_path,{'schema':'cutout-prep-scan-export-1','version':VERSION,'managed':managed,'photos':report})
    save_json(manifest_path,{'schema':'cutout-prep-scan-export-1','version':VERSION,'managed':managed,'photos':report})
    return report
