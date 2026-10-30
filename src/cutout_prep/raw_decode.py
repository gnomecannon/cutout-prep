"""Optional full-resolution DNG development; never substitute an embedded preview."""
import importlib
import os
import numpy as np

RECIPE = {
    'profile':'full-resolution-linear-srgb-camera-wb-v1',
    'demosaic_algorithm':'AHD','half_size':False,'use_camera_wb':True,
    'use_auto_wb':False,'no_auto_bright':True,'no_auto_scale':False,
    'bright':1.0,'output_color':'sRGB','output_bps':16,'gamma':[1,1],
    'user_flip':None,'highlight_mode':'Clip','denoise':'off',
    'bridge':'exact sRGB transfer, round to RGBA8 once before existing image pipeline',
}

def decoder():
    os.environ.setdefault('OMP_NUM_THREADS','2')
    try:
        return importlib.import_module('rawpy')
    except (ImportError,OSError) as exc:
        raise ValueError('DNG RAW decoder is unavailable for this Python. Install this project with its [raw] extra into the same Python environment. No preview fallback was used. '+str(exc)) from exc

def load_dng(path,encode_srgb):
    rawpy = decoder()
    signature = {
        'rawpy':str(rawpy.__version__),
        'libraw':list(rawpy.libraw_version),
        'features':{str(k):bool(v) for k,v in sorted(rawpy.flags.items())},
        'recipe':RECIPE,
    }
    try:
        with rawpy.imread(str(path)) as raw:
            wb = np.asarray(raw.camera_whitebalance,dtype=np.float64)
            if wb.size < 3 or not np.isfinite(wb).all() or (wb[:3] <= 0).any():
                raise ValueError('DNG has no valid as-shot white balance; refusing an unreported automatic/daylight fallback')
            info = {
                'decoder_signature':signature,
                'raw_size':[int(raw.sizes.raw_width),int(raw.sizes.raw_height)],
                'visible_size_before_orientation':[int(raw.sizes.width),int(raw.sizes.height)],
                'raw_flip':int(raw.sizes.flip),
                'camera_white_balance':wb.tolist(),
                'sensor_white_level':int(raw.white_level),
                'sensor_black_levels':[int(v) for v in raw.black_level_per_channel],
                'embedded_preview_used':False,
            }
            rgb16 = raw.postprocess(
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD,half_size=False,
                use_camera_wb=True,use_auto_wb=False,no_auto_bright=True,
                no_auto_scale=False,bright=1.0,exp_shift=None,
                output_color=rawpy.ColorSpace.sRGB,output_bps=16,gamma=(1,1),
                user_flip=None,highlight_mode=rawpy.HighlightMode.Clip,
                fbdd_noise_reduction=rawpy.FBDDNoiseReductionMode.Off,
                median_filter_passes=0,
            )
    except rawpy.LibRawError as exc:
        raise ValueError('Full DNG RAW decode failed; this compression/camera may be unsupported. No embedded JPEG was substituted. '+str(exc)) from exc
    if rgb16.dtype != np.uint16 or rgb16.ndim != 3 or rgb16.shape[2] != 3:
        raise ValueError('DNG decoder returned an unsupported pixel layout')
    height,width = rgb16.shape[:2]
    info['developed_size'] = [width,height]
    info['working_pixel_format'] = 'RGBA8 sRGB; source DNG retained unchanged'
    rgba = np.empty((height,width,4),np.uint8)
    for start in range(0,height,256):
        values = rgb16[start:start+256].astype(np.float32)/65535.0
        rgba[start:start+256,:,:3] = np.clip(np.rint(encode_srgb(values)*255),0,255).astype(np.uint8)
    rgba[:,:,3] = 255
    warnings = ['DNG developed from full RAW pixels with as-shot white balance; camera/Apple preview tone rendering may differ',
                'RAW is developed through 16-bit linear RGB, then uses the existing 8-bit sRGB asset pipeline']
    return rgba,'DNG RAW developed to actual sRGB; RAW orientation applied once',warnings,info
