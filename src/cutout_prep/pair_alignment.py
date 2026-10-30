"""Global front/rear registration, without elastic warping or shared-alpha paint.

Matrices are forward source pixel-center -> output pixel-center transforms.
The rear transform includes reflection. RGB is used only by warp_rgba(); fitting
uses alpha, so authored color and retouch cannot steer the registration.
"""
import math
import numpy as np

RECIPE='mirrored-blade-similarity-common-frame-v1'


def _largest(mask,cv2):
    count,labels,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
    if count<2:raise ValueError('Pair image has no opaque subject')
    return labels==(1+int(np.argmax(stats[1:,cv2.CC_STAT_AREA])))


def _centroid(mask):
    y,x=np.nonzero(mask)
    return np.array([x.mean(),y.mean()],np.float64)


def _blade(mask,cv2,ndi):
    radius=max(2,round(max(mask.shape)*.006))
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius*2+1,radius*2+1))
    blade=_largest(cv2.morphologyEx(mask.astype(np.uint8),cv2.MORPH_OPEN,kernel)>0,cv2)
    if blade.sum()<mask.sum()*.65:blade=mask.copy()
    # The largest remote thin appendage is normally the petiole. This is only
    # a geometric cue; uncertain/absent appendages do not become hard anchors.
    dist=ndi.distance_transform_edt(~blade)
    appendage=mask & (dist>radius*1.5)
    anchor=None;confidence=0.
    if appendage.any():
        branch=_largest(appendage,cv2)
        if branch.sum()>mask.sum()*.001:
            near=branch & (dist<dist[branch].min()+2)
            if near.any():
                yi,xi=ndi.distance_transform_edt(~blade,return_distances=False,return_indices=True)
                anchor=np.array([xi[near].mean(),yi[near].mean()])
                confidence=min(1.,float(branch.sum()/max(mask.sum()*.006,1)))
    return blade,anchor,confidence


def _contour(mask,cv2):
    contours,_=cv2.findContours(mask.astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_NONE)
    points=np.concatenate(contours,axis=0)[:,0,:].astype(np.float64)
    return points[::max(1,math.ceil(len(points)/1200))]


def _matrix(theta,scale,cf,cb,dx=0.,dy=0.):
    c,s=math.cos(theta)*scale,math.sin(theta)*scale
    linear=np.array([[c,-s],[s,c]])
    out=np.eye(3);out[:2,:2]=linear;out[:2,2]=cf+np.array([dx,dy])-linear@cb
    return out


def _points(points,matrix):return points@matrix[:2,:2].T+matrix[:2,2]


def _iou(a,b):
    union=np.count_nonzero(a|b)
    return float(np.count_nonzero(a&b)/union) if union else 0.


