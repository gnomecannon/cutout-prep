# Third-party notices and references

The [MIT license](LICENSE) covers this repository's application code, tests,
documentation and procedural example assets, except where a file says otherwise.
It does not replace the licenses of the software used by the application.
The implementation's AI provenance is described in [AI_DISCLOSURE.md](AI_DISCLOSURE.md).

## Runtime dependencies

The source tree does not vendor dependency implementations. The optional desktop
release bundles a Python runtime, local model and native libraries. Its
`licenses/` directory retains the included distributions' license and notice
files. `BUILD_INFO.json` records the versions actually packaged. The release's
Dependency Sources archive supplies the matching HEIF, LibRaw and FFmpeg library
sources and relevant wheel-build sources. See [binary redistribution](docs/BINARY_DISTRIBUTION.md).

| Dependency | Main project license | Upstream notices |
| --- | --- | --- |
| Pillow | MIT-CMU; included codecs and libraries have additional notices | [Pillow license](https://github.com/python-pillow/Pillow/blob/main/LICENSE) |
| NumPy | BSD-3-Clause; packaged components have additional notices | [NumPy license](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| SciPy | BSD-3-Clause; packaged components have additional notices | [SciPy license](https://github.com/scipy/scipy/blob/main/LICENSE.txt) |
| OpenCV Python distribution | MIT for the packaging/build scripts; Apache-2.0 for OpenCV itself; binary dependencies have additional notices | [Packaging license](https://github.com/opencv/opencv-python/blob/4.x/LICENSE.txt), [third-party notices](https://github.com/opencv/opencv-python/blob/4.x/LICENSE-3RD-PARTY.txt) |
| rawpy, optional for DNG | MIT | [rawpy license](https://github.com/letmaik/rawpy/blob/main/LICENSE) |
| LibRaw, used by rawpy | See the LGPL-2.1 license bundled by rawpy and its third-party notices | [rawpy's LibRaw license](https://github.com/letmaik/rawpy/blob/main/LICENSE.LibRaw) |
| pi-heif, optional HEIC decoding | BSD-3-Clause wrapper; wheels include LGPL-3.0 libheif/libde265 | [HEIF project](https://github.com/bigcat88/pillow_heif) |
| PyTorch and Torchvision, scan mode | BSD-style licenses and bundled-library notices | [PyTorch](https://github.com/pytorch/pytorch), [Torchvision](https://github.com/pytorch/vision) |
| Transformers and safetensors, scan mode | Apache-2.0 | [Transformers](https://github.com/huggingface/transformers), [safetensors](https://github.com/huggingface/safetensors) |
| SAM 2.1 Hiera Tiny weights | Apache-2.0; Meta copyright retained | [Model card](https://huggingface.co/facebook/sam2.1-hiera-tiny), [license copy](tools/SAM2-LICENSE) |
| Python, Tcl/Tk | PSF and Tcl/Tk licenses | [Python](https://www.python.org/), [Tcl/Tk](https://www.tcl.tk/) |
| PyInstaller bootloader | GPL with the application-distribution exception | [PyInstaller license](https://pyinstaller.org/en/stable/license.html) |

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

Procedural demonstrations are labelled as such. Any public photographic example
has its own source/credit record. Private development photographs, project assets,
local paths and processing reports are excluded from the source and app releases.
