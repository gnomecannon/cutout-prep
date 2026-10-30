"""Automatic CPU photograph cutouts; no generated colors or manual seed masks.

Border-derived background, graph-cut segmentation and local edge matting.
Best suited to one isolated object photographed on a reasonably plain surface.
"""
import math
import numpy as np


def _largest(mask, cv2):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if count <= 1:
        raise ValueError('Automatic cutout found no distinct subject')
    index = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    return labels == index


def _background(rgb, cv2):
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[-1:1:complex(h), -1:1:complex(w)]
    design = np.stack((np.ones_like(xx), xx, yy, xx*yy, xx*xx, yy*yy), axis=2)
    edge = max(3, round(min(h, w)*.025))
    border = np.zeros((h, w), bool)
    border[:edge] = border[-edge:] = True
    border[:, :edge] = border[:, -edge:] = True
    samples = design[border][::3]
    colors = rgb[border][::3].astype(np.float64)
    retained = np.ones(len(samples), bool)
    for _ in range(4):
        coefficients = np.linalg.lstsq(samples[retained], colors[retained], rcond=None)[0]
        error = np.linalg.norm(colors-samples@coefficients, axis=1)
        cutoff = max(4., float(np.percentile(error, 85)))
        retained = error <= cutoff
    field = np.clip(design@coefficients, 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    bg_lab = cv2.cvtColor(field, cv2.COLOR_RGB2LAB).astype(np.float32)
    delta = lab-bg_lab
    distance = np.linalg.norm(delta, axis=2)
    noise = float(np.percentile(distance[border], 85))
    value = rgb.astype(np.float32)
    paper = field.astype(np.float32)
    shade = np.sum(value*paper, axis=2)/np.maximum(np.sum(paper*paper, axis=2), 1)
    color_residual = np.linalg.norm(value-shade[:, :, None]*paper, axis=2)
    return distance, color_residual, abs(delta[:, :, 0]), noise, bg_lab[:, :, 0]


def _colored_background(rgb, cv2):
    """Use a contrasting saturated backing as automatic watershed markers.
    Smooth illumination changes stay connected to border background, while
    image gradients separate neutral leaf tissue from similarly gray shadows.
    Neutral-background captures keep the existing paper-specific route.
    """
    h, w = rgb.shape[:2]
    edge = max(3, round(min(h, w)*.025))
    border = np.zeros((h, w), bool)
    border[:edge] = border[-edge:] = True
    border[:, :edge] = border[:, -edge:] = True
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    if np.median(hsv[:, :, 1][border]) < 45:
        return None
    value = rgb.astype(np.float32)
    chroma = value/np.maximum(value.sum(axis=2, keepdims=True), 1)
    dominant = np.median(chroma[border], axis=0)
    axis = np.eye(3)[dominant.argmax()] - np.eye(3)[dominant.argmin()]
    score = chroma @ axis
    cutoff = max(.04, float(np.percentile(score[border], 35)))
    background = score > cutoff
    # A neutral sun/shade patch is not a reliable foreground marker. Require
    # chromatic contrast to the backing, then grow across the image gradients.
    foreground = _largest(score < -.08, cv2)
    if foreground.sum() < max(16, h*w*.0003):
        raise ValueError('Colored backing has insufficient subject color contrast')
    markers = np.zeros((h, w), np.int32)
    markers[background] = 1
    markers[foreground] = 2
    markers[:3] = markers[-3:] = 1
    markers[:, :3] = markers[:, -3:] = 1
    blurred = cv2.GaussianBlur(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), (5, 5), 0)
    cv2.watershed(blurred, markers)
    initial = _largest(markers == 2, cv2)
    from scipy import ndimage as ndi
    interior = ndi.binary_erosion(initial, iterations=16)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    texture = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray.astype(np.float32), cv2.CV_32F)), (0,0), 1)
    texture_limit = max(3., float(np.median(texture[border]))*1.5)
    local_backing = (score > .04) & (ndi.distance_transform_edt(initial) < 6) & (texture < texture_limit)
    extra_backing = np.zeros((h,w), bool)
    blue = score > .04
    if (initial & blue).sum() < initial.sum()*.05:
        # On a chromatically distinct subject, an attached backing-colored
        # shoulder may sit deeper than the contour strip beside a petiole.
        # Reject only smooth backing connected to the exterior, preserving
        # genuine dark tips and any enclosed color variation in the blade.
        smooth = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(21,21)))
        dark_tip = smooth.astype(np.int16)-gray.astype(np.int16) > 32
        connected = ndi.binary_propagation(blue & ~initial, mask=blue)
        extra_backing = connected & ~dark_tip & (texture < texture_limit)
        # Near-neutral paper can be enclosed at the attachment of a long
        # thin petiole. Locate that junction from the silhouette itself; the
        # weaker hue test must never spread over unrelated gray blade/tips.
        weak = score > -.02
        if (initial & weak).sum() < initial.sum()*.05:
            disk = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(25,25))
            broad = cv2.morphologyEx(initial.astype(np.uint8),cv2.MORPH_OPEN,disk).astype(bool)
            appendage = initial & ~cv2.dilate(broad.astype(np.uint8),disk).astype(bool)
            if broad.any() and appendage.any():
                branch = _largest(appendage,cv2)
                if branch.sum() > initial.sum()*.002:
                    to_body = ndi.distance_transform_edt(~broad)
                    near = branch & (to_body < to_body[branch].min()+2)
                    jy,jx = np.argwhere(near).mean(axis=0)
                    yy,xx = np.ogrid[:h,:w]
                    junction = (xx-jx)**2+(yy-jy)**2 < (max(h,w)*.05)**2
                    protected_joint = ndi.binary_dilation(foreground,iterations=3)
                    smooth_backing = (score > -.08) & junction & ~dark_tip & (texture < texture_limit) & ~protected_joint
                    extra_backing |= ndi.binary_propagation(extra_backing & smooth_backing,mask=smooth_backing)
        local_backing |= extra_backing
    # The broad blade is already separated. In its uncertain contour band,
    # a weaker backing-color cue rejects attached paper shoulders without
    # classifying reflected-blue regions deep inside the blade as background.
    markers.fill(0)
    markers[background & ~initial | local_backing] = 1
    markers[(interior & ~extra_backing) | (initial & foreground)] = 2
    markers[:3] = markers[-3:] = 1
    markers[:, :3] = markers[:, -3:] = 1
    cv2.watershed(blurred, markers)
    final = _largest(markers == 2, cv2)
    # Fine photographed bristles can be subpixel mixtures dominated by blue
    # backing. Preserve connected, locally dark narrow features before matting.
    closed = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11,11)))
    dark_line = (closed.astype(np.int16)-gray.astype(np.int16)) > 12
    dark_line &= ndi.binary_dilation(initial, iterations=32)
    dark_line &= ~extra_backing
    final = _largest(final | dark_line, cv2)
    background = local_backing & ~dark_line & ~ndi.binary_erosion(final, iterations=3)
    return final, background, {
        'dominant_backing_channel':'RGB'[dominant.argmax()],
        'opposed_backing_channel':'RGB'[dominant.argmin()],
        'backing_chromaticity_cutoff':round(cutoff, 5)}, (score < -.08) | dark_line, score < -.08, dark_line & (score > .04), (score < -.08) | ((closed.astype(np.int16)-gray.astype(np.int16)) > 32)


