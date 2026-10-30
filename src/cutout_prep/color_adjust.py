"""Perceptual chroma adjustment for bounded linear-sRGB image assets.

This is an editable artistic adjustment, not a measured reflectance recovery or
camera-profile emulation. OKLab lightness and hue stay fixed; chroma increases
only as far as the sRGB gamut permits. Alpha is never accepted or modified.
Transforms follow the author's published linear-sRGB matrices:
https://bottosson.github.io/posts/oklab/
"""
import math
import numpy as np


def _to_oklab(rgb):
    r, g, b = (rgb[..., i] for i in range(3))
    l = np.cbrt(.4122214708*r + .5363325363*g + .0514459929*b)
    m = np.cbrt(.2119034982*r + .6806995451*g + .1073969566*b)
    s = np.cbrt(.0883024619*r + .2817188376*g + .6299787005*b)
    return np.stack((.2104542553*l + .7936177850*m - .0040720468*s,
                    1.9779984951*l - 2.4285922050*m + .4505937099*s,
                    .0259040371*l + .7827717662*m - .8086757660*s), axis=-1)


def _from_oklab(lab):
    light, a, b = (lab[..., i] for i in range(3))
    l = (light + .3963377774*a + .2158037573*b)**3
    m = (light - .1055613458*a - .0638541728*b)**3
    s = (light - .0894841775*a - 1.2914855480*b)**3
    return np.stack((4.0767416621*l - 3.3077115913*m + .2309699292*s,
                    -1.2684380046*l + 2.6097574011*m - .3413193965*s,
                    -.0041960863*l - .7034186147*m + 1.7076147010*s), axis=-1)


def _in_gamut(rgb):
    return np.all((rgb >= 0.) & (rgb <= 1.), axis=-1)


def adjust_saturation(linear_rgb, amount):
    """Scale OKLab chroma by amount0..2, preserving lightness, hue and shape.

    Input is an HxWx3 floating-point linear-sRGB array in0..1. Amount1 returns
    the original array exactly, without a color-space round trip. Other values
    return a new array of the same dtype. Work uses bounded row chunks. Gamut
    compression reduces the requested chroma along the same hue at fixed L;
    it does not clip individual color channels to obtain a stronger effect.
    """
    if isinstance(amount, (bool, np.bool_)) or not isinstance(amount, (int, float, np.integer, np.floating)):
        raise ValueError('saturation must be a finite number from0 to2')
    if not math.isfinite(float(amount)) or not 0. <= amount <= 2.:
        raise ValueError('saturation must be a finite number from0 to2')
    if not isinstance(linear_rgb, np.ndarray) or linear_rgb.ndim != 3 or linear_rgb.shape[2] != 3:
        raise ValueError('saturation requires an HxWx3 linear-sRGB array')
    if not np.issubdtype(linear_rgb.dtype, np.floating):
        raise ValueError('saturation requires floating-point linear-sRGB values')
    if amount == 1.:
        return linear_rgb
    result = np.empty_like(linear_rgb)
    for start in range(0, linear_rgb.shape[0], 128):
        source = linear_rgb[start:start+128]
        if not np.isfinite(source).all() or (source < -2e-6).any() or (source > 1.+2e-6).any():
            raise ValueError('saturation requires finite linear-sRGB values in0..1')
        dtype = np.float64 if source.dtype == np.float64 else np.float32
        values = source.astype(dtype, copy=False)
        if (values < 0.).any() or (values > 1.).any():
            values = np.clip(values, 0., 1.)
        neutral = np.max(values, axis=-1) == np.min(values, axis=-1)
        lab = _to_oklab(values)
        lab[..., 1:] *= amount
        candidate = _from_oklab(lab)
        outside = ~_in_gamut(candidate) & ~neutral
        if outside.any():
            requested = lab[outside]
            low = np.zeros(len(requested), dtype=dtype)
            high = np.ones(len(requested), dtype=dtype)
            for _ in range(14):
                middle = (low+high)*.5
                trial = requested.copy()
                trial[:, 1:] *= middle[:, None]
                inside = _in_gamut(_from_oklab(trial))
                low = np.where(inside, middle, low)
                high = np.where(inside, high, middle)
            compressed = requested.copy()
            compressed[:, 1:] *= low[:, None]
            candidate[outside] = _from_oklab(compressed)
        # Exact achromatic inputs remain exact, including black/white. The
        # final clamp contains only floating-point boundary roundoff after
        # hue-preserving gamut compression, not the requested chroma itself.
        candidate[neutral] = values[neutral]
        result[start:start+128] = np.clip(candidate, 0., 1.)
    return result
