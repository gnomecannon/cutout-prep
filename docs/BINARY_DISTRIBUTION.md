# Desktop binary distribution

Application code remains MIT licensed. Dependencies keep their own terms.
The portable releases retain license texts in `licenses/`, the Meta model license
and model card, and a version/hash inventory in `BUILD_INFO.json`.

HEIC reading uses **pi-heif**, a decoder-only distribution. The application does
not package pillow-heif's x265 encoder. HEIF images are decoded locally; exported
photograph copies retain their original bytes.

For macOS, the OpenCV dependency is rebuilt without FFmpeg/video I/O. The public
build recipe and diagnostic-path redaction tool are in `tools/`. This removes
unneeded video encoders from the app and avoids publishing builder home paths.
The OpenCV algorithm source is unmodified; the compilation options and binary
diagnostic-string redactions are recorded in that recipe.

The release includes a companion **CutoutPrep-DependencySources-0.4.1.zip**.
It contains the matching libheif, libde265, LibRaw and FFmpeg sources and relevant
wheel source/build material. Its manifest records source URLs, versions and
SHA-256 digests. This source material is supplied alongside the binaries,
rather than depending on a future written request or expiring download link.

To rebuild or replace a library, use the included upstream source/build files
for the platform and Python version in the application's build inventory. You
can replace the corresponding bundled native library or Python extension, or
run the application source with your rebuilt dependency installed. The app adds
no restriction on modifying those libraries or debugging such modifications.
On macOS, modification may require reapplying a local ad-hoc code signature:

```sh
codesign --force --deep --sign - "Cutout Prep.app"
```

The source build instructions are in [DESKTOP.md](DESKTOP.md). Native dependency
rebuilds beyond the supplied image-only OpenCV recipe, and alternate Intel Mac
configurations, have not been validated by this project. Retain the dependency sources, licenses and notices
when redistributing the portable binaries.