def _fit(front,back,front_anchor,back_anchor,anchor_weight,cv2,ndi):
    from scipy.optimize import minimize
    cf,cb=_centroid(front),_centroid(back)
    sf=math.sqrt(float(front.sum())/back.sum())
    pf,pb=_contour(front,cv2),_contour(back,cv2)
    ef=front & ~ndi.binary_erosion(front)
    eb=back & ~ndi.binary_erosion(back)
    df=ndi.distance_transform_edt(~ef);db=ndi.distance_transform_edt(~eb)
    penalty=float(max(front.shape))
    def objective(v):
        theta,ls,dx,dy=v;scale=math.exp(ls)
        matrix=_matrix(theta,scale,cf,cb,dx,dy)
        transformed=_points(pb,matrix)
        reverse=_points(pf,np.linalg.inv(matrix))
        d1=ndi.map_coordinates(df,[transformed[:,1],transformed[:,0]],order=1,mode='constant',cval=penalty)
        d2=ndi.map_coordinates(db,[reverse[:,1],reverse[:,0]],order=1,mode='constant',cval=penalty)*scale
        # Smooth symmetric contour error; robust against a few curled lobes.
        score=float((np.sqrt(d1*d1+1).mean()+np.sqrt(d2*d2+1).mean())*.5)
        if front_anchor is not None and back_anchor is not None:
            score+=anchor_weight*float(np.linalg.norm(_points(back_anchor[None],matrix)[0]-front_anchor))
        return score
    angles=np.deg2rad(np.arange(-180,180,10))
    grid=[np.array([a,math.log(sf),0.,0.]) for a in angles]
    scores=[objective(v) for v in grid]
    candidates=[]
    for index in np.argsort(scores)[:3]:
        start=grid[index]
        limit=max(front.shape)*.12
        bounds=[(start[0]-math.radians(14),start[0]+math.radians(14)),
            (math.log(sf*.77),math.log(sf*1.3)),(-limit,limit),(-limit,limit)]
        fit=minimize(objective,start,method='Powell',bounds=bounds,
            options={'maxiter':65,'xtol':1e-4,'ftol':1e-5})
        candidates.append((float(fit.fun),fit.x,bool(fit.success)))
    score,v,converged=min(candidates,key=lambda item:item[0])
    theta,ls,dx,dy=v;matrix=_matrix(theta,math.exp(ls),cf,cb,dx,dy)
    warped=cv2.warpAffine(back.astype(np.uint8),matrix[:2],(front.shape[1],front.shape[0]),flags=cv2.INTER_NEAREST)>0
    transformed=_points(pb,matrix)
    distances=ndi.map_coordinates(df,[transformed[:,1],transformed[:,0]],order=1,mode='constant',cval=penalty)
    reverse=_points(pf,np.linalg.inv(matrix))
    reverse_distances=ndi.map_coordinates(db,[reverse[:,1],reverse[:,0]],order=1,mode='constant',cval=penalty)*math.exp(ls)
    return matrix,{'angle_degrees':float(math.degrees(theta)%360), 'scale':float(math.exp(ls)),
        'blade_iou':_iou(front,warped),
        'contour_distance_p95_work_pixels':float(np.percentile(np.concatenate((distances,reverse_distances)),95)),
        'objective_work_pixels':score,'optimizer_converged':converged}


