# Desktop app: scan masks and image cutouts

Download the portable Windows x64 or Apple Silicon Mac archive from
[Releases](https://github.com/gnomecannon/cutout-prep/releases). Extract the complete
archive. Open `Cutout Prep.exe` on Windows, or copy `Cutout Prep.app` to Applications
on macOS. The app includes its Python runtime and local model; no Python setup,
GPU, account or photo upload is required. Mac builds are local ad-hoc builds,
without Apple notarization. Intel Macs have not been validated.

## Scan masks

1. Choose **Load photo folder** in **Photos for 3D scanning**.
2. Draw a box around the object or surface on the first useful photo.
3. Choose **Process photos**. Ready photos and masks save automatically.
4. Inspect the silhouettes. **Review photos** finds flagged views. Use **Adjust
   this selection** for keep/remove clicks and a preview; use **Use this photo’s
   result** only when its outline is correct. That also updates saved results.
5. Choose **Show results folder** and import that folder into RealityScan.
   Each unchanged source photo has a matching `<photo.ext>.mask.png`.

Saved work is created in a new sibling folder named `<photo folder> - Scan Masks`;
repeated loads receive a numbered folder and preserve previous batches. If that
location is not writable, the app asks where to save. **More options → Load folder
and choose save location** overrides it. **Open saved work** reopens an existing
`Scan Project.json` instead of starting another batch.

For a cliff that continues outside the photograph, use **More options → Mask
settings → Subject continues beyond photo edges**. Additional display choices,
outline adjustments and **Process again from this photo** are in More options.
**For the next photo group → Keep scene; remove selected area** changes the
workflow for a newly loaded group; existing masks keep their original meaning.

Original photo framing, bytes, EXIF orientation and source pixel dimensions are
preserved. Masks are mapped back to the original pixel orientation. Do not crop,
center or square-pad scan photographs using the image-cutout workflow.

Projects contain local source paths and are intended to remain private. Save and
reopen the project to continue; closing the app releases its project lock. Do
not share your project folder or diagnostic logs without checking their contents.

An image-edge/framing warning affects that view. Uncertain tracking identity
still holds following views until a new anchor or approval; it is not silently
treated as recovered. An automatic Ready label is not a guarantee of a correct
silhouette. Thin objects, overlapping supports, wires and busy backgrounds can
require correction. This utility does not reconstruct missing surfaces, repair
meshes, remove reflections, or recover measured albedo/roughness.

## Leaf and image cutouts

The second tab uses the existing Cutout Prep image processor. It crops, centers,
resizes and prepares color/alpha for game assets. Choose **Load photo folder**,
then **Process cutouts**. A fresh `<photo folder> - Cutouts` folder is created
automatically. Use **Show cutout results** to inspect the preview and report.
Image size (4096 pixels by default) and a save-folder override are in **More options**. Existing
manually changed exports remain protected. See [USAGE.md](USAGE.md) for recipes.

Clear stems are oriented downward and named Front/Back/Rear views are aligned
automatically when their outlines fit well. Saved per-photo geometry takes
priority. Use **More options → Review leaf orientation and front/back pairs**
to choose rotations, assign unlabeled pairs, keep views separate and process
again. Saved choices reload when reopening the existing results folder.
Lighting, automatic orientation and automatic pairing have separate switches
in More options. See [LEAVES.md](LEAVES.md) for limitations and processing cost.

## Build from source

Use Python **3.12 with Tk** and a separate environment. A binary must be built on
its target OS; Windows does not build a native Mac app. On Homebrew, the native
build prerequisites are `python@3.12` and `python-tk@3.12`.

The public Mac package uses an image-only OpenCV build. Upstream Mac wheels also
bundle video encoders that this application does not use. To reproduce the
portable Mac release, rebuild OpenCV after installing the desktop requirements
below (requires Xcode command-line tools).

This takes longer than installing a wheel and uses four CPU build jobs. Its
wheel is built from the pinned OpenCV source, with video I/O disabled, and local
build paths are redacted before packaging. Ordinary portable-app users do not
need this build step.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python tools/download_model.py --output build/models/sam2-tiny
```

On macOS, then replace the upstream OpenCV wheel with the image-only build:

```sh
CUTOUT_BUILD_PYTHON="$PWD/.venv/bin/python" bash tools/build_macos_opencv.sh
```

On Windows use `.venv\Scripts\python` for those commands. Install the matching
CPU PyTorch wheels first from the official index to avoid downloading CUDA:

```powershell
.venv\Scripts\python -m pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu
.venv\Scripts\python -m pip install -r requirements-desktop.txt
```

Source runs require the local model directory to be explicitly selected:

```sh
CUTOUT_PREP_MODEL_DIR="$PWD/build/models/sam2-tiny" .venv/bin/python -m cutout_prep.desktop
```

In PowerShell set `$env:CUTOUT_PREP_MODEL_DIR` to that directory, then run
`.venv\Scripts\python -m cutout_prep.desktop`.

```text
python -m unittest discover -s tests -v
python tools/build_portable.py --dist dist/desktop --work build/desktop --model-dir build/models/sam2-tiny
python tools/check_portable_runtime.py --app "dist/desktop/Cutout Prep/Cutout Prep.exe" --output build/portable-check
```

For the Mac check, use `dist/desktop/Cutout Prep.app/Contents/MacOS/Cutout Prep`
as the executable path. Choose a new check-output directory each time. The check
exercises both the bundled segmentation runtime and the frozen leaf worker.

Dependency/model downloads need internet during setup. Runtime processing stays
offline. The model downloader verifies a fixed revision and every file's hash.
Weights and private scan projects are excluded from Git. Binary redistribution
also requires the sources/notices described in [BINARY_DISTRIBUTION.md](BINARY_DISTRIBUTION.md).