def _neutral_support(rgb, strong, distance, residual, noise, cv2, ndi):
    """Connect photographed dark appendages before declaring hard background.

    Color alone is a poor stem detector: dark petioles often have little
    saturation. A local dark-line cue rejects broad, smooth cast shadows and
    grows only from the selected object. No photograph-specific location is
    used, and isolated dust/lines remain disconnected from the selected leaf.
    """
    noise = min(noise, 12.)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    weak_color = (distance > max(12., noise+5)) & (residual > max(6., noise*.7))
    if strong.any():
        body = _largest(strong, cv2)
        body = ndi.binary_propagation(body, mask=body | weak_color)
    else:
        body = _largest(weak_color, cv2)
    body = _largest(body, cv2)
    smooth = cv2.GaussianBlur(gray, (3,3), .55)
    dark = np.zeros(gray.shape, np.float32)
    for width in (9,17,31):
        closed = cv2.morphologyEx(smooth, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(width,width)))
        dark = np.maximum(dark, closed.astype(np.float32)-smooth)
    lines = dark > max(5., noise*.55)
    # A one-pixel connection tolerates antialiasing at the blade/stem junction;
    # return only real line pixels, not the connecting dilation's paper halo.
    bridge = ndi.binary_dilation(lines, iterations=1)
    reachable = ndi.binary_propagation(body, mask=body | bridge)
    recovered = lines & reachable
    support = _largest(body | recovered, cv2)
    # Preserve the connected center of the narrow feature as a foreground cue.
    # The surrounding probable band remains available for image-edge refinement.
    local_peak = ndi.maximum_filter(dark,size=9)
    confident = support & (dark > np.maximum(max(8., noise*.85),local_peak*.60))
    return support, confident, {
        'neutral_connected_line_pixels':int((support & ~body).sum()),
        'neutral_low_chroma_fallback':not bool(strong.any()),
    }


