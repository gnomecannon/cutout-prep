"""Deterministic folder preparation with automatic cutouts; originals read-only.

Requires Pillow, NumPy, CPU OpenCV and SciPy.
Optional rawpy/LibRaw develops full-resolution DNG photographs.
Run --help or drag a folder onto Process Images.cmd.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import stat
import sys
import tempfile
import textwrap

try:
    import numpy as np
    from PIL import Image, ImageCms, ImageDraw, ImageFont, ImageOps
except ImportError as exc:
    raise SystemExit('This Python needs the Cutout Prep dependencies. Install the project into this Python environment. '+str(exc))

from . import __version__

VERSION = __version__
TOOL = 'Cutout Prep'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.tif', '.tiff', '.bmp', '.tga', '.dng'}
REPORT = 'ProcessingReport.json'
PREVIEW = 'Preview.jpg'
DEFAULTS = {'size':4096, 'padding':96, 'exposure':'auto', 'target_median':0.25,
            'max_lift_ev':2.0, 'rotation_degrees':0, 'edge_decontaminate':True,
            'saturation':1.0, 'shadow_lift':0.45, 'raw_tone':'auto', 'name_prefix':'', 'background':'auto',
            'components':'largest'}
PRESETS = {'photo':{}, 'artwork':{'background':'keep', 'exposure':'none', 'shadow_lift':0.0,
           'saturation':1.0, 'edge_decontaminate':False, 'components':'all', 'raw_tone':'neutral'}}
PER_IMAGE = {'name', 'mask', 'rotation_degrees', 'exposure', 'saturation', 'shadow_lift', 'target_median', 'raw_tone', 'edge_decontaminate', 'skip', 'background', 'uv_transform', 'components'}
RESERVED = {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}

def digest(data): return hashlib.sha256(data).hexdigest()
def file_hash(path): return digest(path.read_bytes())
def json_hash(data): return digest(json.dumps(data,sort_keys=True,separators=(',',':')).encode())
def inside(path, parent): return path == parent or parent in path.parents

def environment_provenance():
    """Non-private runtime identity used to invalidate managed export caches."""
    try:
        import cv2
        import scipy
        from PIL import __version__ as pillow_version
    except ImportError as exc:
        raise ValueError('Required runtime dependency unavailable; install this project and its dependencies in the same Python environment. '+str(exc)) from exc
    return {'python':{'version':platform.python_version(),'implementation':platform.python_implementation()},
            'platform':{'system':platform.system(),'architecture':platform.machine()},
            'libraries':{'Pillow':pillow_version,'NumPy':np.__version__,
                         'OpenCV':cv2.__version__,'SciPy':scipy.__version__}}

def is_link_like(path):
    """Skip child links and Windows reparse points on every supported Python."""
    try:
        if path.is_symlink():return True
        if os.name=='nt':
            return bool(getattr(path.lstat(),'st_file_attributes',0)&stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return False
    except OSError:
        # An inaccessible/changing child is not permission to follow it.
        return True

def srgb_decode(v): return np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)
def srgb_encode(v): return np.where(v<=.0031308,v*12.92,1.055*np.maximum(v,0)**(1/2.4)-.055)

def atomic_bytes(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.image-prep-',suffix='.tmp',dir=path.parent,delete=False) as out:
            temp=Path(out.name);out.write(data)
        os.replace(temp,path)
    finally:
        if temp is not None and temp.exists(): temp.unlink()

def largest_component(alpha):
    """Largest eight-connected alpha>0 island; retain its exact alpha samples."""
    parents,areas,runs=[],[],[]
    def root(i):
        while parents[i]!=i:
            parents[i]=parents[parents[i]];i=parents[i]
        return i
    previous=[]
    for y in range(alpha.shape[0]):
        edges=np.flatnonzero(np.diff(np.r_[False,alpha[y]>0,False]));current=[];j=0
        for start,end in zip(edges[::2],edges[1::2]):
            start,end=int(start),int(end);i=len(parents)
            parents.append(i);areas.append(end-start)
            while j<len(previous) and previous[j][1]<start:j+=1
            k=j
            while k<len(previous) and previous[k][0]<=end:
                p,q=root(previous[k][2]),root(i)
                if p!=q:parents[p]=q;areas[q]+=areas[p]
                k+=1
            current.append((start,end,i));runs.append((y,start,end,i))
        previous=current
    roots=[i for i,p in enumerate(parents) if i==p]
    if not roots:raise ValueError('Empty/fully transparent subject')
    keep=max(roots,key=lambda i:areas[i]);result=np.zeros_like(alpha)
    for y,start,end,i in runs:
        if root(i)==keep:result[y,start:end]=alpha[y,start:end]
    return result,{'components':len(roots),'removed_pixels':int(np.count_nonzero(alpha)-np.count_nonzero(result))}

def select_components(alpha,mode):
    """Retain all supplied alpha islands or the largest exact sample island."""
    if mode=='largest':return largest_component(alpha)
    if mode!='all':raise ValueError('components must be largest or all')
    if not np.any(alpha>0):raise ValueError('Empty/fully transparent subject')
    return alpha.copy(),{'components':None,'removed_pixels':0,'mode':'all'}

def edge_fill(rgb,alpha):
    """Push-pull color into alpha-zero pixels without changing visible RGB."""
    colors,weights=[rgb],[(alpha>0).astype(np.float32)]
    if not weights[0].any():raise ValueError('No color-bearing subject')
    while max(weights[-1].shape)>1:
        w=weights[-1];size=(max(1,(w.shape[1]+1)//2),max(1,(w.shape[0]+1)//2))
        sw=np.array(Image.fromarray(w).resize(size,Image.Resampling.BOX));sc=np.empty((*sw.shape,3),np.float32)
        for c in range(3):
            v=np.array(Image.fromarray(colors[-1][:,:,c]*w).resize(size,Image.Resampling.BOX))
            sc[:,:,c]=v/np.maximum(sw,1e-8)
        colors.append(sc);weights.append(sw)
    filled=colors[-1]
    for level in range(len(colors)-2,-1,-1):
        w,own=weights[level],colors[level];missing=w<=0;filled_up=own.copy()
        for c in range(3):
            up=np.array(Image.fromarray(filled[:,:,c]).resize((w.shape[1],w.shape[0]),Image.Resampling.BILINEAR))
            filled_up[:,:,c][missing]=up[missing]
        filled=filled_up
    return filled

def load_image(path):
    warnings=[]
    with Image.open(path) as im:
        im.seek(0)
        if getattr(im,'n_frames',1)>1:warnings.append('Only the first image/frame is used')
        if im.mode in {'I','F','I;16','I;16B','I;16L'}:
            raise ValueError('High-bit-depth numeric image needs an explicit 8-bit color conversion first')
        profile=im.info.get('icc_profile');oriented=ImageOps.exif_transpose(im)
        alpha=oriented.convert('RGBA').getchannel('A')
        if profile:
            source_profile=ImageCms.ImageCmsProfile(io.BytesIO(profile))
            color=oriented if oriented.mode in {'RGB','CMYK','LAB','L'} else oriented.convert('RGB')
            color=ImageCms.profileToProfile(color,source_profile,ImageCms.createProfile('sRGB'),outputMode='RGB')
            color_space='ICC converted to sRGB'
        else:
            if oriented.mode in {'CMYK','LAB'}:raise ValueError('CMYK/Lab without an ICC profile is ambiguous')
            color=oriented.convert('RGB')
            exif=im.getexif()
            declared=exif.get(40961)
            if declared is None and 34665 in exif:
                declared=exif.get_ifd(34665).get(40961)
            color_space='EXIF declares sRGB' if declared==1 else 'Untagged: assumed sRGB'
            if declared!=1:warnings.append(color_space)
        rgba=np.dstack((np.array(color),np.array(alpha)))
    return rgba,color_space,warnings

def validate_options(options):
    size,padding=options['size'],options['padding']
    if type(size) is not int or not 64<=size<=8192:raise ValueError('size must be an integer from64 to8192')
    if type(padding) is not int or not 1<=padding<size//2:raise ValueError('padding must be positive and less than half the size')
    for key in ['target_median','max_lift_ev','rotation_degrees','saturation','shadow_lift']:
        if isinstance(options[key],bool) or not isinstance(options[key],(int,float)) or not math.isfinite(options[key]):
            raise ValueError(key+' must be a finite number')
    if not .05<=options['target_median']<=.8:raise ValueError('target_median must be .05 to .8')
    if not 0<=options['max_lift_ev']<=4:raise ValueError('max_lift_ev must be0 to4')
    if not 0<=options['saturation']<=2:raise ValueError('saturation must be0 to2;1 preserves source chroma')
    if not 0<=options['shadow_lift']<=1:raise ValueError('shadow_lift must be0 to1;0 disables shadow compression')
    ev=options['exposure']
    if ev not in ('auto','none'):
        if isinstance(ev,bool) or not isinstance(ev,(int,float)) or not math.isfinite(ev) or not -4<=ev<=4:
            raise ValueError('exposure must be auto, none, or an EV number from-4 to4')
    if type(options['edge_decontaminate']) is not bool:raise ValueError('edge_decontaminate must be true/false')
    if not isinstance(options['name_prefix'],str):raise ValueError('name_prefix must be text')
    if options['background'] not in ('auto','keep'):raise ValueError('background must be auto or keep')
    if options['raw_tone'] not in ('auto','neutral'):raise ValueError('raw_tone must be auto or neutral')
    if options.get('components','largest') not in ('largest','all'):raise ValueError('components must be largest or all')
    if 'uv_transform' in options:
        uv_matrix(options['uv_transform'],size)

def uv_matrix(value,size):
    """Forward normalized pixel-center UV transform -> output pixel centers."""
    try:matrix=np.asarray(value,dtype=np.float64)
    except (TypeError,ValueError) as exc:raise ValueError('uv_transform must be a finite 3x3 matrix') from exc
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or not np.allclose(matrix[2],[0,0,1],atol=1e-10,rtol=0):
        raise ValueError('uv_transform must be a finite affine 3x3 matrix')
    axes=matrix[:2,:2];gram=axes.T@axes;scale2=np.trace(gram)/2
    if scale2<1e-8 or not np.allclose(gram,np.eye(2)*scale2,atol=1e-7*max(1,scale2),rtol=1e-6):
        raise ValueError('uv_transform supports uniform scale, rotation, reflection and translation only')
    pixels_to_uv=np.array([[1/size,0,.5/size],[0,1/size,.5/size],[0,0,1]],np.float64)
    return np.linalg.inv(pixels_to_uv)@matrix@pixels_to_uv

def output_name(source, options):
    raw=options.get('name')
    if raw is None:
        raw=source.stem
        for suffix in ['_Source','_Cutout']:
            if raw.lower().endswith(suffix.lower()):raw=raw[:-len(suffix)]
        if not raw.lower().endswith('_basecolor'):raw+='_BaseColor'
        prefix=options['name_prefix']
        if prefix and not raw.startswith(prefix):raw=prefix+raw
    if not isinstance(raw,str) or not raw:raise ValueError('name must be nonempty text')
    if raw.lower().endswith('.png'):raw=raw[:-4]
    if not raw:raise ValueError('Output name cannot be an empty stem')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]',raw) or '..' in raw or raw.endswith((' ','.')):
        raise ValueError('Unsafe output name: '+repr(raw))
    if raw.split('.')[0].upper() in RESERVED:raise ValueError('Windows reserved output name: '+raw)
    if len(raw)>180:raise ValueError('Output name exceeds180 characters')
    return raw+'.png'

def exposure_curve(rgb, ev):
    gain=2**ev;peak=rgb.max(axis=2)
    return rgb*(gain/(1+(gain-1)*peak))[:,:,None]

def median_luma(rgb,alpha,*,allow_translucent=False):
    selected=rgb[alpha>=192]
    if len(selected)==0 and allow_translucent:selected=rgb[alpha>0]
    if len(selected)==0:raise ValueError('No sufficiently opaque subject; check alpha/mask')
    return float(np.median(selected@np.array([.2126,.7152,.0722],np.float32)))

def render(rgba,options,profile,*,matte_prepared=False,tone_profile=None):
    warnings=[]
    alpha,cleanup=select_components(rgba[:,:,3],options.get('components','largest'));bbox=Image.fromarray(alpha).getbbox()
    alpha=alpha[bbox[1]:bbox[3],bbox[0]:bbox[2]]
    rgb=rgba[bbox[1]:bbox[3],bbox[0]:bbox[2],:3].astype(np.float32)/255
    linear=srgb_decode(rgb)
    core=np.where(alpha>=240,255,0).astype(np.uint8)
    if options['edge_decontaminate'] and not matte_prepared:
        if not core.any():raise ValueError('No near-opaque interior for edge color cleanup; disable edge_decontaminate for translucent art')
        repaired=edge_fill(linear,core);edge=(alpha>0)&(core==0);linear[edge]=repaired[edge]
        del repaired
    if tone_profile is not None:
        from .dng_profile import apply_profile
        linear=apply_profile(linear,tone_profile)
    # Color-preserving artwork can be wholly translucent. Its median is only
    # reported, so it does not need the opaque sample required by auto exposure.
    translucent_stats=options['exposure']=='none' and options['shadow_lift']==0
    before=median_luma(srgb_encode(linear),alpha,allow_translucent=translucent_stats)
    ev=options['exposure']
    if ev=='auto' and tone_profile is not None:
        from .dng_profile import asset_exposure
        curve=lambda values,amount:asset_exposure(values,amount,tone_profile)
    else:
        curve=exposure_curve
    if ev=='auto':
        # Lift only. Natural brighter/autumn colors retain their brightness.
        target=options['target_median'];lo,hi=0.,options['max_lift_ev']
        samples=linear[alpha>=192]
        samples=samples[::max(1,math.ceil(len(samples)/262144))][:,None,:]
        sample_alpha=np.full(samples.shape[:2],255,np.uint8)
        for _ in range(12):
            middle=(lo+hi)/2
            if median_luma(srgb_encode(curve(samples,middle)),sample_alpha)<target:lo=middle
            else:hi=middle
        ev=0. if before>=target else round((lo+hi)/2,4)
    elif ev=='none':ev=0.
    corrected=curve(linear,ev)
    from .tone_normalize import lift_shadows
    corrected,shadow_details=lift_shadows(corrected,alpha,options['shadow_lift'])
    from .color_adjust import adjust_saturation
    corrected=adjust_saturation(corrected,options['saturation'])
    # Rotate and resize premultiplied linear channels; never interpolate edge
    # RGB independently from its coverage. Positive rotation is counterclockwise.
    af=alpha.astype(np.float32)/255;channels=[Image.fromarray(af)]
    channels += [Image.fromarray(corrected[:,:,c]*af) for c in range(3)]
    angle=options['rotation_degrees']%360
    if angle:channels=[im.rotate(angle,Image.Resampling.BICUBIC,expand=True,fillcolor=0) for im in channels]
    ab=np.clip(np.array(channels[0]),0,1);rotbox=Image.fromarray(np.round(ab*255).astype(np.uint8)).getbbox()
    if rotbox is None:raise ValueError('Rotation produced an empty subject')
    channels=[im.crop(rotbox) for im in channels]
    span=options['size']-2*options['padding'];scale=span/max(channels[0].size)
    dims=tuple(max(1,round(v*scale)) for v in channels[0].size)
    size=options['size'];x=(size-dims[0])//2;y=(size-dims[1])//2
    layout=uv_matrix(options['uv_transform'],size) if 'uv_transform' in options else np.eye(3)
    aligned=not np.allclose(layout,np.eye(3),atol=1e-10,rtol=0)
    if aligned:
        # Compose the pair layout with the normal source-to-square framing.
        # Warp the native premultiplied channels once, rather than resampling
        # a previously resized 4K texture a second time.
        import cv2
        cv2.setNumThreads(2)
        width,height=channels[0].size;sx,sy=dims[0]/width,dims[1]/height
        framing=np.array([[sx,0,x+.5*sx-.5],[0,sy,y+.5*sy-.5],[0,0,1]],np.float64)
        combined=layout@framing
        arrays=[cv2.warpAffine(np.array(im),combined[:2],(size,size),flags=cv2.INTER_LANCZOS4,
                               borderMode=cv2.BORDER_CONSTANT,borderValue=0) for im in channels]
    else:
        # Retain the exact established path for unchanged front/unpaired views.
        arrays=[np.array(im.resize(dims,Image.Resampling.LANCZOS)) for im in channels]
    raw_alpha=arrays[0];resized_alpha=np.clip(raw_alpha,0,1)
    a8=np.round(resized_alpha*255).astype(np.uint8);a8,post=select_components(a8,options.get('components','largest'))
    resized=np.stack([np.clip(v/np.maximum(raw_alpha,1e-8),0,1) for v in arrays[1:]],axis=2)
    if aligned:
        out_alpha=a8;out_rgb=resized
        aligned_box=Image.fromarray(out_alpha).getbbox()
        if min(aligned_box[0],aligned_box[1],size-aligned_box[2],size-aligned_box[3])<options['padding']:
            raise ValueError('uv_transform leaves insufficient transparent padding; recompute the common pair frame')
    else:
        out_alpha=np.zeros((size,size),np.uint8);out_rgb=np.zeros((size,size,3),np.float32)
        out_alpha[y:y+dims[1],x:x+dims[0]]=a8;out_rgb[y:y+dims[1],x:x+dims[0]]=resized
    out_rgb=edge_fill(out_rgb,out_alpha)
    encoded=np.clip(np.round(srgb_encode(out_rgb)*255),0,255).astype(np.uint8)
    result=Image.fromarray(np.dstack((encoded,out_alpha)))
    buf=io.BytesIO();result.save(buf,format='PNG',icc_profile=profile,compress_level=6)
    if cleanup['removed_pixels']>np.count_nonzero(alpha)*.05:warnings.append('Substantial disconnected content removed; review preview')
    if scale>1:warnings.append('Upscaled source; no new captured detail')
    dark=np.all(rgba[:,:,:3]==0,axis=2)&(rgba[:,:,3]>=192)
    if dark.sum()>max(32,np.count_nonzero(alpha)*.005):warnings.append('Clipped black source detail remains; exposure cannot reconstruct it')
    record={'source_bbox':list(bbox),'cleanup':cleanup,'resampling_cleanup':post,'exposure_ev':ev,
            'source_median_srgb_luma':round(before,5),'output_median_srgb_luma':round(median_luma(encoded/255,out_alpha,allow_translucent=translucent_stats),5),
            'scale':round(scale,6),'rotation_degrees':options['rotation_degrees'],
            'components':options.get('components','largest'),
            'saturation':options['saturation'],'automatic_matte_colors_preserved':matte_prepared,
            'shadow_lift':options['shadow_lift'],'shadow_adjustment':shadow_details,
            'raw_tone_profile_applied':tone_profile is not None,
            'output_bbox':list(Image.fromarray(out_alpha).getbbox()),'output_size':[size,size]}
    if 'uv_transform' in options:
        record['pair_layout']={'uv_transform':options['uv_transform'],
                               'resampling':'native premultiplied linear Lanczos4 with composed layout' if aligned else 'unchanged standard framing',
                               'pixel_center_matrix':layout.tolist()}
    return buf.getvalue(),record,warnings

def scan(folder, output, recursive, excluded):
    found=[]
    for root,dirs,files in os.walk(folder,followlinks=False):
        dirs[:]=sorted([name for name in dirs if not is_link_like(Path(root)/name)
                       and not inside((Path(root)/name).resolve(),output)],key=str.casefold)
        for name in sorted(files,key=str.casefold):
            path=Path(root)/name
            if path.suffix.lower() not in EXTENSIONS or is_link_like(path):continue
            if path.resolve() in excluded or inside(path.resolve(),output):continue
            found.append(path)
        if not recursive:break
    return found

def preview_bytes(output, outputs):
    entries=[]
    for name,record in sorted(outputs.items(),key=lambda v:v[0].casefold()):
        path=output/name
        if path.is_file() and file_hash(path)==record['output_sha256']:entries.append((name,path))
    if not entries:return None
    tile_w,tile_h,cols=340,390,min(4,len(entries))
    sheet=Image.new('RGB',(cols*tile_w,math.ceil(len(entries)/cols)*tile_h),(85,89,93))
    font=ImageFont.load_default(size=15)
    for i,(name,path) in enumerate(entries):
        with Image.open(path) as im:
            im.thumbnail((320,320),Image.Resampling.LANCZOS)
            sheet.paste(im,((i%cols)*tile_w+(tile_w-im.width)//2,(i//cols)*tile_h+(320-im.height)//2),im)
        label='\n'.join(textwrap.wrap(name,34)[:3])
        ImageDraw.Draw(sheet).multiline_text(((i%cols)*tile_w+10,(i//cols)*tile_h+328),label,font=font,fill='white')
    buf=io.BytesIO();sheet.save(buf,format='JPEG',quality=93);return buf.getvalue()

def read_settings(path):
    data=json.loads(path.read_text(encoding='utf-8-sig')) if path else {}
    if not isinstance(data,dict) or set(data)-{'defaults','images'}:raise ValueError('Settings require only defaults and images objects')
    if not isinstance(data.get('defaults',{}),dict) or set(data.get('defaults',{}))-set(DEFAULTS):raise ValueError('Unknown defaults setting')
    if not isinstance(data.get('images',{}),dict):raise ValueError('images must be an object keyed by relative input filename')
    for key,opts in data.get('images',{}).items():
        if not isinstance(opts,dict) or set(opts)-PER_IMAGE:raise ValueError('Unknown per-image setting for '+key)
        if 'mask' in opts and (not isinstance(opts['mask'],str) or not opts['mask']):raise ValueError('mask must be a nonempty path for '+key)
        if 'skip' in opts and type(opts['skip']) is not bool:raise ValueError('skip must be true/false for '+key)
    return data

def read_input(src,options,folder):
    raw_info=None
    if src.suffix.lower()=='.dng':
        from .raw_decode import load_dng
        rgba,color_space,warnings,raw_info=load_dng(src,srgb_encode)
    else:
        rgba,color_space,warnings=load_image(src)
    mask_data=b'';mask_path=None;cutout={'method':'existing transparency','review_required':False}
    if options.get('mask'):
        mask_path=(folder/options['mask']).resolve();mask_data=mask_path.read_bytes()
        with Image.open(io.BytesIO(mask_data)) as m:
            m=ImageOps.exif_transpose(m).convert('L')
            if m.size!=(rgba.shape[1],rgba.shape[0]):raise ValueError('Mask dimensions must match the EXIF-oriented photo')
            rgba[:,:,3]=np.round(rgba[:,:,3].astype(np.float32)*np.array(m)/255).astype(np.uint8)
        cutout={'method':'optional supplied mask','review_required':False}
    elif np.all(rgba[:,:,3]==255) and options['background']=='auto':
        from .auto_cutout import extract
        rgba,cutout=extract(rgba)
        warnings.extend(cutout['warnings'])
        if options.get('components','largest')=='all':
            warnings.append('Automatic extraction selects one connected subject; components=all retains only islands supplied by that extraction. Use existing transparency or an explicit mask for multiple objects.')
    elif np.all(rgba[:,:,3]==255):
        cutout={'method':'opaque rectangular image retained explicitly','review_required':False}
    if raw_info is not None and options['raw_tone']=='auto':
        from .dng_profile import prepare_profile
        tone_profile=prepare_profile(src,rgba)
        raw_info['render_profile']=tone_profile
        raw_info['embedded_preview_used_for_color_calibration']=tone_profile is not None
        if tone_profile is None:
            warnings.append('No supported embedded DNG tone/reference profile; neutral RAW color retained')
        else:
            warnings.append('Embedded DNG tone curve and global color calibration applied; preview supplies reference statistics only, never texture detail')
            warnings.extend(tone_profile.get('warnings',[]))
    return rgba,color_space,warnings,mask_data,mask_path,cutout,raw_info

def transform_options(options):
    return {k:v for k,v in options.items() if k not in {'name','name_prefix','mask','skip'}}

def input_pixel_key(rgba,options,render_profile=None):
    from .dng_profile import render_identity
    return digest(rgba.tobytes()+json_hash(transform_options(options)).encode()+json_hash(render_identity(render_profile)).encode()+str(rgba.shape).encode())

def run(args):
    folder=args.folder.expanduser().resolve();output=(args.output or folder/'Processed').expanduser().resolve()
    if not folder.is_dir():raise ValueError('Input folder does not exist: '+str(folder))
    if inside(folder,output):raise ValueError('Output must not equal or contain the input folder')
    settings_path=args.settings or (folder/'image-settings.json' if (folder/'image-settings.json').is_file() else None)
    settings=read_settings(settings_path)
    preset=getattr(args,'preset','photo')
    if preset not in PRESETS:raise ValueError('preset must be photo or artwork')
    # Existing per-image overrides remain the final layer. CLI values override
    # JSON defaults, while the selected preset supplies only earlier defaults.
    defaults={**DEFAULTS,**PRESETS[preset],**settings.get('defaults',{})}
    for key in ('size','padding','exposure','background','saturation','shadow_lift','target_median','raw_tone','components'):
        if getattr(args,key,None) is not None:defaults[key]=getattr(args,key)
    validate_options(defaults)
    overrides=settings.get('images',{})
    excluded=set()
    for opts in overrides.values():
        if 'mask' in opts:
            path=(folder/opts['mask']).resolve();excluded.add(path)
    sources=scan(folder,output,args.recursive,excluded)
    if not sources:raise ValueError('No supported source images found')
    output.mkdir(parents=True,exist_ok=True)
    report_path=output/REPORT
    prior=json.loads(report_path.read_text(encoding='utf-8')) if report_path.is_file() else {}
    if report_path.exists() and (not isinstance(prior,dict) or prior.get('tool')!=TOOL or
            prior.get('input_root')!=str(folder) or not isinstance(prior.get('outputs'),dict)):
        raise ValueError('Existing report is unmanaged or belongs to another input/tool; preserving it. Choose a different output folder.')
    outputs=prior.get('outputs',{}).copy();files=[];claims={};duplicates={};blocked_pixels={}
    for name,record in outputs.items():
        if (not isinstance(name,str) or not isinstance(record,dict) or
                output_name(Path('unused'),{**defaults,'name':name})!=name or
                any(not isinstance(record.get(field),str) or not re.fullmatch('[0-9a-f]{64}',record[field])
                    for field in ('output_sha256','signature','processor_sha256','pixel_key')) or
                not isinstance(record.get('source'),str)):
            raise ValueError('Malformed owned-output record; preserving existing output directory')
    profile_path=Path(__file__).with_name('sRGB.icc');profile=profile_path.read_bytes()
    environment=environment_provenance()
    processor=digest(Path(__file__).read_bytes()+Path(__file__).with_name('__init__.py').read_bytes()+Path(__file__).with_name('auto_cutout.py').read_bytes()+Path(__file__).with_name('raw_decode.py').read_bytes()+Path(__file__).with_name('color_adjust.py').read_bytes()+Path(__file__).with_name('dng_profile.py').read_bytes()+Path(__file__).with_name('tone_normalize.py').read_bytes()+Path(__file__).with_name('pair_alignment.py').read_bytes()+profile+json_hash(environment).encode())
    for name,record in outputs.items():
        pixel_key=record.get('pixel_key');path=output/name
        if not pixel_key or not path.is_file():continue
        if file_hash(path)!=record['output_sha256']:blocked_pixels[pixel_key]=name
        elif record.get('processor_sha256')==processor:duplicates.setdefault(pixel_key,name)
    plans=[]
    for src in sources:
        relative=src.relative_to(folder).as_posix();options={**defaults,**overrides.get(relative,{})}
        rec={'source':relative,'warnings':[],'settings':options};files.append(rec)
        try:
            if options.get('skip'):
                if type(options['skip']) is not bool:raise ValueError('skip must be true/false')
                rec['status']='excluded';continue
            validate_options(options);name=output_name(src,options)
            if name.casefold() in {REPORT.casefold(),PREVIEW.casefold()}:raise ValueError('Output name reserved for tool report/preview')
            plans.append((src,options,name,rec));claims.setdefault(name.casefold(),[]).append((src,options))
        except Exception as exc:rec.update(status='error',message=str(exc))
    for src,options,name,rec in plans:
        print('Preparing '+rec['source'],flush=True)
        try:
            raw=src.read_bytes();rec['source_sha256']=digest(raw)
            rgba,color_space,warnings,mask_data,mask_path,cutout,raw_info=read_input(src,options,folder)
            rec['color_management']=color_space;rec['warnings']+=warnings;rec['cutout']=cutout
            if raw_info is not None:rec['raw_decode']=raw_info
            rec['review_required']=cutout['review_required']
            signature_options=transform_options(options)
            signature_data={'processor':processor,'source':rec['source_sha256'],'mask':digest(mask_data),'settings':signature_options}
            if raw_info is not None:
                signature_data['raw_decoder']=raw_info['decoder_signature']
                signature_data['raw_render']=raw_info.get('render_profile')
            signature=json_hash(signature_data)
            pixel_key=input_pixel_key(rgba,options,raw_info.get('render_profile') if raw_info else None)
            if pixel_key in blocked_pixels:
                raise ValueError('Existing canonical output was manually changed; preserving it and avoiding duplicate aliases: '+blocked_pixels[pixel_key])
            if pixel_key in duplicates and (duplicates[pixel_key]!=name or outputs[duplicates[pixel_key]].get('source')!=rec['source']):
                rec.update(status='duplicate',duplicate_of=duplicates[pixel_key],output=duplicates[pixel_key]);continue
            group=claims[name.casefold()]
            if len(group)>1:
                # Same-stem duplicates may claim one export; different pixels
                # or transforms must be named deliberately before any write.
                for other,other_options in group:
                    if other==src:continue
                    other_input=read_input(other,other_options,folder);other_rgba=other_input[0];other_raw=other_input[6]
                    if input_pixel_key(other_rgba,other_options,other_raw.get('render_profile') if other_raw else None)!=pixel_key:
                        raise ValueError('Output name collision: '+'; '.join(p.relative_to(folder).as_posix() for p,_ in group)+'. Set distinct name overrides.')
            dest=output/name
            # Check case-insensitively even on platforms with case-sensitive paths.
            existing=next((p for p in output.iterdir() if p.name.casefold()==name.casefold()),None)
            owned=outputs.get(name)
            if existing is not None:
                if not owned or existing.name!=name or file_hash(existing)!=owned['output_sha256']:
                    raise ValueError('Existing output is unmanaged or manually changed; preserving it: '+existing.name)
                if owned['signature']==signature:
                    rec.update(status='unchanged',output=name,exposure_ev=owned.get('exposure_ev'))
                    duplicates[pixel_key]=name;continue
                if not args.update:
                    rec.update(status='needs_update',message='Source/settings changed; use --update to replace this unchanged managed export',output=name);continue
            data,details,warnings=render(rgba,options,profile,matte_prepared=cutout.get('edge_colors_prepared',False),tone_profile=raw_info.get('render_profile') if raw_info else None)
            # Refuse a source change during processing rather than reporting a
            # successful result against different input bytes.
            if file_hash(src)!=rec['source_sha256']:raise ValueError('Source changed during processing; retry when editing is finished')
            if mask_path is not None and file_hash(mask_path)!=digest(mask_data):raise ValueError('Mask changed during processing; retry when editing is finished')
            if existing is None:
                if dest.exists():raise ValueError('An output appeared during processing; preserving it: '+name)
            elif not dest.is_file() or file_hash(dest)!=owned['output_sha256']:
                raise ValueError('Output changed during processing; preserving it: '+name)
            atomic_bytes(dest,data)
            if file_hash(dest)!=digest(data):raise OSError('Output readback failed')
            with Image.open(dest) as im:
                if im.mode!='RGBA' or im.size!=(options['size'],)*2 or im.info.get('icc_profile')!=profile:raise OSError('Output structure/profile readback failed')
            rec.update(details);rec['warnings']+=warnings;rec.update(status='processed',output=name)
            outputs[name]={'signature':signature,'pixel_key':pixel_key,'processor_sha256':processor,
                           'output_sha256':digest(data),'source':rec['source'],'exposure_ev':details['exposure_ev']}
            duplicates[pixel_key]=name
        except Exception as exc:rec.update(status='error',message=str(exc))
    preview=preview_bytes(output,outputs);preview_hash=prior.get('preview_sha256')
    if preview is not None:
        dest=output/PREVIEW
        if dest.exists() and (not preview_hash or file_hash(dest)!=preview_hash):
            files.append({'source':None,'status':'error','message':'Existing Preview.jpg is unmanaged/manually changed; preserving it'})
        else:atomic_bytes(dest,preview);preview_hash=digest(preview)
    counts=dict(Counter(r['status'] for r in files))
    review_count=sum(bool(r.get('review_required')) for r in files)
    if review_count:counts['review_required']=review_count
    report={'tool':TOOL,'version':VERSION,'preset':preset,'environment':environment,'processor_sha256':processor,'input_root':str(folder),
            'output_root':str(output),'defaults':defaults,'counts':counts,'files':files,
            'outputs':outputs,'preview_sha256':preview_hash,
            'limits':'Prepared color, not measured albedo. Automatic cutouts work best on isolated subjects against plain backgrounds; review uncertain boundaries. No botanical identification, roughness, or clipped-detail reconstruction.'}
    atomic_bytes(report_path,json.dumps(report,indent=2,ensure_ascii=False).encode('utf-8'))
    print('\n'+', '.join(f'{key}: {value}' for key,value in counts.items()),flush=True)
    print('Output: '+str(output),flush=True)
    print('Review Preview.jpg and ProcessingReport.json.',flush=True)
    return 2 if any(counts.get(k,0) for k in ['error','review_required','needs_update']) else 0

def run_guarded(args):
    folder=args.folder.expanduser().resolve();output=(args.output or folder/'Processed').expanduser().resolve()
    if not folder.is_dir():raise ValueError('Input folder does not exist: '+str(folder))
    if inside(folder,output):raise ValueError('Output must not equal or contain the input folder')
    output.mkdir(parents=True,exist_ok=True)
    lock=output/'.image-preparation.lock'
    try:descriptor=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise ValueError('Output has an active/interrupted batch lock. Finish the other run before reusing this output folder: '+str(lock))
    try:
        os.write(descriptor,str(os.getpid()).encode())
        return run(args)
    finally:
        os.close(descriptor);lock.unlink()

def main(argv=None):
    # Redirected Windows streams can use a legacy code page even when the
    # filesystem accepts Unicode names. Escape only unrepresentable console
    # characters; actual paths and UTF-8 JSON retain their original spelling.
    for stream in (sys.stdout,sys.stderr):
        reconfigure=getattr(stream,'reconfigure',None)
        if reconfigure is not None:
            try:reconfigure(errors='backslashreplace')
            except (AttributeError,OSError,TypeError,ValueError):pass
    p=argparse.ArgumentParser(prog='cutout-prep',description=__doc__)
    p.add_argument('--version',action='version',version='%(prog)s '+VERSION)
    p.add_argument('folder',nargs='?',type=Path,help='Folder of source images; prompts when omitted')
    p.add_argument('--output',type=Path,help='Output directory; default INPUT/Processed')
    p.add_argument('--settings',type=Path,help='JSON settings; default INPUT/image-settings.json if present')
    p.add_argument('--preset',choices=tuple(PRESETS),default='photo',help='photo: automatic cleanup/color; artwork: retain supplied alpha islands and color; default photo')
    p.add_argument('--components',choices=('largest','all'),help='Keep largest alpha subject (photo default) or all supplied islands (artwork default); automatic extraction still selects one object')
    p.add_argument('--size',type=int,help='Square output size; default4096')
    p.add_argument('--padding',type=int,help='Empty pixels on each end of longest subject axis; default96')
    p.add_argument('--exposure',type=str,help='auto, none or EV number; default auto, lift capped at2EV')
    p.add_argument('--background',choices=['auto','keep'],help='Automatically cut out opaque photos (default) or keep their rectangular frame')
    p.add_argument('--saturation',type=float,help='Perceptual chroma multiplier0 to2; default1 preserves rendered chroma')
    p.add_argument('--target-median',type=float,help='Minimum subject median sRGB luminance for auto exposure; default0.25')
    p.add_argument('--raw-tone',choices=['auto','neutral'],help='Use a supported embedded DNG tone profile (default auto) or neutral RAW development')
    p.add_argument('--shadow-lift',type=float,help='Relative shadow compression0 to1; default0.45,0 disables; midtones/highlights retained')
    p.add_argument('--recursive',action='store_true',help='Include nested input folders; output/masks/junctions excluded')
    p.add_argument('--update',action='store_true',help='Regenerate changed inputs/settings only when previous managed export is unmodified')
    args=p.parse_args(argv)
    if args.folder is None:
        if not sys.stdin.isatty():p.error('folder is required in noninteractive use')
        args.folder=Path(input('Paste the folder of source images, then press Enter: ').strip().strip('"'))
    if args.exposure is not None and args.exposure not in ('auto','none'):
        try:args.exposure=float(args.exposure)
        except ValueError:p.error('--exposure requires auto, none or an EV number')
    try:return run_guarded(args)
    except Exception as exc:print('Cannot prepare folder: '+str(exc),file=sys.stderr);return 1

if __name__=='__main__':sys.exit(main())
