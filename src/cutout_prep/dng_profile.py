"""DNG profile tone rendering from full-RAW color, never preview pixels.

The supplied profile tone curve is applied in linear ProPhoto D50 using the
Adobe reference RGB-tone ordering rule. Aligned opaque subject samples from
the camera preview calibrate global exposure, a monotonic luminance residual
and a bounded shadow hue/chroma correction. These are global color-coordinate
transforms; no preview pixel, mask, spatial gain map or texture detail enters
the output. Texture remains full-resolution RAW. This is a bounded rendering
approximation, not an implementation of Apple's complete DNG pipeline.

References:
https://android.googlesource.com/platform/external/dng_sdk.git/+/refs/heads/main/source/dng_reference.cpp
https://www.w3.org/TR/css-color-4/#color-conversion-code
"""
from pathlib import Path
import hashlib
import math
import numpy as np
from PIL import Image,ImageCms
import io

RECIPE='dng-profile-prophoto-rgbtone-native-toe-shadow-chromatic-v4'
_SRGB_XYZ=np.array([[506752/1228815,87881/245763,12673/70218],
    [87098/409605,175762/245763,12673/175545],
    [7918/409605,87881/737289,1001167/1053270]],np.float64)
_D65_D50=np.array([[1.0479297925449969,.022946870601609652,-.05019226628920524],
    [.02962780877005599,.9904344267538799,-.017073799063418826],
    [-.009243040646204504,.015055191490298152,.7518742814281371]],np.float64)
_XYZ_PP=np.array([[1.3457868816471583,-.25557208737979464,-.05110186497554526],
    [-.5446307051249019,1.5082477428451468,.02052744743642139],
    [0.,0.,1.2119675456389452]],np.float64)
SRGB_TO_PROPHOTO=_XYZ_PP@_D65_D50@_SRGB_XYZ
PROPHOTO_TO_SRGB=np.linalg.inv(SRGB_TO_PROPHOTO)
_LUMA=np.array([.2126,.7152,.0722],np.float32)

def _decode(v):return np.where(v<=.04045,v/12.92,((v+.055)/1.055)**2.4)

def read_profile(path):
    """Read only DNG metadata; return None for absent/unsupported tone data."""
    with Image.open(path) as im:
        if not hasattr(im,'tag_v2'):return None
        values=im.tag_v2.get(50940)
        baseline=float(im.tag_v2.get(50730,0.))
        name=str(im.tag_v2.get(50936,'Embedded DNG profile'))
    if values is None:return None
    points=np.asarray(values,dtype=np.float64)
    if points.size<4 or points.size%2 or points.size>131072:raise ValueError('Invalid DNG profile tone curve length')
    points=points.reshape(-1,2)
    if not np.isfinite(points).all() or not np.isfinite(baseline):raise ValueError('Non-finite DNG tone metadata')
    if np.any(np.diff(points[:,0])<=0) or np.any(np.diff(points[:,1])<0):raise ValueError('Non-monotonic DNG profile tone curve')
    if np.any(points<0) or np.any(points>1) or not np.allclose(points[0],[0,0],atol=1e-6) or not np.allclose(points[-1],[1,1],atol=1e-6):raise ValueError('DNG tone curve must span normalized black and white')
    return {'recipe':RECIPE,'name':name,'tone_curve':points.tolist(),
        'curve_sha256':hashlib.sha256(points.tobytes()).hexdigest(),
        'baseline_exposure_ev':baseline,'input_exposure_ev':baseline,
        'curve_interpolation':'dense piecewise linear, Adobe min/max RGB-tone ordering',
        'preview_role':'none until optional global-exposure calibration',
        'full_apple_pipeline':False}

def _exposure(values,ev):
    if ev>=0:return np.clip(values*2.**ev,0,1)
    slope=2.**ev;a=16./9.*(1-slope);b=slope-.5*a;c=1-a-b
    return np.where(values<=.25,values*slope,(a*values+b)*values+c)

def _apply_values(values,profile,ev):
    pp=values@SRGB_TO_PROPHOTO.astype(values.dtype).T
    pp=_exposure(np.clip(pp,0,1),ev)
    points=np.asarray(profile['tone_curve'])
    low=pp.min(axis=-1);high=pp.max(axis=-1)
    mapped_low=np.interp(low,points[:,0],points[:,1])
    mapped_high=np.interp(high,points[:,0],points[:,1])
    fraction=(pp-low[...,None])/np.maximum((high-low)[...,None],1e-12)
    mapped=mapped_low[...,None]+fraction*(mapped_high-mapped_low)[...,None]
    result=np.clip(mapped@PROPHOTO_TO_SRGB.T,0,1).astype(values.dtype)
    if profile.get('luma_residual_knots'):
        knots=np.asarray(profile['luma_residual_knots'])
        luma=result@_LUMA
        mapped=np.interp(luma,knots[:,0],knots[:,1])
        # Preserve a strictly positive slope and native vein/shadow variation,
        # even if robust isotonic knot estimation contains a flat segment.
        mapped=.98*mapped+.02*luma
        gain=np.clip(mapped/np.maximum(luma,1e-12),.125,8.)
        gain=np.minimum(gain,1./np.maximum(result.max(axis=-1),1e-12))
        result=result*gain[...,None]
    if profile.get('dark_chroma_model'):
        result=_dark_chroma(result,profile['dark_chroma_model'])
    return result.astype(values.dtype)