def _exterior_background(binary, ndi):
    """Background connected to the image boundary, excluding enclosed holes."""
    background = ~binary
    seed = np.zeros(binary.shape, bool)
    seed[0] = background[0];seed[-1] = background[-1]
    seed[:,0] = background[:,0];seed[:,-1] = background[:,-1]
    return ndi.binary_propagation(seed, mask=background)


def _protect_interior(rgb, mask, scale, ndi, allowed=None):
    """Restore enclosed tissue unless the source supports a real paper hole.

    A mask's missing pixel is not itself proof of background. Check enclosed
    components against measured exterior paper; a genuine photographed hole
    retains convincing paper color/brightness. Low-contrast gray tissue stays
    opaque with its original RGB. An allowed mask restricts the later matting
    guard to material already confirmed by segmentation, preserving real gaps.
    """
    exterior = _exterior_background(mask,ndi)
    holes = ~mask & ~exterior
    protected = np.zeros(mask.shape,bool)
    if not holes.any():return protected,0
    safe = exterior & ~ndi.binary_dilation(mask,iterations=max(2,round(1/scale)))
    if not safe.any():return protected,0
    at = ndi.distance_transform_edt(~safe,return_distances=False,return_indices=True)
    value = rgb.astype(np.float32)
    paper = value[at[0],at[1]]
    value_sum = value.sum(axis=2);paper_sum = paper.sum(axis=2)
    chroma = value/np.maximum(value_sum[:,:,None],1)
    paper_chroma = paper/np.maximum(paper_sum[:,:,None],1)
    paper_like = (np.linalg.norm(chroma-paper_chroma,axis=2)<.025) & (value_sum/np.maximum(paper_sum,1)>.65)
    labels,count = ndi.label(holes)
    actual_holes = 0
    for index,box in enumerate(ndi.find_objects(labels),1):
        if box is None:continue
        region = labels[box]==index
        if allowed is not None and not np.all(allowed[box][region]):continue
        if np.mean(paper_like[box][region])>=.8:
            actual_holes += 1
            continue
        protected[box] |= region
    return protected,actual_holes


