"""Conservative leaf geometry decisions; never replace a photographed outline."""
from __future__ import annotations

import math
from pathlib import Path
import re

import cv2
import numpy as np
from scipy import ndimage as ndi

from . import pair_alignment


def named_pairs(names):
    """Use explicit filename roles, not a guess that similar leaves are a pair."""
    groups = {}
    for name in sorted(names, key=str.casefold):
        stem = Path(name).stem
        roles = list(re.finditer(r'(?<![a-z0-9])(front|back|rear)(?![a-z0-9])', stem, re.I))
        if len(roles) != 1:
            continue
        role = roles[0]
        key = (stem[:role.start()] + '{side}' + stem[role.end():]).casefold()
        side = 'front' if role[0].lower() == 'front' else 'back'
        groups.setdefault(key, {'front': [], 'back': []})[side].append(name)
    pairs, ambiguous = [], []
    for group in groups.values():
        if len(group['front']) == len(group['back']) == 1:
            pairs.append({'front': group['front'][0], 'back': group['back'][0]})
        elif group['front'] and group['back']:
            ambiguous.extend(group['front'] + group['back'])
    return pairs, ambiguous


def stem_direction(alpha):
    """Quarter-turn only a single, long, nearly constant-width appendage.

    This is a geometric cue, not botanical identification or a probability.
    Multiple similar appendages, tapering tips and uncertain angles are retained.
    """
    h, w = alpha.shape
    scale = min(1., 512 / max(h, w))
    mask = cv2.resize(alpha, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA) >= 128
    if not mask.any():
        return {'clockwise_degrees': 0, 'confident': False, 'reason': 'No opaque subject'}
    labels,count=ndi.label(mask,np.ones((3,3)))
    sizes=np.bincount(labels.ravel())[1:]
    if np.count_nonzero(sizes>max(12,mask.sum()*.025))>1:
        return {'clockwise_degrees':0,'confident':False,'reason':'Several separate subjects; photo orientation kept'}
    mask = pair_alignment._largest(mask, cv2)
    radius = max(3, round(max(mask.shape) * .018))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
    blade = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel) > 0
    if blade.sum() < mask.sum() * .65:
        return {'clockwise_degrees': 0, 'confident': False, 'reason': 'No clear broad blade and stem'}
    distance = ndi.distance_transform_edt(~blade)
    labels, count = ndi.label(mask & (distance > radius * 1.5))
    branches = sorted([(int((labels == i).sum()), i) for i in range(1, count + 1)], reverse=True)
    unchanged = {'clockwise_degrees': 0, 'confident': False, 'reason': 'No single clear stem; photo orientation kept'}
    if not branches or branches[0][0] < mask.sum() * .002:
        return unchanged
    if len(branches) > 1 and branches[1][0] > branches[0][0] * .55:
        return {**unchanged, 'reason': 'Several similar tips; photo orientation kept'}
    branch = labels == branches[0][1]
    low, high = float(distance[branch].min()), float(distance[branch].max())
    inside = ndi.distance_transform_edt(mask)
    near = branch & (distance < low + max(2., (high - low) * .2))
    far = branch & (distance > high - max(2., (high - low) * .2))
    near_width = float(np.median(inside[near]))
    far_width = float(np.median(inside[far]))
    if high - low < max(mask.shape) * .05 or high - low < near_width * 4:
        return unchanged
    if near_width > inside.max() * .3 or far_width < near_width * .58:
        return {**unchanged, 'reason': 'Tapering tip is not a reliable stem; photo orientation kept'}
    ny, nx = np.nonzero(near);fy, fx = np.nonzero(far)
    angle = math.degrees(math.atan2(fy.mean() - ny.mean(), fx.mean() - nx.mean()))
    delta = (90 - angle + 180) % 360 - 180
    quarter = round(delta / 90) * 90
    if abs(delta - quarter) > 25:
        return {**unchanged, 'reason': 'Stem direction is between quarter-turns; review orientation'}
    return {'clockwise_degrees': quarter % 360, 'confident': True,
            'reason': 'Clear stem placed downward' if quarter else 'Clear stem already points downward',
            'stem_angle_degrees': round(angle, 2)}


def rotated_frame(alpha, clockwise_degrees, padding):
    """Plan a rotation and shared-safe canvas without clipping fine alpha."""
    if clockwise_degrees % 360 == 0:
        return np.eye(3)
    h, w = alpha.shape
    angle = math.radians(clockwise_degrees)
    c, s = math.cos(angle), math.sin(angle)
    rotation = np.array([[c, -s, 0.], [s, c, 0.], [0., 0., 1.]])
    rotation[:2, 2] = np.array([(w-1)/2, (h-1)/2]) - rotation[:2, :2] @ np.array([(w-1)/2, (h-1)/2])
    extent = pair_alignment._extent(alpha, rotation, cv2) + np.array([-5., -5., 5., 5.])
    span = extent[2:] - extent[:2]
    available = np.array([w-1-2*padding, h-1-2*padding])
    scale = min(1., float(np.min(available / np.maximum(span, 1))))
    frame = np.eye(3);frame[:2, :2] *= scale
    frame[:2, 2] = np.array([(w-1)/2, (h-1)/2]) - (extent[:2] + extent[2:]) * .5 * scale
    return frame @ rotation


def alpha_canvas(alpha, matrix):
    """Analysis-only canvas. Final RGB is rendered from the original capture."""
    h, w = alpha.shape
    warped = cv2.warpAffine(alpha, matrix[:2], (w, h), flags=cv2.INTER_NEAREST)
    rgba = np.zeros((h, w, 4), dtype=np.uint8);rgba[:, :, 3] = warped
    return rgba


def normalized_transform(matrix, size):
    pixels_to_uv = np.array([[1/size, 0, .5/size], [0, 1/size, .5/size], [0, 0, 1.]])
    return pixels_to_uv @ matrix @ np.linalg.inv(pixels_to_uv)


def reliable_pair(plan):
    metrics = plan['metrics'];edge = max(plan['output_size'])
    return (metrics['blade_iou'] >= .90 and metrics['whole_iou'] >= .86
            and metrics['contour_distance_p95_output_pixels'] <= edge * .035
            and plan['common_frame']['common_scale'] >= .85)