def _dark_chroma(rgb,model):
    """Bounded global color-coordinate correction; never a spatial mask."""
    if model.get('kind')=='paired-shadow-chromatic-v4':
        return _shadow_chromatic(rgb,model)
    # Retain exact evaluation of saved v3 scalar-neutralization recipes.
    from .color_adjust import _to_oklab,_from_oklab
    axis=np.asarray(model['axis'],dtype=rgb.dtype)
    knots=np.asarray(model['gain_knots'])
    fade_low,fade_high=model['linear_Y_fade']
    hue_low,hue_high=model['hue_cosine_window']
    if axis.shape!=(2,) or not np.isfinite(axis).all() or not .99<=np.linalg.norm(axis)<=1.01:
        raise ValueError('Invalid calibrated dark-chroma hue direction')
    if knots.ndim!=2 or knots.shape[1]!=2 or len(knots)<2 or not np.isfinite(knots).all() or np.any(np.diff(knots[:,0])<=0) or np.any(knots[:,0]<0) or np.any(knots[:,0]>1) or np.any(knots[:,1]<.2) or np.any(knots[:,1]>1):
        raise ValueError('Invalid bounded dark-chroma gain curve')
    if not 0<=fade_low<fade_high<=.12 or not -1<=hue_low<hue_high<=1:
        raise ValueError('Invalid dark-chroma confidence range')
    lab=_to_oklab(rgb)
    chroma=np.linalg.norm(lab[...,1:],axis=-1)
    direction=lab[...,1:]/np.maximum(chroma[...,None],1e-8)
    agreement=direction@axis
    hue=np.clip((agreement-hue_low)/(hue_high-hue_low),0,1)
    hue=hue*hue*(3-2*hue)
    light=rgb@_LUMA
    fade=np.clip((fade_high-light)/(fade_high-fade_low),0,1)
    fade=fade*fade*(3-2*fade)
    gain=np.interp(light,knots[:,0],knots[:,1])
    factor=1+(gain-1)*hue*fade
    changed=(factor<1.-1e-8)&(rgb.max(axis=-1)!=rgb.min(axis=-1))
    if not changed.any():return rgb
    result=rgb.copy();adjusted=lab[changed].copy();adjusted[...,1:]*=factor[changed,None]
    result[changed]=np.clip(_from_oklab(adjusted),0,1)
    return result

def _same_y_gamut(lab,target_Y,original):
    """Map requested hue/relative chroma into gamut at the original linear Y."""
    from .color_adjust import _from_oklab
    def candidate(values):
        result=_from_oklab(values)
        current=result@_LUMA
        valid=np.isfinite(result).all(axis=-1)&np.isfinite(current)&(current>1e-12)
        scale=np.divide(target_Y,current,out=np.ones_like(target_Y),where=valid)
        result=result*scale[...,None]
        return result,valid
    result,valid=candidate(lab)
    outside=~valid|np.any((result<0)|(result>1),axis=-1)
    if outside.any():
        requested=lab.copy();lo=np.zeros_like(target_Y);hi=np.ones_like(target_Y)
        # Reducing only chroma keeps the requested hue; re-normalizing scalar
        # RGB preserves Y after each trial. Neutral gray is the safe endpoint.
        for _ in range(14):
            middle=(lo+hi)*.5;trial=requested.copy();trial[...,1:]*=middle[...,None]
            rgb,good=candidate(trial)
            good &= np.all((rgb>=0)&(rgb<=1),axis=-1)
            lo=np.where(good,middle,lo);hi=np.where(good,hi,middle)
        requested[...,1:]*=lo[...,None]
        compressed,good=candidate(requested)
        result[outside]=compressed[outside]
        valid[outside]=good[outside]
    result[~valid]=original[~valid]
    return np.clip(result,0,1)


