"""Measured-paper cleanup for fine colorful subjects, with source-backed stems.

This is deliberately separate from solid-object matting: a pale rock glint is
not a hole. No specimen names, coordinates, reference masks or model downloads
are used here. Supplied artwork/masks never enter this route.
"""
from __future__ import annotations

import heapq
import math

import cv2
import numpy as np
from scipy import ndimage as ndi

_NEIGHBORS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]
_EIGHT = np.ones((3,3),bool)


def _components(mask):
    labels, _ = ndi.label(mask, structure=_EIGHT)
    sizes = np.bincount(labels.ravel()); sizes[0] = 0
    return labels, sizes


def _path(start, goals, allowed, costs, max_length):
    """A short path entirely inside photographic foreground evidence."""
    distances = np.full(allowed.shape, np.inf)
    parents = np.full((*allowed.shape, 2), -1, np.int32)
    distances[start] = 0
    pending = [(0., *start)]
    while pending:
        distance, y, x = heapq.heappop(pending)
        if distance != distances[y,x]: continue
        if goals[y,x]:
            result = [(y,x)]
            while result[-1] != start:
                py,px = parents[result[-1]]; result.append((int(py),int(px)))
            return result if len(result) <= max_length else None
        for dy,dx in _NEIGHBORS:
            yy,xx = y+dy,x+dx
            if not (0 <= yy < allowed.shape[0] and 0 <= xx < allowed.shape[1] and allowed[yy,xx]): continue
            step = (costs[y,x]+costs[yy,xx])*.5*(math.sqrt(2) if dy and dx else 1)
            value = distance+step
            if value < distances[yy,xx]:
                distances[yy,xx] = value; parents[yy,xx] = y,x
                heapq.heappush(pending,(value,yy,xx))
    return None


def _recover(alpha, basis, saturation, lightness):
    """Keep genuine separate subjects separate; reconnect only within a source component."""
    recovered = 0; pixels = 0; unresolved = 0
    max_gap = min(64,max(12,round(max(alpha.shape)*.035)))
    repair_limit = max(128,round(np.count_nonzero(alpha)*.02))
    for level, minimum in [(128,10),(220,32),(1,9)]:
        allowed = basis >= level
        source_labels, source_sizes = _components(allowed)
        depth = ndi.distance_transform_edt(allowed)
        costs = 1+3/(depth+.5)+5*np.maximum(0,.45-saturation)+np.maximum(0,lightness-160)/30
        attempted = set()
        for _ in range(48):
            labels,sizes = _components(alpha>=level)
            target = None
            # Each physically separate source subject has its own anchor.
            for source_id in np.argsort(source_sizes)[::-1]:
                if source_sizes[source_id] < minimum: continue
                ids, counts = np.unique(labels[source_labels==source_id],return_counts=True)
                pairs = [(int(i),int(n)) for i,n in zip(ids,counts) if i and sizes[i]>=minimum]
                if len(pairs)<2: continue
                anchor = max(pairs,key=lambda p:p[1])[0]
                for fragment,_n in sorted(pairs,key=lambda p:-p[1]):
                    if fragment==anchor: continue
                    yy,xx = np.where(labels==fragment)
                    key = (level,int(yy.min()),int(xx.min()),int(sizes[fragment]))
                    if key not in attempted:
                        target = (int(source_id),anchor,fragment,key); break
                if target: break
            if target is None: break
            source_id,anchor,fragment,key = target; attempted.add(key)
            main = labels==anchor
            distance,nearest = ndi.distance_transform_edt(~main,return_indices=True)
            cy,cx = np.where(labels==fragment)
            pick = int(np.argmin(distance[cy,cx])); y,x = int(cy[pick]),int(cx[pick])
            if distance[y,x] > max_gap:
                unresolved += 1; continue
            yy,xx = int(nearest[0,y,x]),int(nearest[1,y,x])
            path = None
            for pad in (12,32,64):
                y0=max(0,min(y,yy)-pad); y1=min(alpha.shape[0],max(y,yy)+pad+1)
                x0=max(0,min(x,xx)-pad); x1=min(alpha.shape[1],max(x,xx)+pad+1)
                sl=np.s_[y0:y1,x0:x1]
                path=_path((y-y0,x-x0),main[sl],source_labels[sl]==source_id,costs[sl],max_gap)
                if path is not None: break
            if path is None:
                unresolved += 1; continue
            band=np.zeros((y1-y0,x1-x0),bool)
            for py,px in path: band[py,px]=True
            band=ndi.binary_dilation(band,structure=_EIGHT)&(basis[sl]>0)
            changes=band&(basis[sl]>alpha[sl]); count=int(changes.sum())
            if pixels+count>repair_limit:
                unresolved += 1; continue
            alpha[sl][band]=np.maximum(alpha[sl][band],basis[sl][band])
            pixels += count; recovered += 1
    return alpha, {'stems_recovered':recovered,'stem_pixels_recovered':pixels,
                   'uncertain_connections':unresolved}