def _neutral_backing_wedges(rgb, binary, scale, cv2, ndi):
    """Reopen photographed backing that coarse foreground enclosed at teeth.

    A hard coarse foreground label is not color evidence. In particular, the
    paper between a bristle and blade may lie inside an eroded coarse mask.
    Compare its illumination-independent chromaticity with nearby exterior
    paper, and remove only bright paper-like pixels reachable from outside.
    Dark stem centers and chromatic gray/brown tissue do not satisfy that test.
    The operation changes coverage; painting the backing brown would leave the
    wrong silhouette and conceal the segmentation failure.
    """
    margin = max(2,round(1/scale))
    exterior = _exterior_background(binary,ndi)
    outside = exterior & ~ndi.binary_dilation(binary, iterations=margin)
    if not outside.any():
        return binary,0
    at = ndi.distance_transform_edt(~outside,return_distances=False,return_indices=True)
    value = rgb.astype(np.float32)
    paper = value[at[0],at[1]]
    value_sum = value.sum(axis=2)
    paper_sum = paper.sum(axis=2)
    chroma = value/np.maximum(value_sum[:,:,None],1)
    paper_chroma = paper/np.maximum(paper_sum[:,:,None],1)
    delta = np.linalg.norm(chroma-paper_chroma,axis=2)
    ratio = value_sum/np.maximum(paper_sum,1)
    # Interior holes are neither flood seeds nor exterior-distance origins.
    # Otherwise a tiny segmentation miss grows across intact gray tissue.
    depth = ndi.distance_transform_edt(~exterior)
    strip = depth < max(20,round(6/scale))
    paper_like = strip & (delta < .025) & (ratio > .72)
    reached = ndi.binary_propagation(exterior,mask=~binary | paper_like)
    removed = binary & reached
    if not removed.any():
        return binary,0
    result = _largest(binary & ~removed,cv2)
    return result,int((binary & ~result).sum())