def _shadow_chromatic(rgb,model):
    """Apply one blended matched-reference color correction, preserving Y."""
    from .color_adjust import _to_oklab
    classes=model.get('hue_classes')
    if not isinstance(classes,list) or not 1<=len(classes)<=12:
        raise ValueError('Invalid calibrated shadow hue classes')
    fade_low,fade_high=model['linear_Y_fade']
    chroma_low,chroma_high=model['relative_chroma_gate']
    hue_low,hue_high=model['hue_cosine_window']
    if not 0<=fade_low<fade_high<=.04 or not .025<=chroma_low<chroma_high<=.1 or not -1<=hue_low<hue_high<=1:
        raise ValueError('Invalid shadow color confidence range')
    lab=_to_oklab(rgb);light=rgb@_LUMA
    chroma=np.linalg.norm(lab[...,1:],axis=-1)
    relative=chroma/np.maximum(lab[...,0],.03)
    direction=lab[...,1:]/np.maximum(chroma[...,None],1e-8)
    weight_sum=np.zeros_like(light);log_gain=np.zeros_like(light)
    rotation_real=np.zeros_like(light);rotation_imag=np.zeros_like(light)
    angular_ranges=[]
    for entry in classes:
        axis=np.asarray(entry['source_axis'],dtype=rgb.dtype)
        gains=np.asarray(entry['gain_knots'],dtype=np.float64)
        rotations=np.asarray(entry['rotation_knots'],dtype=np.float64)
        if axis.shape!=(2,) or not np.isfinite(axis).all() or not .99<=np.linalg.norm(axis)<=1.01:
            raise ValueError('Invalid shadow source hue direction')
        if gains.ndim!=2 or gains.shape[1]!=2 or len(gains)<2 or not np.isfinite(gains).all() or np.any(np.diff(gains[:,0])<=0) or np.any(gains[:,0]<0) or np.any(gains[:,0]>1) or np.any(gains[:,1]<.2) or np.any(gains[:,1]>2.5):
            raise ValueError('Invalid bounded shadow chroma gains')
        if rotations.shape!=(len(gains),3) or not np.isfinite(rotations).all() or not np.array_equal(rotations[:,0],gains[:,0]) or not np.allclose(np.linalg.norm(rotations[:,1:],axis=1),1.,atol=1e-6):
            raise ValueError('Invalid bounded shadow hue rotations')
        angles=np.arctan2(rotations[:,2],rotations[:,1])
        if np.any(np.abs(angles)>np.deg2rad(165)) or np.ptp(angles)>np.pi or np.any(np.abs(np.diff(angles))>np.pi/2):
            raise ValueError('Ambiguous calibrated shadow hue rotation')
        for other_axis,other_angles in angular_ranges:
            if axis@other_axis>math.cos(math.radians(70)) and np.ptp(np.r_[angles,other_angles])>np.pi:
                raise ValueError('Overlapping shadow hue rotations cross the angular branch')
        angular_ranges.append((axis,angles))
        weight=np.clip((direction@axis-hue_low)/(hue_high-hue_low),0,1)
        weight=weight*weight*(3-2*weight)
        weight_sum+=weight
        log_gain+=weight*np.interp(light,gains[:,0],np.log(gains[:,1]))
        rotation_real+=weight*np.interp(light,rotations[:,0],rotations[:,1])
        rotation_imag+=weight*np.interp(light,rotations[:,0],rotations[:,2])
    denom=np.maximum(weight_sum,1e-8)
    coherence=np.hypot(rotation_real,rotation_imag)/denom
    strength=np.minimum(weight_sum,1.)
    fade=np.clip((fade_high-light)/(fade_high-fade_low),0,1)
    fade=fade*fade*(3-2*fade)
    colored=np.clip((relative-chroma_low)/(chroma_high-chroma_low),0,1)
    colored=colored*colored*(3-2*colored)
    strength*=fade*colored
    confidence=np.clip((coherence-.8)/.2,0,1)
    strength*=confidence*confidence*(3-2*confidence)
    legacy=model.get('fallback_neutralization')
    result=rgb.copy()
    if legacy:
        neutralized=_dark_chroma(rgb,legacy)
        fallback_strength=fade*colored
        result=rgb+(neutralized-rgb)*fallback_strength[...,None]
        base_Y=result@_LUMA
        gain=np.divide(light,base_Y,out=np.ones_like(light),where=base_Y>1e-12)
        result=np.clip(result*gain[...,None],0,1)
        # Keep the exact input bytes outside supported non-neutral shadows.
        result[fallback_strength==0]=rgb[fallback_strength==0]
    changed=(strength>1e-7)&(light>0)&(light<fade_high)&(rgb.max(axis=-1)!=rgb.min(axis=-1))
    if not changed.any():return result
    # Construct the full supported endpoint first. Partial confidence blends
    # same-Y RGB endpoints; it must not sweep through magenta intermediate
    # hues on a blue-shadow -> warm-brown correction.
    angle=np.arctan2(rotation_imag[changed],rotation_real[changed])
    gain=np.exp(log_gain[changed]/denom[changed])
    adjusted=lab[changed].copy();a=adjusted[:,1].copy();b=adjusted[:,2].copy()
    adjusted[:,1]=(a*np.cos(angle)-b*np.sin(angle))*gain
    adjusted[:,2]=(a*np.sin(angle)+b*np.cos(angle))*gain
    endpoint=_same_y_gamut(adjusted,light[changed],rgb[changed])
    amount=strength[changed,None]
    result[changed]=result[changed]*(1.-amount)+endpoint*amount
    return result