def refine(rgb, prior, color, alpha, background_rgb):
    """Return unchanged inputs unless measured paper and colorful fine material qualify."""
    info={'paper_foliage_applied':False}
    h,w=prior.shape
    if min(h,w)<256 or h*w>2048*2048: return color,alpha,info
    values=rgb.astype(np.float32)
    maximum=values.max(2)
    saturation=(maximum-values.min(2))/np.maximum(maximum,1)
    foreground=prior>=.5
    if not foreground.any(): return color,alpha,info
    core=prior>=.95
    if core.sum()<128 or np.mean(saturation[core]>=.4)<.65: return color,alpha,info
    # A sizeable pale area can be a petal or variegated tissue. Leave the
    # existing matte intact rather than deciding from its resemblance to paper.
    _,pale_sizes=_components(core&(saturation<.2))
    if pale_sizes.max(initial=0)>max(128,foreground.sum()*.005): return color,alpha,info
    depth=ndi.distance_transform_edt(foreground)
    if (foreground&(depth<=4)).sum()<foreground.sum()*.20: return color,alpha,info
    edge=max(2,round(min(h,w)*.025)); border=np.zeros((h,w),bool)
    border[:edge]=border[-edge:]=True; border[:,:edge]=border[:,-edge:]=True
    paper=(rgb.min(2)>=210)&(np.ptp(rgb,axis=2)<=16)&(prior<=.01)
    if (paper&border).sum()<border.sum()*.40 or np.max(np.ptp(np.asarray(background_rgb)))>16:
        return color,alpha,info
    threshold=float(np.clip(np.percentile(saturation[core],25)*.70,.20,.34))
    large=cv2.resize(rgb,None,fx=2,fy=2,interpolation=cv2.INTER_LINEAR)
    peak=large.max(2).astype(np.float32)
    sat=(peak-large.min(2))/np.maximum(peak,1)
    lab=cv2.cvtColor(large,cv2.COLOR_RGB2LAB)
    a=lab[:,:,1].astype(np.float32)-128; b=lab[:,:,2].astype(np.float32)-128
    chroma=np.hypot(a,b)
    # Use saturation as well as absolute chroma, so a dark green stem does not
    # disappear merely because it has fewer bright color values.
    colored=(chroma>=8)|((peak<100)&(sat>=threshold))
    loose=ndi.binary_dilation(prior>=.08,iterations=3)
    support=cv2.resize(loose.astype(np.uint8),(w*2,h*2),interpolation=cv2.INTER_NEAREST)>0
    key=colored&(sat>=threshold)&support
    candidate=np.round(cv2.resize(key.astype(np.float32),(w,h),interpolation=cv2.INTER_AREA)*255).astype(np.uint8)
    # Clipped/dark neutral tissue has no reliable saturation. Confirmed dark
    # interiors cannot be mistaken for the measured bright paper merely for
    # having little chroma; preserving them does not reconstruct lost detail.
    dark_tissue=(maximum<40)&(prior>=.95)&(depth>1)
    candidate[dark_tissue]=255
    # Do not blanket-fill pale pockets: the model can be confidently wrong
    # about backing inside a curled leaflet.
    holes=ndi.binary_fill_holes(candidate>=128)&(candidate<128)
    rim=ndi.binary_dilation(holes)&~holes&(saturation<.48)&~dark_tissue
    candidate[rim]=np.minimum(candidate[rim],ndi.minimum_filter(candidate,size=3)[rim])
    weak=((chroma>=6)|((peak<100)&(sat>=.16)))&(sat>=.12)&support
    basis=np.round(cv2.resize(weak.astype(np.float32),(w,h),interpolation=cv2.INTER_AREA)*255).astype(np.uint8)
    basis[dark_tissue]=255
    native_lab=cv2.cvtColor(rgb,cv2.COLOR_RGB2LAB).astype(np.float32)
    candidate,connections=_recover(candidate,basis,saturation,native_lab[:,:,0])
    labels,sizes=_components(candidate>0)
    # Only unconfident isolated crumbs can be discarded. Genuine separate
    # objects stay independent, including when Keep separate objects is enabled.
    for label in np.flatnonzero((sizes>0)&(sizes<=12)):
        island=labels==label
        if np.max(prior[island])<.5: candidate[island]=0
    if (candidate>=128).sum()<foreground.sum()*.65:
        info['paper_foliage_rejected']='The correction would remove too much subject coverage'
        return color,alpha,info
    solid=candidate>=250
    c=np.hypot(native_lab[:,:,1]-128,native_lab[:,:,2]-128)
    anchors=solid&(((c>=34)&(saturation>=.44)&(native_lab[:,:,0]<190))|
                   ((c>=12)&(saturation>=.28)&(native_lab[:,:,0]<155)))
    prepared=rgb.copy()
    if anchors.any():
        distance,nearest=ndi.distance_transform_edt(~anchors,return_indices=True)
        boundary=(candidate>0)&(ndi.distance_transform_edt(solid)<=1.1)&(distance<=20)&~dark_tissue
        prepared[boundary]=rgb[nearest[0][boundary],nearest[1][boundary]]
    else: boundary=np.zeros((h,w),bool)
    _,component_sizes=_components(candidate>=128)
    significant=int((component_sizes>=max(16,candidate.size*.00002)).sum())
    info.update(paper_foliage_applied=True,paper_saturation_cutoff=threshold,
                paper_pocket_rim_pixels=int(rim.sum()),paper_subject_components=significant,
                paper_contour_rgb_pixels=int(boundary.sum()),**connections)
    return prepared,candidate,info
