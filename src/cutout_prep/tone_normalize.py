"""Median-anchored shadow compression for prepared linear-sRGB assets.

This is one global luminance curve. It modifies no alpha, texture placement,
hue or linear RGB channel ratios, and adds no synthetic black-floor value.
"""
import math
import numpy as np

_LUMA = np.array([.2126, .7152, .0722], np.float32)
_GAIN_CAP = 4.


def lift_shadows(linear_rgb, alpha, amount):
    """Return corrected HxWx3 RGB and details for a shadow_lift amount0..1.

    The pivot is the exact median linear luminance of alpha>=192 subject
    pixels. Below that pivot, Y maps to pivot*(Y/pivot)**(1-amount).
    Above it the image stays unchanged. Black remains black, and all gain
    is scalar RGB, limited to4 and the available sRGB gamut. Alpha is read
    only. Amount0 returns the original RGB object without a color round trip.
    """
    if isinstance(amount, (bool, np.bool_)) or not isinstance(amount, (int, float, np.number)):
        raise ValueError('shadow_lift must be a finite number from0 to1')
    if not math.isfinite(float(amount)) or not 0. <= amount <= 1.:
        raise ValueError('shadow_lift must be a finite number from0 to1')
    if not isinstance(linear_rgb, np.ndarray) or linear_rgb.ndim != 3 or linear_rgb.shape[2] != 3:
        raise ValueError('shadow lift requires an HxWx3 linear-sRGB array')
    if not np.issubdtype(linear_rgb.dtype, np.floating):
        raise ValueError('shadow lift requires floating-point linear-sRGB values')
    if not isinstance(alpha, np.ndarray) or alpha.shape != linear_rgb.shape[:2]:
        raise ValueError('shadow lift alpha dimensions must match the RGB image')
    details = {'amount':float(amount), 'exponent':1.-float(amount),
               'gain_cap':_GAIN_CAP, 'pivot_linear_Y':None,
               'curve':'median-anchored lower-half luminance power; upper-half identity',
               'gamut':'scalar gain limited by the maximum RGB channel'}
    if amount == 0.:
        details.update(applied=False, lifted_pixels=0, gamut_limited_pixels=0,
                       maximum_applied_gain=1.)
        return linear_rgb, details
    opaque = alpha >= 192
    if not opaque.any():
        raise ValueError('Shadow lift has no sufficiently opaque subject samples')
    weights = _LUMA.astype(np.float64 if linear_rgb.dtype == np.float64 else np.float32)
    light = linear_rgb @ weights
    selected = light[opaque]
    if not np.isfinite(selected).all() or (selected < 0.).any() or (selected > 1.).any():
        raise ValueError('Shadow lift requires finite normalized linear-sRGB values')
    before = np.percentile(selected, [1,5,25,50,75,95]).tolist()
    pivot = float(np.median(selected, overwrite_input=True))
    del selected
    details.update(pivot_linear_Y=pivot, subject_percentiles=[1,5,25,50,75,95],
                   subject_linear_Y_before=before)
    if pivot <= 0.:
        details.update(applied=False, lifted_pixels=0, gamut_limited_pixels=0,
                       maximum_applied_gain=1., subject_linear_Y_after=before)
        return linear_rgb, details
    result = np.empty_like(linear_rgb)
    lifted = limited = 0
    maximum_gain = 1.
    for row in range(0, linear_rgb.shape[0], 128):
        values = linear_rgb[row:row+128]
        if not np.isfinite(values).all() or (values < 0.).any() or (values > 1.).any():
            raise ValueError('Shadow lift requires finite linear-sRGB values in0..1')
        current = light[row:row+128]
        shadow = (current > 0.) & (current < pivot)
        gain = np.ones_like(current)
        # Apply the gain bound before exponentiation as well, avoiding an
        # overflow for tiny positive floating-point samples at large amounts.
        ratio_floor = _GAIN_CAP**(-1./float(amount))
        gain[shadow] = np.minimum(np.maximum(current[shadow]/pivot,ratio_floor)**(-float(amount)), _GAIN_CAP)
        gain[alpha[row:row+128] == 0] = 1.
        requested = gain.copy()
        peak = values.max(axis=2)
        gain = np.minimum(gain, 1./np.maximum(peak, 1e-12))
        limited += int(np.count_nonzero(gain < requested))
        lifted += int(np.count_nonzero(gain > 1.+1e-7))
        maximum_gain = max(maximum_gain, float(gain.max()))
        result[row:row+128] = np.clip(values*gain[:,:,None], 0., 1.)
        # Reuse the scalar luminance map for exact post-transform statistics.
        current *= gain
    details.update(applied=bool(lifted), lifted_pixels=lifted,
                   gamut_limited_pixels=limited, maximum_applied_gain=maximum_gain,
                   subject_linear_Y_after=np.percentile(light[opaque], [1,5,25,50,75,95]).tolist())
    return result, details
