# Third-party notices and references

The [MIT license](LICENSE) covers this repository's application code, tests,
documentation and procedural example assets, except where a file says otherwise.
It does not replace the licenses of the software used by the application.
The implementation's AI provenance is described in [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## Runtime dependencies

Dependencies are installed as separate Python packages. This source repository
does not vendor their implementations or distribute a bundled Python runtime.
Package wheels can contain additional libraries and notices; retain the notices
shipped with the exact packages when redistributing a binary application.

| Dependency | Main project license | Upstream notices |
| --- | --- | --- |
| Pillow | MIT-CMU; included codecs and libraries have additional notices | [Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| NumPy | BSD-3-Clause; packaged components have additional notices | [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| SciPy | BSD-3-Clause; packaged components have additional notices | [SciPy license](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| OpenCV Python distribution | MIT for the packaging/build scripts; Apache-2.0 for OpenCV itself; binary dependencies have additional notices | [Packaging license](https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt), [third-party notices](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt) |
| rawpy, optional for DNG | MIT | [rawpy license](https://github.com/letmaik/rawpy/blob/main/LICENSE) |
| LibRaw, used by rawpy | See the LGPL-2.1 license bundled by rawpy and its third-party notices | [rawpy's LibRaw license](https://github.com/letmaik/rawpy/blob/main/LICENSE.LibRaw) |

Python and the packages' own dependencies retain their respective licenses.
The current rawpy wheel documentation states that the optional GPL demosaic
packs are not included in its published wheels; custom builds can differ.
Consult the exact distribution's files rather than treating this table as a
complete binary-distribution license inventory.

## Bundled color profile

`src/cutout_prep/sRGB.icc` is a generated built-in sRGB profile. Its embedded
copyright tag states: **"No copyright, use freely"**. The application uses
Pillow's LittleCMS integration for ICC conversion; it does not bundle a separate
LittleCMS implementation.

## Color-science and algorithm references

These references explain equations or algorithms used by this implementation;
the linked software projects remain separately licensed.

- Björn Ottosson, [A perceptual color space for image processing](https://bottosson.github.io/posts/oklab/): OKLab transforms and published matrices.
- W3C, [CSS Color 4 sample color-conversion code](https://www.w3.org/TR/css-color-4/#color-conversion-code): RGB/XYZ and chromatic-adaptation reference matrices.
- Adobe DNG SDK, [reference RGB tone-curve ordering](https://android.googlesource.com/platform/external/dng_sdk.git/+/refs/heads/main/source/dng_reference.cpp): the RGB tone-ordering rule. The SDK is not bundled.
- OpenCV, [GrabCut](https://docs.opencv.org/4.x/d8/d83/tutorial_py_grabcut.html) and [watershed segmentation](https://docs.opencv.org/4.x/d3/db4/tutorial_py_watershed.html): segmentation provided by the external OpenCV package.

The included demonstration images are procedural fixtures, not camera
photographs or third-party artwork. Private development photographs, project
assets and processing reports are not included in this distribution.
