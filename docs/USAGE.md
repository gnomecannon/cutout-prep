# Settings and advanced use

## Command-line options

Run `cutout-prep --help` for the full list. Common options:

```text
cutout-prep "photos" --preset photo
cutout-prep "photos" --output "ReviewExports"
cutout-prep "photos" --recursive
cutout-prep "photos" --update
cutout-prep "artwork" --preset artwork --size 1024 --padding 24
cutout-prep "photos" --exposure none --shadow-lift 0
cutout-prep "photos" --raw-tone neutral
```

`--background keep` retains an opaque rectangular background; square framing
still applies. It does not disable color preparation or component selection.
Use the `artwork` preset when preserving authored color and existing transparency.
Neither preset makes this tool suitable for numeric/data texture channels.

The photo defaults are 4096 pixels square, 96-pixel padding, lift-only automatic
exposure targeting median sRGB luminance 0.25 (capped at 2 EV), `shadow_lift` 0.45,
`saturation` 1, automatic background extraction and `raw_tone` auto.
`shadow_lift: 0` disables shadow compression. `saturation: 1` retains the rendered
chroma; it is not a blanket saturation boost. Positive rotation is counterclockwise.

## Per-folder settings

Place `image-settings.json` beside the input photographs, or pass `--settings`.
Start with [this example](image-settings.example.json) and use actual relative
input filenames. Precedence is photo defaults, selected preset, JSON defaults,
explicit common CLI options, then per-image overrides. Per-image names use `/`
between directories.

```json
{
  "defaults": {"size": 2048, "padding": 48},
  "images": {
    "seed-pod.jpg": {"name": "T_SeedPod_01_BaseColor", "rotation_degrees": 180},
    "reference-only.jpg": {"skip": true}
  }
}
```

An optional supplied grayscale `mask` must match the EXIF-oriented input
dimensions. Masks are never required for the normal workflow. Treat settings as
local instructions you control; a mask path can refer to a local file. Configured
masks, output directories, symlinks and directory junctions are excluded from
recursive input scanning. Only the first frame of an ordinary multi-frame image
is used. Supported ordinary color formats are PNG, JPEG, WebP, TIFF, BMP and TGA.
DNG has a separate RAW route. Numeric high-bit-depth/grayscale inputs are rejected.

## DNG color and precision

The optional rawpy/LibRaw decoder reads the full RAW image with camera white
balance and orientation applied once. It does not substitute the embedded JPEG
for texture detail. Development starts in 16-bit linear sRGB, then uses an exact
sRGB transfer into the existing 8-bit RGBA working pipeline. The original DNG
remains the high-bit-depth master; final exports are ordinary 8-bit sRGB.

A supported DNG tone curve and corresponding opaque camera-preview color samples
can calibrate a bounded global tone/shadow-color recipe. Fitted hue classes and
weak-color population confidence gates preserve supported warm colors while
refusing unreliable corrections. The shadow chromatic step preserves linear
luminance and uses same-luminance gamut compression. Preview samples supply
statistics, not masks, geometry or replacement texture.

This approximates camera appearance; it does not implement every manufacturer's
local HDR pipeline or recover reflectance. Some dark stems remain neutral where
the source/reference color relation is uncertain. `--raw-tone neutral` bypasses
camera-reference calibration, while exposure/shadow controls remain separate.
Unsupported profiles retain neutral rendering with a warning; invalid calibration
produces a per-file error. Compression/camera support depends on LibRaw.

The original workflow included full-resolution portrait and landscape iPhone
linear DNG captures. That history is limited camera coverage. Public automated
tests and synthetic demos do not establish general camera compatibility.

## Front/rear alignment API

The public package retains an advanced API:

```python
import numpy as np
from PIL import Image
from cutout_prep.pair_alignment import estimate_alignment, warp_rgba

front = np.array(Image.open("front.png").convert("RGBA"))
rear = np.array(Image.open("rear.png").convert("RGBA"))
plan = estimate_alignment(front, rear, padding=96)
front_aligned = warp_rgba(front, plan["front_matrix"], plan["output_size"])
rear_aligned = warp_rgba(rear, plan["back_matrix"], plan["output_size"])
```

Use prepared RGBA canvases of equal square size. Back matrices already include
horizontal reflection into front coordinates. The fit emphasizes the broad body
and may downweight a thin appendage as a petiole. This is foliage-oriented global
registration, not universal object correspondence or elastic warping. Inspect
warnings and overlays; natural outlines and curved stems can differ substantially.
The API returns arrays; callers must deliberately save them with the intended
profile/output ownership. Preserve the unaligned color-stage inputs and apply
stored transforms once rather than recursively transforming aligned outputs.

For an advanced native re-render, per-image `uv_transform` accepts a generated
forward 3x3 similarity matrix in normalized square UV coordinates. Pixel centers
are `(pixel + 0.5) / size`. The final row must be `[0, 0, 1]`; the rear reflection
must already be included. The processor composes this with source framing before
the final sample for unrotated source inputs. A nonzero `rotation_degrees` uses
the earlier separate rotation step. Re-estimate registration after changing
source geometry, cutout, rotation or framing. Invalid or clipping transforms fail.
No command automatically discovers matching photographs or proves their identity.

## Managed output and interrupted batches

Keep `ProcessingReport.json` beside its exports. The report records ownership and
hashes; unrelated, malformed or foreign reports are refused. A recognized report
is tool-managed metadata and is rewritten; manual edits to every field are not
detectable or preserved. Reports are trusted local instructions, not authenticated
proof against tampering. Keep manual notes elsewhere. Use an empty output folder when importing
artwork from another tool. `--update` replaces only unchanged managed exports
whose source/settings/runtime recipe changed. A missing source does not retire
its old derivative. Duplicate input pixels/settings can share one output;
different content claiming one name produces an error.

If a forcibly terminated run leaves `.image-preparation.lock`, first verify that
its process has stopped. Then remove that lock deliberately before restarting.
Ordinary completion/errors release the lock. The tool cannot prove that an
arbitrary other program or machine is idle, and the lock is not a distributed
transaction or permission system. Keep normal backups for important work.