def extract(rgba):
    """Return RGBA + evidence. Existing transparency should bypass this call."""
    try:
        import cv2
        from scipy import ndimage as ndi
    except ImportError as exc:
        raise ValueError('Automatic cutouts require the configured CPU OpenCV/SciPy runtime') from exc
    cv2.setNumThreads(2)
    cv2.setRNGSeed(19)
    rgb = rgba[:, :, :3]
    h, w = rgb.shape[:2]
    scale = min(1., 1400/max(h, w))
    small = cv2.resize(rgb, (max(2, round(w*scale)), max(2, round(h*scale))), interpolation=cv2.INTER_AREA)
    distance, color_residual, lightness, noise, paper_lightness = _background(small, cv2)
    cutoff = max(20., noise+10)
    saturation = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)[:, :, 1]
    # Neutral cast shadows can differ strongly from a fitted paper surface.
    # They must not become certain foreground merely from that difference.
    strong = (distance > cutoff) & (((saturation > max(50., noise+30)) & (color_residual > 16)) | (lightness > max(100., noise+75)))
    original_strong = strong.copy()
    colored = _colored_background(small, cv2)
    neutral_detail = None
    neutral_evidence = {}
    if colored is not None:
        strong = colored[0]
    else:
        strong, neutral_detail, neutral_evidence = _neutral_support(
            small,strong,distance,color_residual,noise,cv2,ndi)
    seed = _largest(strong, cv2)
    if seed.sum() < max(16, small.shape[0]*small.shape[1]*.0003):
        raise ValueError('Automatic cutout found insufficient foreground contrast')
    filled = ndi.binary_fill_holes(seed)
    likely = ndi.binary_dilation(filled, iterations=3 if colored is not None else 6)
    # A pale neutral shoulder can be enclosed by a colored petiole and blade.
    # Identify it by paper chromaticity rather than brightness. Apply this only
    # near the support boundary on a light surface, retaining neutral glare in
    # the broad leaf interior and very dark clipped blade pixels.
    support_depth = ndi.distance_transform_edt(filled)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY).astype(np.float32)
    texture = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray, cv2.CV_32F)), (0, 0), 1)
    shadow_bg = (color_residual < 8) & (lightness < 120) & (paper_lightness > 140)
    shadow_bg &= (support_depth < max(12, max(small.shape[:2])*.02)) & (texture < 3)
    if colored is not None:
        # The neutral-paper shadow rule is not valid for colored backing under
        # mixed sun/shade. It can otherwise erase gray-brown leaf lobes.
        shadow_bg[:] = False
    certain = ndi.binary_erosion(seed, iterations=2)
    if colored is None:
        certain |= seed & original_strong & (distance > cutoff*1.8)
        certain |= neutral_detail
    else:
        certain |= seed & colored[3]
    gc = np.where(likely, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
    # Paper-colored holes remain background candidates. Glare that differs from
    # the fitted surface stays probable foreground inside the blade enclosure.
    gc[filled & (distance < max(5., noise+1))] = cv2.GC_PR_BGD
    gc[~likely] = cv2.GC_BGD
    gc[certain] = cv2.GC_FGD
    if colored is not None:
        gc[colored[1]] = cv2.GC_BGD
    if colored is None:
        shadow_bg &= ~ndi.binary_dilation(neutral_detail,iterations=1)
    gc[shadow_bg] = cv2.GC_BGD
    gc[:2] = gc[-2:] = cv2.GC_BGD
    gc[:, :2] = gc[:, -2:] = cv2.GC_BGD
    bg = np.zeros((1, 65), np.float64); fg = np.zeros((1, 65), np.float64)
    cv2.grabCut(cv2.cvtColor(small, cv2.COLOR_RGB2BGR), gc, None, bg, fg, 5, cv2.GC_INIT_WITH_MASK)
    mask = _largest((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), cv2)
    coarse = cv2.resize(mask.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
    radius = max(3, math.ceil(3/scale))
    ys, xs = np.nonzero(coarse)
    margin = max(24, radius*3)
    x0, x1 = max(0, int(xs.min())-margin), min(w, int(xs.max())+margin+1)
    y0, y1 = max(0, int(ys.min())-margin), min(h, int(ys.max())+margin+1)
    crop = rgb[y0:y1, x0:x1]
    initial = coarse[y0:y1, x0:x1]
    inside = ndi.binary_erosion(initial, iterations=radius)
    outside = ~ndi.binary_dilation(initial, iterations=radius)
    fine_gc = np.where(initial, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
    fine_gc[inside] = cv2.GC_FGD; fine_gc[outside] = cv2.GC_BGD
    native_detail = None
    if colored is None:
        detail_full = cv2.resize(neutral_detail.astype(np.uint8), (w,h), interpolation=cv2.INTER_NEAREST).astype(bool)
        # Nearest-neighbor enlargement of a coarse line is a search band,
        # never a hard foreground mask. At high capture resolutions that
        # band can be wider than the actual petiole. Recheck dark contrast
        # at native resolution before protecting only its measured center.
        native_gray = cv2.cvtColor(crop,cv2.COLOR_RGB2GRAY)
        diameter = max(3,round(17/scale)) | 1
        closed = cv2.morphologyEx(native_gray,cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_RECT,(diameter,diameter)))
        contrast = closed.astype(np.int16)-native_gray.astype(np.int16)
        diameter = max(3,round(9/scale)) | 1
        local_peak = cv2.dilate(contrast,cv2.getStructuringElement(cv2.MORPH_RECT,(diameter,diameter)))
        native_detail = detail_full[y0:y1,x0:x1] & (contrast > np.maximum(max(8.,min(noise,12.)*.85),local_peak*.6))
        fine_gc[initial & native_detail] = cv2.GC_FGD
    if colored is not None:
        backing_full = cv2.resize(colored[1].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
        fine_gc[backing_full[y0:y1, x0:x1]] = cv2.GC_BGD
        detail_full = cv2.resize(colored[4].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
        fine_gc[initial & detail_full[y0:y1, x0:x1]] = cv2.GC_FGD
    shadow_full = cv2.resize(shadow_bg.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
    fine_gc[shadow_full[y0:y1, x0:x1]] = cv2.GC_BGD
    cv2.setRNGSeed(19)
    bg.fill(0); fg.fill(0)
    cv2.grabCut(cv2.cvtColor(crop, cv2.COLOR_RGB2BGR), fine_gc, None, bg, fg, 3, cv2.GC_INIT_WITH_MASK)
    binary = _largest((fine_gc == cv2.GC_FGD) | (fine_gc == cv2.GC_PR_FGD), cv2)
    protected_interior = np.zeros(binary.shape,bool)
    if colored is None and not neutral_evidence['neutral_low_chroma_fallback']:
        protected_interior,actual_holes = _protect_interior(crop,binary,scale,ndi)
        binary |= protected_interior
        neutral_evidence.update(interior_segmentation_pixels_protected=int(protected_interior.sum()),
            photographed_paper_holes_preserved=actual_holes)
    if colored is None and not neutral_evidence['neutral_low_chroma_fallback']:
        binary,removed = _neutral_backing_wedges(crop,binary,scale,cv2,ndi)
        neutral_evidence['neutral_backing_wedge_pixels_removed'] = removed
    donor_radius = max(2,round(1/scale))
    core = ndi.binary_erosion(binary, structure=np.ones((3, 3)), iterations=2 if colored is not None else donor_radius)
    if colored is None:core |= protected_interior
    if colored is not None:
        mixed_full = cv2.resize(colored[5].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
        core &= ~mixed_full[y0:y1, x0:x1]
    # A narrow ridge can be measured in the photograph while still mixing
    # strongly with paper. It is segmentation support, not proof of opacity.
    # Neutral foreground color donors must therefore come from an eroded
    # capture-resolution interior. Dark narrow stems are preserved below when
    # their measured color is already at/beyond full foreground coverage.
    outer = ~ndi.binary_dilation(binary, structure=np.ones((3, 3)), iterations=3 if colored is not None else 1)
    if not core.any() or not outer.any():
        raise ValueError('Automatic cutout could not separate a usable subject and background')
    fi = ndi.distance_transform_edt(~core, return_distances=False, return_indices=True)
    bi = ndi.distance_transform_edt(~outer, return_distances=False, return_indices=True)
    value = crop.astype(np.float32)/255
    linear = np.where(value <= .04045, value/12.92, ((value+.055)/1.055)**2.4)
    f = linear[fi[0], fi[1]]; b = linear[bi[0], bi[1]]; delta = f-b
    projection = np.sum((linear-b)*delta, axis=2)/np.maximum(np.sum(delta*delta, axis=2), 1e-6)
    alpha = np.where(core, 1., np.where(outer, 0., np.clip(projection, 0, 1)))
    # Do not erase very narrow petioles/teeth just because their nearest opaque
    # donor lies farther inside a differently colored part of the leaf.
    thin = binary & ~core & (ndi.distance_transform_edt(~core) > 3.5)
    if colored is not None:
        confident_full = cv2.resize(colored[6].astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
        thin &= confident_full[y0:y1, x0:x1]
        alpha[thin] = np.maximum(alpha[thin], .55)
    a8 = np.round(alpha*255).astype(np.uint8)
    if colored is None and not neutral_evidence['neutral_low_chroma_fallback']:
        protected_matte,actual_holes = _protect_interior(crop,a8>=128,scale,ndi,allowed=binary)
        alpha[protected_matte] = 1.;a8[protected_matte] = 255;core[protected_matte] = True
        neutral_evidence.update(interior_matting_pixels_protected=int(protected_matte.sum()))
    projection_repaired = 0
    if colored is not None:
        # Color projection can perforate dark, certainly segmented tissue at
        # a vein/petiole junction. Restore only tiny ENCLOSED coverage holes
        # wholly confirmed by the binary subject; real segmented holes and
        # the exterior matte are never filled.
        holes = ndi.binary_fill_holes(a8 > 128) & (a8 <= 128)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8),8)
        for index in range(1,count):
            if stats[index,cv2.CC_STAT_AREA] > max(16,math.ceil(16/(scale*scale))):continue
            region = labels == index
            if np.all(binary[region]):
                alpha[region] = 1.;a8[region] = 255;core[region] = True
                projection_repaired += int(region.sum())
    retained = _largest(a8 > 0, cv2); a8[~retained] = 0
    edge = (a8 > 0) & ~core
    if colored is None:
        # A dark narrow stem can be darker than its nearest broader donor;
        # projection then reaches full coverage. Preserve its actual RGB.
        # Paper-mixed bristles instead carry fractional coverage and a local
        # uncontaminated foreground color, not opaque gray/white camera pixels.
        untouched = core | (binary & (projection >= .995))
        color_band = (a8 > 0) & ~untouched
        linear[color_band] = f[color_band]
        neutral_evidence.update(neutral_rgb_donor_radius=donor_radius,
            neutral_boundary_color_pixels=int(color_band.sum()))
    else:
        recovered = (linear-(1-alpha[:, :, None])*b)/np.maximum(alpha[:, :, None], 1e-6)
        linear[edge] = np.clip(recovered[edge], 0, 1)
        untouched = core
    if colored is not None:
        # Narrow tips mix strongly with the backing at capture resolution.
        # Remove that edge color using a genuine foreground donor, retaining
        # the edge's darker luminance and never changing opaque blade detail.
        chroma = crop.astype(np.float32)/np.maximum(crop.sum(axis=2, keepdims=True), 1)
        high = 'RGB'.index(colored[2]['dominant_backing_channel'])
        low = 'RGB'.index(colored[2]['opposed_backing_channel'])
        score = chroma[:, :, high]-chroma[:, :, low]
        donors = (a8 >= 240) & (score < -.04)
        spill = edge & (ndi.distance_transform_edt(binary) < 4) & (score > .04)
        if donors.any() and spill.any():
            donor_at = ndi.distance_transform_edt(~donors, return_distances=False, return_indices=True)
            donor = linear[donor_at[0], donor_at[1]]
            weights = np.array([.2126,.7152,.0722],np.float32)
            donor_luma = donor@weights
            edge_luma = linear@weights
            corrected = donor*(np.minimum(edge_luma,donor_luma)/np.maximum(donor_luma,1e-6))[:, :, None]
            linear[spill] = corrected[spill]
    encoded = np.clip(np.round(np.where(linear <= .0031308, linear*12.92, 1.055*np.maximum(linear, 0)**(1/2.4)-.055)*255), 0, 255).astype(np.uint8)
    assert np.array_equal(encoded[untouched], crop[untouched])
    result = rgba.copy(); result[:, :, 3] = 0
    result[y0:y1, x0:x1, :3] = encoded
    result[y0:y1, x0:x1, 3] = a8
    fraction = float((a8 > 128).sum()/(h*w))
    warnings = ['Automatic cutout: inspect the preview before game use']
    if noise > 14: warnings.append('Textured or uneven background: review automatic cutout')
    if fraction < .003 or fraction > .8: warnings.append('Unusual subject coverage: review automatic cutout')
    if x0 == 0 or y0 == 0 or x1 == w or y1 == h: warnings.append('Subject approaches photograph edge: review tips/stem')
    method = 'automatic border-color watershed, GrabCut and full-resolution edge matting' if colored is not None else 'automatic border-model GrabCut and full-resolution edge matting'
    return result, {'method':method,
                    'background_route':'colored border watershed' if colored is not None else 'neutral paper model',
                    **neutral_evidence,
                    'edge_colors_prepared':colored is None,
                    **(colored[2] if colored is not None else {}),
                    'working_long_edge':max(small.shape[:2]), 'background_residual_p85':round(noise, 3),
                    'subject_fraction':round(fraction, 5), 'opaque_core_pixels_preserved':int(untouched.sum()),
                    'enclosed_projection_pixels_preserved':projection_repaired,
                    'review_required':True, 'warnings':warnings}