def _extent(alpha,matrix,cv2):
    contours,_=cv2.findContours((alpha>0).astype(np.uint8),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    if not contours:raise ValueError('Empty pair alpha')
    points=np.concatenate(contours,axis=0)[:,0,:].astype(np.float64)
    points=_points(points,matrix)
    return np.array([points[:,0].min(),points[:,1].min(),points[:,0].max(),points[:,1].max()])


def _common_frame(front_alpha,back_alpha,rear,padding,cv2):
    h,w=front_alpha.shape
    identity=np.eye(3)
    a=_extent(front_alpha,identity,cv2);b=_extent(back_alpha,rear,cv2)
    # Back sampling is one combined warp, with up to four source pixels of
    # Lanczos support. Include that support when planning the common frame.
    back_scale=math.sqrt(abs(np.linalg.det(rear[:2,:2])))
    b+=np.array([-4,-4,4,4])*max(1.,back_scale)
    union=np.array([min(a[0],b[0]),min(a[1],b[1]),max(a[2],b[2]),max(a[3],b[3])])
    lower=np.array([padding,padding],float);upper=np.array([w-1-padding,h-1-padding],float)
    # Prefer a whole-pixel translation if it fits: the front can then retain
    # exact texels. If already framed correctly the front remains unchanged.
    dlo=np.ceil(lower-union[:2]);dhi=np.floor(upper-union[2:])
    if np.all(dlo<=dhi):
        delta=np.minimum(np.maximum(np.zeros(2),dlo),dhi)
        frame=np.eye(3);frame[:2,2]=delta
        mode='front unchanged' if not delta.any() else 'joint integer translation'
    else:
        # A shared shrink preserves both whole silhouettes, including bent
        # petioles, rather than clipping the rear to the front bounding box.
        available=upper-lower-8.
        span=np.maximum(union[2:]-union[:2],1)
        scale=min(1.,float(np.min(available/span)))
        center=(union[:2]+union[2:])*.5
        frame=np.eye(3);frame[:2,:2]*=scale
        frame[:2,2]=np.array([(w-1)*.5,(h-1)*.5])-center*scale
        mode='joint uniform shrink and translation'
    return frame,{'mode':mode,'pre_frame_union_center_bounds':union.tolist(),
        'common_scale':float(frame[0,0]),'requested_padding':padding,
        'resampling_support_included':True}


def estimate_alignment(front_rgba,back_rgba,padding=96,working_long_edge=768,mirror=True):
    """Return a reproducible rear->front similarity and shared-frame plan.

    Inputs are prepared RGBA canvases. The returned front_matrix and back_matrix
    include the common-frame adjustment; back_matrix also includes reflection.
    No image is modified. Natural shape/curvature differences remain measurable.
    """
    import cv2
    from scipy import ndimage as ndi
    cv2.setNumThreads(2)
    for rgba in (front_rgba,back_rgba):
        if not isinstance(rgba,np.ndarray) or rgba.ndim!=3 or rgba.shape[2]!=4 or rgba.dtype!=np.uint8:
            raise ValueError('Pair alignment expects uint8 HxWx4 RGBA canvases')
    if front_rgba.shape[:2]!=back_rgba.shape[:2]:raise ValueError('Prepared pair canvases must share dimensions')
    h,w=front_rgba.shape[:2]
    if not 1<=padding<min(h,w)/2:raise ValueError('Invalid pair padding')
    if not 64<=working_long_edge:raise ValueError('Registration working edge must be at least 64 pixels')
    scale=min(1.,working_long_edge/max(h,w));ww,hh=round(w*scale),round(h*scale)
    sx,sy=ww/w,hh/h
    pre=np.array([[sx,0,(sx-1)*.5],[0,sy,(sy-1)*.5],[0,0,1.]])
    fa=cv2.resize(front_rgba[:,:,3],(ww,hh),interpolation=cv2.INTER_AREA)
    ba=cv2.resize(back_rgba[:,:,3],(ww,hh),interpolation=cv2.INTER_AREA)
    fm=_largest(fa>=128,cv2);bm=_largest(ba>=128,cv2)
    reflect=np.array([[-1.,0,ww-1],[0,1,0],[0,0,1]]) if mirror else np.eye(3)
    if mirror:bm=bm[:,::-1].copy()
    fb,af,cf=_blade(fm,cv2,ndi);bb,ab,cb=_blade(bm,cv2,ndi)
    anchor_weight=.12*min(cf,cb) if af is not None and ab is not None else 0.
    similarity,metrics=_fit(fb,bb,af,ab,anchor_weight,cv2,ndi)
    rear=np.linalg.inv(pre)@similarity@reflect@pre
    frame,frame_info=_common_frame(front_rgba[:,:,3],back_rgba[:,:,3],rear,padding,cv2)
    aligned=cv2.warpAffine(bm.astype(np.uint8),similarity[:2],(ww,hh),flags=cv2.INTER_NEAREST)>0
    metrics.update(before_blade_iou=_iou(fb,bb),before_whole_iou=_iou(fm,bm),
        whole_iou=_iou(fm,aligned),
        contour_distance_p95_output_pixels=metrics['contour_distance_p95_work_pixels']/scale,
        anchor_weight=anchor_weight)
    if af is not None and ab is not None:
        metrics['stem_junction_distance_output_pixels']=float(np.linalg.norm(_points(ab[None],similarity)[0]-af)/scale)
    final_front=frame;final_back=frame@rear
    extents={'front':_extent(front_rgba[:,:,3],final_front,cv2).tolist(),
             'back':_extent(back_rgba[:,:,3],final_back,cv2).tolist()}
    subject_frame={}
    for name,rgba,matrix in [('front',front_rgba,final_front),('back',back_rgba,final_back)]:
        x0,y0,x1,y1=extents[name]
        pads=[x0,y0,w-1-x1,h-1-y1]
        subject_frame[name]={'padding_left_top_right_bottom_pixels':pads,
            'minimum_padding_pixels':min(pads),
            'subject_alpha_area_fraction_estimate':float(np.sum(rgba[:,:,3],dtype=np.float64)/255.*abs(np.linalg.det(matrix[:2,:2]))/(w*h)),
            'subject_wholly_inside_canvas':bool(min(pads)>=0)}
    warnings=[]
    if metrics['blade_iou']<.85:warnings.append('Substantial remaining shape difference; review pair overlay')
    if metrics['contour_distance_p95_output_pixels']>80:warnings.append('Large contour residual; global alignment does not match curled geometry exactly')
    if frame_info['common_scale']<.9:warnings.append('Common frame reduced subject scale to retain both complete silhouettes')
    return {'recipe':RECIPE,'matrix_convention':'forward pixel centers [x,y,1], source to destination; reflection included in back_matrix',
        'output_size':[w,h],'rear_reflected':bool(mirror),'front_matrix':final_front.tolist(),
        'back_matrix':final_back.tolist(),'rear_to_front_matrix':rear.tolist(),
        'common_frame':frame_info,'subject_center_bounds':extents,'subject_frame':subject_frame,'metrics':metrics,
        'warnings':warnings,'working_size':[ww,hh],
        'transform_kind':'global similarity only; no elastic warp or alpha replacement'}


def warp_rgba(rgba,matrix,output_size):
    """One linear-light, premultiplied warp; return uint8 straight-alpha RGBA.

    Identity and integer translation preserve exact source texels. Other
    transforms resample once. Source RGB/alpha are read only.
    """
    import cv2
    from scipy import ndimage as ndi
    cv2.setNumThreads(2)
    matrix=np.asarray(matrix,np.float64)
    if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or not np.allclose(matrix[2],[0,0,1]):raise ValueError('Invalid pair transform')
    w,h=map(int,output_size)
    if w<1 or h<1:raise ValueError('Invalid output dimensions')
    if np.array_equal(matrix[:2,:2],np.eye(2)) and np.allclose(matrix[:2,2],np.round(matrix[:2,2]),atol=1e-10):
        dx,dy=np.round(matrix[:2,2]).astype(int);result=np.zeros((h,w,4),np.uint8)
        x0,y0=max(0,dx),max(0,dy);x1,y1=min(w,dx+rgba.shape[1]),min(h,dy+rgba.shape[0])
        if x1>x0 and y1>y0:result[y0:y1,x0:x1]=rgba[y0-dy:y1-dy,x0-dx:x1-dx]
        return result
    rgb=rgba[:,:,:3].astype(np.float32)/255.
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    alpha=rgba[:,:,3].astype(np.float32)/255.
    a=cv2.warpAffine(alpha,matrix[:2],(w,h),flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    color=np.empty((h,w,3),np.float32)
    for c in range(3):
        channel=cv2.warpAffine(linear[:,:,c]*alpha,matrix[:2],(w,h),flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
        color[:,:,c]=np.clip(channel/np.maximum(a,1e-8),0,1)
    a8=np.rint(np.clip(a,0,1)*255).astype(np.uint8)
    # Discard disconnected ringing, not photographed pieces of the main leaf.
    mask=_largest(a8>0,cv2);a8[~mask]=0
    indices=ndi.distance_transform_edt(a8==0,return_distances=False,return_indices=True)
    missing=a8==0;color[missing]=color[indices[0][missing],indices[1][missing]]
    encoded=np.clip(np.rint(np.where(color<=.0031308,color*12.92,1.055*np.maximum(color,0)**(1/2.4)-.055)*255),0,255).astype(np.uint8)
    return np.dstack((encoded,a8))
