# Desktop app: scan masks and image cutouts

Download the portable Windows x64 or Apple Silicon Mac archive from
[Releases](https://github.com/gnomecannon/cutout-prep/releases). Extract the complete
archive. Open `Cutout Prep.exe` on Windows, or copy `Cutout Prep.app` to Applications
on macOS. The app includes its Python runtime and local model; no Python setup,
GPU, account or photo upload is required. Mac builds are local ad-hoc builds,
without Apple notarization. Intel Macs have not been validated.

## Scan masks

1. Choose photographs or a photo folder, then choose a separate project folder.
2. Draw a box around the object or surface on a starting photo. Preview the mask.
   Add Keep/Remove points when the selection needs correction.
3. For a cliff that continues outside the photograph, enable **Target may continue
   beyond photo edges**. Scene-removal regions may naturally meet the image edge.
4. Process the group. Inspect the silhouettes, especially the flagged views.
   A new selection or an approved view can restart tracking after uncertainty.
5. Export ready/approved photographs. Import the **Prepared Photos** folder into
   RealityScan. Each unchanged source photo has a matching `<photo.ext>.mask.png`.

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
resizes and prepares color/alpha for game assets. Choose an input and a separate
output folder, prepare the batch, then inspect its preview and report. Existing
manually changed exports remain protected. See [USAGE.md](USAGE.md) for recipes.

## Build from source

Use Python **3.12 with Tk** and a separate environment. A binary must be built on
its target OS; Windows does not build a native Mac app. On Homebrew, the native
build prerequisites are `python@3.12` and `python-tk@3.12`.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-desktop.txt
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python tools/download_model.py --output build/models/sam2-tiny
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
```

Dependency/model downloads need internet during setup. Runtime processing stays
offline. The model downloader verifies a fixed revision and every file's hash.
Weights and private scan projects are excluded from Git. Binary redistribution
also requires the sources/notices described in [BINARY_DISTRIBUTION.md](BINARY_DISTRIBUTION.md).