def _population_shadow_class(source,target,light,keep):
    """Weak-colored reference means need vector confidence, not noisy angles."""
    q_source=source[:,1:]/np.maximum(source[:,:1],.03)
    q_target=target[:,1:]/np.maximum(target[:,:1],.03)
    diagnostic={'method':'weak_reference_population_vector','samples':int(keep.sum()),'bins':[]}
    if keep.sum()<48:return None,diagnostic
    if np.median(np.linalg.norm(q_target[keep],axis=1))>.08:return None,diagnostic
    def estimate(values):
        center=np.median(values,axis=0)
        spread=np.maximum(1.4826*np.median(np.abs(values-center),axis=0),.005)
        radius=np.linalg.norm((values-center)/spread,axis=1)
        weights=np.minimum(1.,3./np.maximum(radius,1e-12))
        mean=np.average(values,axis=0,weights=weights)
        variance=np.average((values-mean)**2,axis=0,weights=weights)
        effective=float(weights.sum()**2/np.sum(weights*weights))
        sem=float(np.sqrt(variance.sum()/max(effective,1.)))
        return mean,sem
    nodes=[]
    for low,high in ((0.,.0025),(.0025,.006),(.006,.012)):
        selected=keep&(light>=low)&(light<high)
        count=int(selected.sum());detail={'linear_Y_bin':[low,high],'samples':count}
        diagnostic['bins'].append(detail)
        if count<48:continue
        src=q_source[selected];ref=q_target[selected]
        s,_=estimate(src);t,sem=estimate(ref);magnitude=float(np.linalg.norm(t))
        detail.update(reference_mean_ab_over_L=t.tolist(),reference_mean_magnitude=magnitude,
            reference_vector_standard_error=sem)
        if magnitude<max(.015,3.*sem) or magnitude>.08:
            detail['status']='identity_reference_mean_not_reliably_colored';continue
        stable=True
        # Both interleaved and contiguous splits must independently support
        # the measured weak hue. This does not infer it from the blade color.
        for first,second in ((ref[::2],ref[1::2]),(ref[:count//2],ref[count//2:])):
            a,_=estimate(first);b,_=estimate(second);na=np.linalg.norm(a);nb=np.linalg.norm(b)
            cosine=float(a@b/max(na*nb,1e-12));ratio=float(na/max(nb,1e-12))
            if min(na,nb)<.01 or cosine<math.cos(math.radians(30)) or not .5<=ratio<=2.:
                stable=False;break
        if not stable:
            detail['status']='identity_reference_mean_unstable_across_splits';continue
        gain=magnitude/max(float(np.linalg.norm(s)),1e-12)
        angle=float(np.angle(complex(*t)/complex(*s)))
        if not .2<=gain<=1. or abs(angle)>np.deg2rad(165):
            detail['status']='identity_reference_mean_exceeds_color_bounds';continue
        nodes.append([float(np.median(light[selected])),gain,math.cos(angle),math.sin(angle)])
        detail.update(status='reference_mean_supported',gain=gain,hue_difference_degrees=float(np.degrees(angle)))
    if not nodes:return None,diagnostic
    nodes.sort();angles=np.arctan2(np.asarray(nodes)[:,3],np.asarray(nodes)[:,2])
    if np.ptp(angles)>np.pi or np.any(np.abs(np.diff(angles))>np.pi/2):return None,diagnostic
    axis=np.mean(q_source[keep]/np.maximum(np.linalg.norm(q_source[keep],axis=1,keepdims=True),1e-12),axis=0)
    axis/=np.linalg.norm(axis)
    anchored=[[0.,*nodes[0][1:]],*nodes,[1.,*nodes[-1][1:]]]
    diagnostic['status']='supported_nonzero_weak_reference_mean'
    return {'source_axis':axis.tolist(),'gain_knots':[[n[0],n[1]] for n in anchored],
        'rotation_knots':[[n[0],n[2],n[3]] for n in anchored]},diagnostic


def _learn_dark_chroma(rendered,reference,modeled_Y):
    """Learn matched dark hue differences and relative-chroma gains only.

    Source hue bins stop a red rear petiole and a blue front shadow from
    sharing a guessed correction. Circular paired-difference agreement, native
    sample support and source/reference chroma floors gate each learned class.
    No spatial coordinate, preview pixel or texture is stored in the model.
    """
    from .color_adjust import _to_oklab
    source=_to_oklab(rendered);target=_to_oklab(reference)
    source_C=np.linalg.norm(source[:,1:],axis=1)/np.maximum(source[:,0],.03)
    target_C=np.linalg.norm(target[:,1:],axis=1)/np.maximum(target[:,0],.03)
    source_angle=np.arctan2(source[:,2],source[:,1]);target_angle=np.arctan2(target[:,2],target[:,1])
    delta=np.angle(np.exp(1j*(target_angle-source_angle)))
    ratio=target_C/np.maximum(source_C,1e-8)
    finite=np.isfinite(source).all(axis=1)&np.isfinite(target).all(axis=1)&np.isfinite(modeled_Y)
    evidence=finite&(modeled_Y>.0001)&(modeled_Y<.012)&(source_C>.035)&(target_C>.03)
    evidence&=(reference@_LUMA>.0001)&(source_C<.6)&(target_C<.6)
    population=finite&(modeled_Y>.0001)&(modeled_Y<.012)&(source_C>.065)&(target_C<.15)&(reference@_LUMA>.0001)
    hue_bin=np.floor((source_angle+np.pi/12)%(2*np.pi)/(np.pi/6)).astype(int)
    diagnostic={'matched_chromatic_shadow_samples':int(evidence.sum()),
        'reference_role':'Matched native hue-difference and relative-chroma statistics only',
        'hue_difference_concentration_minimum':.82,'source_relative_chroma_floor':.035,
        'reference_relative_chroma_floor':.03,'gain_bounds':[.2,2.5],'classes':[]}
    classes=[]
    for index in range(12):
        keep=evidence&(hue_bin==index)
        count=int(keep.sum())
        weak,weak_diagnostic=_population_shadow_class(source,target,modeled_Y,population&(hue_bin==index))
        if weak is not None:
            axis=np.asarray(weak['source_axis']);angles=np.arctan2(np.asarray(weak['rotation_knots'])[:,2],np.asarray(weak['rotation_knots'])[:,1])
            if not any(axis@np.asarray(other['source_axis'])>math.cos(math.radians(70)) and
                np.ptp(np.r_[angles,np.arctan2(np.asarray(other['rotation_knots'])[:,2],np.asarray(other['rotation_knots'])[:,1])])>np.pi for other in classes):
                classes.append(weak)
                diagnostic['classes'].append({'source_hue_bin_degrees':index*30,
                    'status':'reference_learned_weak_shadow_color','population_vector_confidence':weak_diagnostic})
                continue
        if count<48:continue
        differences=delta[keep]
        weights=np.minimum(source_C[keep],target_C[keep])
        mean=np.average(np.exp(1j*differences),weights=weights)
        coherence=float(abs(mean))
        entry={'source_hue_bin_degrees':index*30,'initial_samples':count,'paired_hue_difference_concentration':coherence}
        entry['weak_reference_population_check']=weak_diagnostic
        diagnostic['classes'].append(entry)
        # A single hue class can contain a smaller unrelated mold/edge color
        # population. Require a reliable majority circular consensus rather
        # than allowing that minority to veto a coherent matched stem color.
        trials=np.deg2rad(np.arange(-180,180,15))
        scores=[float(weights[np.abs(np.angle(np.exp(1j*(differences-c))))<np.deg2rad(30)].sum()) for c in trials]
        center=float(trials[int(np.argmax(scores))])
        agreement=np.abs(np.angle(np.exp(1j*(delta-center))))<np.deg2rad(30)
        agreed=keep&agreement
        retained_weight=float(np.minimum(source_C[agreed],target_C[agreed]).sum()/max(float(weights.sum()),1e-12))
        entry['majority_circular_consensus_weight_fraction']=retained_weight
        if retained_weight<.6 or agreed.sum()<48:
            entry['status']='identity_uncertain_paired_hue_difference';continue
        paired=np.average(np.exp(1j*delta[agreed]),weights=np.minimum(source_C[agreed],target_C[agreed]))
        center=float(np.angle(paired));coherence=float(abs(paired))
        entry['accepted_hue_difference_concentration']=coherence
        if not math.isfinite(coherence) or coherence<.82 or abs(center)>np.deg2rad(165):
            entry['status']='identity_ambiguous_paired_hue_difference';continue
        keep &= agreement
        if keep.sum()<48:
            entry['status']='identity_insufficient_consistent_samples';continue
        axis=np.average(source[keep,1:]/np.maximum(np.linalg.norm(source[keep,1:],axis=1,keepdims=True),1e-8),axis=0)
        axis/=np.linalg.norm(axis)
        nodes=[];supports=[]
        for low,high in ((0.,.0025),(.0025,.006),(.006,.012)):
            selected=keep&(modeled_Y>=low)&(modeled_Y<high)
            if selected.sum()<24:continue
            paired=np.average(np.exp(1j*delta[selected]),weights=np.minimum(source_C[selected],target_C[selected]))
            if abs(paired)<.82:continue
            x=float(np.median(modeled_Y[selected]));gain=float(np.clip(np.median(ratio[selected]),.2,2.5))
            angle=float(np.angle(paired))
            if abs(angle)>np.deg2rad(165):continue
            nodes.append([x,gain,math.cos(angle),math.sin(angle)])
            supports.append(int(selected.sum()))
        if not nodes:
            entry['status']='identity_insufficient_native_luminance_support';continue
        nodes.sort()
        angles=np.arctan2(np.array(nodes)[:,3],np.array(nodes)[:,2])
        if np.ptp(angles)>np.pi or np.any(np.abs(np.diff(angles))>np.pi/2):
            entry['status']='identity_ambiguous_luminance_rotation';continue
        if any(axis@np.asarray(other['source_axis'])>math.cos(math.radians(70)) and
               np.ptp(np.r_[angles,np.arctan2(np.asarray(other['rotation_knots'])[:,2],np.asarray(other['rotation_knots'])[:,1])])>np.pi for other in classes):
            entry['status']='identity_ambiguous_overlapping_rotation';continue
        anchored=[[0.,*nodes[0][1:]],*nodes,[1.,*nodes[-1][1:]]]
        classes.append({'source_axis':axis.tolist(),
            'gain_knots':[[n[0],n[1]] for n in anchored],
            'rotation_knots':[[n[0],n[2],n[3]] for n in anchored]})
        entry.update(status='reference_learned_shadow_color',accepted_samples=int(keep.sum()),
            source_hue_degrees=float(np.degrees(np.arctan2(axis[1],axis[0]))%360),
            median_hue_difference_degrees=float(np.degrees(center)),bin_support=supports,
            gain_knots=classes[-1]['gain_knots'])
    if not classes:
        legacy,old_diagnostic=_learn_legacy_dark_chroma(rendered,reference,modeled_Y)
        diagnostic['status']='legacy_neutralization_only_no_reliable_paired_shadow_color'
        diagnostic['legacy_calibration']=old_diagnostic
        return legacy,diagnostic
    diagnostic.update(status='reference_learned_shadow_chromatic',
        brightness='Exact original linear Y retained; same-Y hue-preserving gamut compression',
        scope='Learned source hue classes below.012linearY, identity by.02; no spatial/detail transfer')
    legacy,old_diagnostic=_learn_legacy_dark_chroma(rendered,reference,modeled_Y)
    diagnostic['fallback_calibration']=old_diagnostic
    return {'kind':'paired-shadow-chromatic-v4','hue_classes':classes,
        'linear_Y_fade':[.012,.02],'relative_chroma_gate':[.035,.065],
        'fallback_neutralization':legacy,
        'hue_cosine_window':[math.cos(math.radians(35)),math.cos(math.radians(10))]},diagnostic


def _learn_legacy_dark_chroma(rendered,reference,modeled_Y):
    from .color_adjust import _to_oklab
    source_lab=_to_oklab(rendered);target_lab=_to_oklab(reference)
    source_C=np.linalg.norm(source_lab[:,1:],axis=1)/np.maximum(source_lab[:,0],.03)
    target_C=np.linalg.norm(target_lab[:,1:],axis=1)/np.maximum(target_lab[:,0],.03)
    ratio=target_C/np.maximum(source_C,1e-8)
    evidence=(modeled_Y<.02)&(source_C>.025)&(source_C-target_C>.02)&(ratio<.8)
    diagnostic={'excess_chroma_samples':int(evidence.sum()),'reference_role':'Matched native color statistics only'}
    if evidence.sum()<48:
        diagnostic['status']='identity_no_reliable_excess_chroma'
        return None,diagnostic
    vectors=source_lab[evidence,1:]
    units=vectors/np.maximum(np.linalg.norm(vectors,axis=1,keepdims=True),1e-8)
    weights=np.clip((source_C-target_C)[evidence],0,.3)
    mean=np.average(units,axis=0,weights=weights)
    confidence=float(np.linalg.norm(mean));diagnostic['directional_confidence']=confidence
    if not math.isfinite(confidence) or confidence<.65:
        diagnostic['status']='identity_uncertain_excess_chroma_direction'
        diagnostic['warning']='Dark-chroma reference samples have no reliable common hue direction; no chroma correction applied'
        return None,diagnostic
    axis=mean/confidence
    nodes=[];counts=[]
    for low,high in ((0.,.0025),(.0025,.006),(.006,.012),(.012,.02)):
        keep=evidence&(modeled_Y>=low)&(modeled_Y<high)
        if keep.sum()<24:continue
        nodes.append([float(np.median(modeled_Y[keep])),float(np.clip(np.median(ratio[keep]),.2,1.))])
        counts.append(int(keep.sum()))
    if not nodes:
        diagnostic['status']='identity_insufficient_dark_color_bin_support'
        return None,diagnostic
    nodes.sort()
    knots=[[0.,nodes[0][1]],*nodes,[.02,nodes[-1][1]],[.04,1.],[1.,1.]]
    diagnostic.update(status='reference_learned_dark_chroma',bin_support=counts,
        gain_bounds=[.2,1.],scope='Learned excess-color hue direction below.02linearY, identity by.04; no brightness or texture replacement')
    return {'axis':axis.tolist(),'gain_knots':knots,'linear_Y_fade':[.02,.04],
        'hue_cosine_window':[.5,.95]},diagnostic

def _isotonic(values,weights):
    blocks=[]
    for i,(value,weight) in enumerate(zip(values,weights)):
        blocks.append([i,i,float(value),float(weight)])
        while len(blocks)>1 and blocks[-2][2]>blocks[-1][2]:
            b=blocks.pop();a=blocks.pop();total=a[3]+b[3]
            blocks.append([a[0],b[1],(a[2]*a[3]+b[2]*b[3])/total,total])
    result=np.empty(len(values),np.float64)
    for lo,hi,value,_ in blocks:result[lo:hi+1]=value
    return result

def _native_residual(rgba,preview,profile):
    """Fit only a global8-knot luminance residual, including narrow stems."""
    from scipy import ndimage as ndi
    # One NATIVE pixel of erosion protects mixed backing pixels without
    # deleting thin stems as a two-pixel erosion of a512px thumbnail does.
    opaque=ndi.binary_erosion(rgba[:,:,3]>=250,iterations=1)
    stride=max(1,int(math.ceil(math.sqrt(rgba.shape[0]*rgba.shape[1]/1000000))))
    ys,xs=np.nonzero(opaque[::stride,::stride]);ys*=stride;xs*=stride
    colors=rgba[ys,xs,:3].astype(np.float32)/255.
    values=_decode(colors);luma=values@_LUMA
    valid=(colors.max(axis=1)>.01)&(colors.max(axis=1)<.985)
    ys=ys[valid];xs=xs[valid];values=values[valid];luma=luma[valid]
    # Log-luminance strata, rather than equal-area sampling, retain the dark
    # petiole/vein population even when it occupies much less than1%of a blade.
    edges=np.r_[0.,np.geomspace(.00025,1.,17)]
    selected=[];stratum_counts=[]
    for low,high in zip(edges[:-1],edges[1:]):
        indices=np.flatnonzero((luma>=low)&(luma<high))
        stratum_counts.append(int(len(indices)))
        if len(indices):selected.extend(indices[::max(1,math.ceil(len(indices)/1100))].tolist())
    selected=np.asarray(selected,dtype=np.int64)
    if len(selected)<256:raise ValueError('Insufficient native opaque samples for global DNG tone calibration')
    ys=ys[selected];xs=xs[selected];values=values[selected]
    reference=np.asarray(preview,dtype=np.uint8)
    coords=np.array([(ys+.5)*preview.height/rgba.shape[0]-.5,(xs+.5)*preview.width/rgba.shape[1]-.5])
    sampled=np.stack([ndi.map_coordinates(reference[:,:,c].astype(np.float32),coords,order=1,mode='nearest',prefilter=False) for c in range(3)],axis=1)/255.
    reference_linear=_decode(sampled)
    target=reference_linear@_LUMA
    rendered=_apply_values(values,profile,profile['input_exposure_ev'])
    current=rendered@_LUMA
    # Six supported interior nodes plus fixed normalized black/white anchors.
    # Node positions cover log-lightness, making the lowest bins address black
    # stems separately from midtone leaf color. No node stores spatial data.
    positive=current[current>1e-6]
    lo=max(1e-5,float(np.percentile(positive,1)));hi=min(.8,float(np.percentile(positive,99)))
    centers=np.geomspace(lo,max(lo*1.01,hi),6)
    boundaries=np.r_[0.,np.sqrt(centers[:-1]*centers[1:]),1.00001]
    nodes=[]
    for low,high in zip(boundaries[:-1],boundaries[1:]):
        keep=(current>=low)&(current<high)
        if keep.sum()<24:continue
        x=float(np.median(current[keep]));ratio=float(np.median((target[keep]+1e-6)/(current[keep]+1e-6)))
        y=x*np.clip(ratio,.125,8.)
        nodes.append([x,min(1.,max(0.,float(y))),int(keep.sum())])
    if len(nodes)<3:raise ValueError('Insufficient tonal range for global DNG residual calibration')
    nodes.sort();ys_fit=_isotonic([n[1] for n in nodes],[n[2] for n in nodes])
    knots=[[0.,0.]]+[[n[0],float(v)] for n,v in zip(nodes,ys_fit)]+[[1.,1.]]
    mapped=np.interp(current,*np.asarray(knots).T);mapped=.98*mapped+.02*current
    modeled_gain=np.clip(mapped/np.maximum(current,1e-12),.125,8.)
    modeled_gain=np.minimum(modeled_gain,1./np.maximum(rendered.max(axis=1),1e-12))
    modeled=rendered*modeled_gain[:,None]
    chroma_model,chroma_diagnostic=_learn_dark_chroma(modeled,reference_linear,modeled@_LUMA)
    return knots,{'native_grid_stride':stride,'native_stratified_samples':int(len(selected)),
        'native_luma_stratum_population':stratum_counts,'residual_global_knots':len(knots),
        'residual_gain_bounds':[.125,8.],'residual_strict_slope_identity_fraction':.02,
        'native_preview_sampling':'bilinear full-preview coordinates; global luminance statistics only',
        'native_log_luma_fit_error_ev_before':float(np.median(np.abs(np.log2((current+1e-6)/(target+1e-6)))))},chroma_model,chroma_diagnostic

def apply_profile(linear_srgb,profile):
    """Apply the global metadata recipe to linear-sRGB HxWx3; alpha untouched."""
    if profile is None:return linear_srgb
    ev=float(profile['input_exposure_ev'])
    if not math.isfinite(ev) or not -4<=ev<=8:raise ValueError('DNG profile exposure is out of bounds')
    if not isinstance(linear_srgb,np.ndarray) or linear_srgb.ndim!=3 or linear_srgb.shape[2]!=3 or not np.issubdtype(linear_srgb.dtype,np.floating):raise ValueError('DNG profile requires floating-point HxWx3 RGB')
    result=np.empty_like(linear_srgb)
    for row in range(0,linear_srgb.shape[0],128):
        values=linear_srgb[row:row+128]
        if not np.isfinite(values).all() or (values < -2e-6).any() or (values > 1.+2e-6).any():raise ValueError('DNG tone input must be finite normalized linear sRGB')
        result[row:row+128]=_apply_values(np.clip(values,0,1),profile,ev)
    return result

def render_identity(profile):
    """Pixel-affecting parameters only; exclude provenance/calibration logs."""
    if profile is None:return None
    return {'recipe':RECIPE,'tone_curve':profile['tone_curve'],
        'input_exposure_ev':float(profile['input_exposure_ev']),
        'luma_residual_knots':profile.get('luma_residual_knots'),
        'residual_gain_bounds':[.125,8.],
        'residual_strict_slope_identity_fraction':.02,
        'asset_black_protection':'native-toe-anchored-smoothstep-v1',
        'asset_exposure_knees':profile.get('asset_exposure_knees',_asset_knees(profile)),
        'dark_chroma_model':profile.get('dark_chroma_model')}

def _asset_knees(profile):
    nodes=np.asarray(profile.get('luma_residual_knots',[]),np.float64)
    if len(nodes)>=5:
        inner=nodes[1:-1,1]
        low=float(inner[min(2,len(inner)-1)])
        high=float(inner[max(0,len(inner)-2)])
    else:low,high=.008,.04
    low=float(np.clip(low,.001,.025));high=float(np.clip(max(high,low+.015),.02,.12))
    return {'low_linear_Y':low,'high_linear_Y':high}

def asset_exposure(rgb,ev,profile=None):
    """Lift asset midtones without re-lifting calibrated DNG black features.

    Non-profiled images and deliberate negative exposure retain the established
    peak-preserving curve. Profiled positive exposure stays anchored through
    the calibrated dark toe, then smoothly gains toward blade midtones. This
    is one global monotonic luminance transform; it transfers no spatial detail.
    """
    if ev==0:return rgb
    gain=2.**ev;peak=rgb.max(axis=-1)
    if profile is None or ev<0:
        return rgb*(gain/(1+(gain-1)*peak))[...,None]
    knees=profile.get('asset_exposure_knees',_asset_knees(profile))
    low=knees['low_linear_Y'];high=knees['high_linear_Y']
    light=rgb@_LUMA
    weight=np.clip((light-low)/(high-low),0,1);weight=weight*weight*(3-2*weight)
    local_gain=1+(gain-1)*weight
    return rgb*(local_gain/(1+(local_gain-1)*peak))[...,None]

def prepare_profile(path,rgba,source_sha256=None):
    """Calibrate global profile tone/color from the corresponding preview.

    Call AFTER automatic extraction, before crop/resize. rgba must retain its
    original oriented photo dimensions. Global exposure uses a512px-long
    preview and at most12000 interior samples; the global luminance residual
    uses at most18700 native opaque samples stratified by log luminance. The
    full preview is read only to sample matching native coordinates. Unsupported
    geometry refuses calibration rather than comparing a rotated/cropped image.
    """
    profile=read_profile(path)
    if profile is None:return None
    if source_sha256 is None:
        hasher=hashlib.sha256()
        with Path(path).open('rb') as stream:
            while chunk:=stream.read(1024*1024):hasher.update(chunk)
        source_sha256=hasher.hexdigest()
    profile['source_sha256']=source_sha256
    source=Image.fromarray(rgba)
    source.thumbnail((512,512),Image.Resampling.BOX)
    small=np.array(source)
    with Image.open(path) as im:
        # Pillow's TIFF reader applies orientation as it loads, and removes the
        # orientation from the converted image. A second exif_transpose rotates
        # this specific TIFF preview twice. Do not apply that second transform.
        icc=im.info.get('icc_profile');preview=im.convert('RGB')
        if abs(preview.width/preview.height-rgba.shape[1]/rgba.shape[0])>.005:
            raise ValueError('DNG preview aspect/orientation does not match developed RAW; no color calibration')
        if icc:
            preview=ImageCms.profileToProfile(preview,ImageCms.ImageCmsProfile(io.BytesIO(icc)),ImageCms.createProfile('sRGB'),outputMode='RGB')
            reference_color='ICC-converted sRGB preview'
        else:reference_color='Untagged embedded RGB preview assumed sRGB; appearance reference only'
        full_preview=preview
        preview=preview.resize(source.size,Image.Resampling.BOX)
        reference=np.asarray(preview,dtype=np.float32)/255.
    rgb=np.asarray(small[:,:,:3],dtype=np.float32)/255.
    from scipy import ndimage as ndi
    interior=ndi.binary_erosion(small[:,:,3]>=250,iterations=2)
    mask=interior & (rgb.max(axis=2)<.94) & (rgb.min(axis=2)>.015)
    positions=np.flatnonzero(mask)
    if len(positions)<256:raise ValueError('Insufficient aligned opaque subject for DNG profile exposure calibration')
    positions=positions[::max(1,math.ceil(len(positions)/12000))]
    values=_decode(rgb.reshape(-1,3)[positions]);target=_decode(reference.reshape(-1,3)[positions])
    target_luma=target@_LUMA
    raw_log=np.log2(values@_LUMA+.001);ref_log=np.log2(target_luma+.001)
    correlation=float(np.corrcoef(raw_log,ref_log)[0,1]) if min(raw_log.std(),ref_log.std())>.03 else None
    if correlation is not None and (not math.isfinite(correlation) or correlation<.5):
        raise ValueError('DNG preview and developed RAW do not align on subject luminance; refusing tone calibration')
    def error(ev):
        out=_apply_values(values,profile,ev)
        return float(np.median(np.abs(np.log2((out@_LUMA+.001)/(target_luma+.001)))))
    # Locate a broad minimum, then use a bounded deterministic golden search.
    grid=np.linspace(-2.,5.,57);loss=np.array([error(ev) for ev in grid]);i=int(np.argmin(loss))
    lo=grid[max(0,i-1)];hi=grid[min(len(grid)-1,i+1)]
    for _ in range(20):
        left=lo+(hi-lo)/3;right=hi-(hi-lo)/3
        if error(left)<=error(right):hi=right
        else:lo=left
    exposure=round(float((lo+hi)/2),5)
    if error(exposure)>1.:
        raise ValueError('DNG preview cannot be matched by a global profile exposure; refusing misleading color calibration')
    profile.update(input_exposure_ev=exposure,calibration_offset_from_baseline_ev=round(exposure-profile['baseline_exposure_ev'],5),
        calibration_samples=len(values),calibration_median_luma_error_ev=round(error(exposure),5),
        calibration_alignment_luma_correlation=correlation,
        preview_role='Global exposure/tone/dark-chroma statistics only; no preview pixels or spatial detail enter output',
        preview_color=reference_color,preview_sample_size=list(source.size),
        preview_sha256=hashlib.sha256(reference.tobytes()).hexdigest())
    knots,diagnostic,chroma_model,chroma_diagnostic=_native_residual(rgba,full_preview,profile)
    profile['luma_residual_knots']=knots
    profile['native_luma_calibration']=diagnostic
    profile['asset_exposure_knees']=_asset_knees(profile)
    profile['dark_chroma_model']=chroma_model
    profile['dark_chroma_calibration']=chroma_diagnostic
    if chroma_diagnostic.get('warning'):profile.setdefault('warnings',[]).append(chroma_diagnostic['warning'])
    return profile
