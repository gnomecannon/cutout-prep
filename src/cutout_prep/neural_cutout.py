"""Local, pinned object segmentation with bounded edge refinement.

No remote code, inference service or automatic model download is used. Supplied
alpha/masks bypass this module in the image reader. RGB is changed only where a
fractional boundary is sufficiently supported by nearby foreground/background.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import sys

import cv2
import numpy as np
from PIL import Image
from scipy import ndimage as ndi

MODEL_SHA256 = '5600024376f572a557870a5eb0afb1e5961636bef4e1e22132025467d0f03333'
MODEL_BYTES = 224005088
_sessions = {}


def model_directory():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent/'resources'))
    return Path(os.environ.get('CUTOUT_PREP_2D_MODEL_DIR', str(root/'models/birefnet-lite')))


def available():
    return (model_directory()/'model.onnx').is_file()


class Predictor:
    def __init__(self, path):
        path = Path(path)
        if not path.is_file() or path.stat().st_size != MODEL_BYTES:
            raise ValueError('The detailed cutout model is missing or incomplete. Extract the complete app download or run the documented source setup.')
        with path.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest() if hasattr(hashlib,'file_digest') else hashlib.sha256(handle.read()).hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError('The detailed cutout model does not match the verified release. Restore it from the app download.')
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise ValueError('Detailed cutouts need the local ONNX runtime. Use the complete portable app or install the cutout dependency extra.') from exc
        options = ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
        options.log_severity_level=3
        self.session = ort.InferenceSession(str(path),options,providers=['CPUExecutionProvider'])
        self.input = self.session.get_inputs()[0]
        if self.input.shape != [1,3,1024,1024] or len(self.session.get_outputs()) != 1:
            raise ValueError('Unexpected detailed cutout model interface')
        self.runtime_version = ort.__version__
        self.cache = OrderedDict()

    def predict(self, rgb):
        image = np.asarray(Image.fromarray(rgb).resize((1024,1024),Image.Resampling.BILINEAR))
        key = hashlib.sha256(image.tobytes()).hexdigest()
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key].copy()
        mean=np.array([.485,.456,.406],np.float32);std=np.array([.229,.224,.225],np.float32)
        values=((image.astype(np.float32)/255-mean)/std).transpose(2,0,1)[None]
        logits=self.session.run(None,{self.input.name:values})[0]
        if logits.shape != (1,1,1024,1024) or not np.isfinite(logits).all():
            raise ValueError('Detailed cutout model returned an invalid mask')
        alpha=(1/(1+np.exp(-np.clip(logits[0,0],-40,40)))).astype(np.float32)
        self.cache[key]=alpha.copy()
        while len(self.cache)>32:self.cache.popitem(last=False)
        return alpha


def predictor():
    path=model_directory()/'model.onnx'
    if not path.is_file():return Predictor(path)
    stat=path.stat();key=(str(path.resolve()),stat.st_size,stat.st_mtime_ns)
    if key not in _sessions:
        _sessions.clear();_sessions[key]=Predictor(path)
    return _sessions[key]


def _dark_backing(rgb, prior):
    """Recover cropped fine material only with measured, flat dark backing.

    This is not used on bright paper or clutter. A strongly incomplete object
    prediction can otherwise discard most of a skeletonized leaf on black.
    No holes are filled; separation follows the measured source contrast.
    """
    h,w=prior.shape;edge=max(2,round(min(h,w)*.025))
    border=np.zeros((h,w),bool);border[:edge]=border[-edge:]=True;border[:,:edge]=border[:,-edge:]=True
    values=rgb.astype(np.float32)
    peak=values.max(axis=2)
    # Estimate noise from the actual darkest border cluster. The broader
    # dark tail can contain antialiased foreground, not backing noise.
    cluster_limit=min(28,max(6,float(np.percentile(peak[border],20))+2))
    dark=border&(peak<=cluster_limit)
    if dark.sum()<border.sum()*.20:return None
    background=np.median(values[dark],axis=0)
    residual=np.linalg.norm(values-background,axis=2)
    noise=float(np.percentile(residual[dark],95))
    if noise>12:return None
    difference=np.max(values-background,axis=2)
    candidate=difference>max(24,noise*4)
    fraction=float(candidate.mean());predicted=prior>=.5
    if not .035<fraction<.9 or float((candidate&predicted).sum()/max(1,candidate.sum()))>=.3:return None
    alpha=np.clip((difference-max(6,noise*2))/max(12,24-noise),0,1)
    alpha[np.max(values,axis=2)<max(8,float(background.max())+noise*2)]=0
    return alpha.astype(np.float32)


def fine_structure(rgb, prior, backend):
    """Recheck fine chromatic subjects on measured bright neutral backing.

    Four overlapping crops give the model more pixels per leaflet. Cropped
    predictions may only reduce the global mask, and confident colored source
    material is protected. This is not a blanket white-pixel removal rule.
    """
    info={'fine_structure_tiles':0}
    h,w=prior.shape;foreground=prior>=.5
    if min(h,w)<256 or not foreground.any():return prior,None,info
    depth=ndi.distance_transform_edt(foreground)
    chroma=np.ptp(rgb,axis=2)
    if (foreground&(depth<=4)).sum()<foreground.sum()*.20 or np.median(chroma[foreground])<32:
        return prior,None,info
    border=np.zeros((h,w),bool);edge=max(2,round(min(h,w)*.025))
    border[:edge]=border[-edge:]=True;border[:,:edge]=border[:,-edge:]=True
    paper=(rgb.min(axis=2)>=210)&(chroma<=16)
    seeds=paper&(prior<=.01)
    if (seeds&border).sum()<border.sum()*.40 or seeds.sum()<h*w*.02:return prior,None,info
    # Shadows can cover much of otherwise uniform paper. Estimate its bright
    # mode separately instead of treating shadow variation as backing noise.
    seeds &= rgb.min(axis=2)>=max(210,float(np.percentile(rgb.min(axis=2)[seeds],70))-8)
    background=np.median(rgb[seeds],axis=0)
    if np.percentile(np.max(np.abs(rgb[seeds].astype(np.float32)-background),axis=1),90)>12:
        return prior,None,info
    if (paper&foreground).sum()<max(32,foreground.sum()*.002):return prior,None,info
    width=round(w*.625);height=round(h*.625)
    total=np.zeros_like(prior);weights=np.zeros_like(prior)
    blend=np.outer(np.hanning(height),np.hanning(width)).astype(np.float32)+.001
    for y in (0,h-height):
        for x in (0,w-width):
            prediction=backend.predict(rgb[y:y+height,x:x+width])
            prediction=cv2.resize(prediction,(width,height),interpolation=cv2.INTER_LINEAR)
            total[y:y+height,x:x+width]+=prediction*blend
            weights[y:y+height,x:x+width]+=blend
    local=total/weights
    protected=(chroma>=40)&(prior>=.9)
    combined=np.where(protected,prior,np.minimum(prior,local))
    info.update(fine_structure_tiles=4,paper_background_rgb=background.tolist())
    if (combined>=.5).sum()<foreground.sum()*.8:
        info['fine_structure_rejected']='Local crops disagreed on too much subject coverage'
        return prior,None,info
    # The edge projection must not grow low-confidence paper back into the
    # mask. Solid pale objects do not pass the chromatic/thin-structure gate;
    # high-confidence pale details confirmed by the crops also remain intact.
    paper_like=(chroma<40)&(rgb.min(axis=2)>=float(background.min())-85)
    ceiling=np.where(paper_like&(combined<.98),combined,1).astype(np.float32)
    info['fine_structure_reduced_pixels']=int((combined<prior-1e-4).sum())
    return combined,ceiling,info


def refine(rgb, prior, *, recover_dark=True, coverage_ceiling=None):
    """Refine a working-resolution prior while preserving its interior topology."""
    rgb=np.asarray(rgb,dtype=np.uint8);prior=np.clip(np.asarray(prior,np.float32),0,1)
    if prior.shape!=rgb.shape[:2] or not np.isfinite(prior).all():raise ValueError('Invalid segmentation prior')
    if coverage_ceiling is not None:
        coverage_ceiling=np.asarray(coverage_ceiling,np.float32)
        if coverage_ceiling.shape!=prior.shape or not np.isfinite(coverage_ceiling).all():raise ValueError('Invalid fine-structure coverage')
        coverage_ceiling=np.clip(coverage_ceiling,0,1)
    recovered=_dark_backing(rgb,prior) if recover_dark else None
    if recovered is not None:
        return rgb.copy(),np.round(recovered*255).astype(np.uint8),{'dark_backing_recovery':True,'edge_rgb_pixels':0}
    foreground=prior>=.5
    if not foreground.any() or foreground.all():raise ValueError('Detailed cutout could not separate the subject; review this capture')
    depth=ndi.distance_transform_edt(foreground)
    outside=ndi.distance_transform_edt(~foreground)
    core=(prior>=.98)|(foreground&(depth>2))
    if coverage_ceiling is not None:core &= coverage_ceiling>=.99
    background=(prior<=.02)&~foreground&(outside>1)
    alpha=prior.copy();alpha[core]=1;alpha[(prior<=.01)&~foreground]=0
    if coverage_ceiling is not None:alpha=np.minimum(alpha,coverage_ceiling)
    edge=(alpha>0)&~core&(outside<=3)
    colors=rgb.astype(np.float32)/255
    linear=np.where(colors<=.04045,colors/12.92,((colors+.055)/1.055)**2.4)
    changed=np.zeros(alpha.shape,bool)
    if core.any() and background.any() and edge.any():
        fd,fi=ndi.distance_transform_edt(~core,return_indices=True)
        _,bi=ndi.distance_transform_edt(~background,return_indices=True)
        f=linear[fi[0],fi[1]];b=linear[bi[0],bi[1]];delta=f-b
        norm=np.sum(delta*delta,axis=2)
        projection=np.clip(np.sum((linear-b)*delta,axis=2)/np.maximum(norm,1e-6),0,1)
        residual=np.linalg.norm(linear-(projection[:,:,None]*f+(1-projection[:,:,None])*b),axis=2)
        supported=edge&(fd<=12)&(norm>.006)&(residual<.12)
        alpha[supported]=.75*projection[supported]+.25*prior[supported]
        if coverage_ceiling is not None:alpha=np.minimum(alpha,coverage_ceiling)
        # Remove backing spill only on a supported fractional boundary. Keep
        # opaque texture/glints and uncertain thin colored details unchanged.
        changed=supported&(alpha>.02)&(alpha<.98)
        recovered_rgb=(linear-(1-alpha[:,:,None])*b)/np.maximum(alpha[:,:,None],.02)
        linear[changed]=np.clip(recovered_rgb[changed],0,1)
    alpha[alpha<.01]=0;alpha[alpha>.99]=1
    encoded=np.clip(np.round(np.where(linear<=.0031308,linear*12.92,1.055*np.maximum(linear,0)**(1/2.4)-.055)*255),0,255).astype(np.uint8)
    encoded[~changed]=rgb[~changed]
    return encoded,np.round(alpha*255).astype(np.uint8),{'dark_backing_recovery':False,'edge_rgb_pixels':int(changed.sum())}


def extract(rgba, backend=None):
    backend=backend or predictor();rgb=rgba[:,:,:3];h,w=rgb.shape[:2]
    raw=backend.predict(rgb)
    scale=min(1.,2048/max(h,w));size=(max(2,round(w*scale)),max(2,round(h*scale)))
    small=cv2.resize(rgb,size,interpolation=cv2.INTER_AREA) if scale<1 else rgb
    prior=np.clip(cv2.resize(raw,size,interpolation=cv2.INTER_LINEAR),0,1)
    prior,ceiling,fine_evidence=fine_structure(small,prior,backend)
    color,alpha,evidence=refine(small,prior,coverage_ceiling=ceiling)
    evidence.update(fine_evidence)
    if not (alpha>=128).any():raise ValueError('Detailed cutout found no usable foreground')
    result=rgba.copy()
    result[:,:,3]=np.asarray(Image.fromarray(alpha).resize((w,h),Image.Resampling.LANCZOS)) if scale<1 else alpha
    if evidence['edge_rgb_pixels']:
        corrected=cv2.resize(color,(w,h),interpolation=cv2.INTER_LINEAR) if scale<1 else color
        # At capture resolution restrict RGB changes to fractional coverage.
        fractional=(result[:,:,3]>0)&(result[:,:,3]<250)
        result[fractional,:3]=corrected[fractional]
    warnings=['Automatic detailed cutout: inspect the preview before game use']
    if evidence['dark_backing_recovery']:warnings.append('Fine material recovered from uniform dark backing after incomplete object prediction; inspect holes and small pieces')
    boundary=np.concatenate([alpha[0],alpha[-1],alpha[:,0],alpha[:,-1]])
    if np.any(boundary>127):warnings.append('Subject approaches photograph edge: check capture coverage')
    return result,{'method':'local BiRefNet Lite segmentation and topology-preserving edge refinement',
                   'model_sha256':MODEL_SHA256,'runtime_version':backend.runtime_version,'working_long_edge':max(small.shape[:2]),
                   'edge_colors_prepared':True,'subject_fraction':float((alpha>=128).mean()),
                   **evidence,'review_required':True,'warnings':warnings}
