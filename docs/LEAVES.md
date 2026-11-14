# Leaf preparation

The desktop leaf tab keeps the normal **Load photo folder → Process cutouts**
workflow. Portable builds use detailed object segmentation and edge refinement;
brightness/shadow preparation uses the established image processor. This is prepared photographic color, not measured
albedo or recovery of clipped detail.

## Automatic geometry

- A single clear stem can trigger a quarter-turn to point it downward. Multiple
  similar tips, tapering points and uncertain directions keep the photo's
  orientation. Camera EXIF/RAW orientation is already applied by the reader.
- Names such as `Oak_Front.jpg` and `Oak_Back.jpg` (or `Rear`) identify possible
  pairs. Unlabeled capture numbers are not matched by guessing specimen identity.
- Rear views are reflected into the front's frame, then fitted with global
  rotation, uniform scale and translation. Each photographed silhouette remains
  independent. No elastic warp, painted replacement alpha or forced hole filling
  makes incompatible views appear identical.
- Weak overlap or large contour differences retain separate views and add review
  flags. Matching filenames and high overlap do not establish specimen identity;
  inspect veins, stems and the actual photographic details.

## Correct orientation and choose pairs

After processing, use **More options → Review leaf orientation and front/back
pairs**. Choose a photo to see its last saved result. Select a quarter-turn or
keep its photographed orientation. For a paired leaf, set the front's direction;
the fitted back follows it. The picture updates after processing again.

For unnamed captures, choose the front and rear photographs and press **Add this
front/back pair**. **Keep selected views separate** disables their automatic
pairing. **Apply choices and process again** saves the choices and regenerates
unmodified owned exports. Hand-edited exports remain protected and are reported
as conflicts. **Close without applying changes** leaves saved choices alone.

Use **More options → Choose a different save folder** to reopen previous results.
The saved choices reload. A fresh Load photo folder action creates a new batch.

## Saved recipes and color

An `image-settings.json` beside the original photos is still read automatically.
**Load saved leaf settings** selects that recipe from another location. The
photo-preparation format has `defaults` and `images`; an old alignment-rebuild
receipt is a different format. Explicit rotations, existing UV layouts and
skipped photos remain authoritative. Skipped views are not reintroduced by
automatic pairing. Explicit manual geometry choices apply in addition to a
saved recipe's framing.

**Balance brightness and shadows** controls the ordinary automatic exposure and
shadow lift defaults. Per-photo recipe settings retain their priority. RAW
white balance and supported capture tone/reference calibration follow the
existing renderer. Earlier hand-retouched source artwork is not automatically
recreated from an untouched capture.

For an already prepared PNG or other artwork, choose **Preserve existing artwork
colors and alpha**. This selects the existing artwork preset: supplied colors,
translucency and separate alpha pieces are retained, and automatic photo cleanup,
lighting and geometry are disabled. Explicit rotation/pair choices can still be
applied. Per-photo recipes remain authoritative.

The detailed method locks confirmed foreground interiors during edge refinement,
so bright glints do not become color-derived holes. Predicted gaps remain open;
there is no blanket hole filling. **Keep separate objects and small pieces** is
enabled by default. Several separate subjects keep their photographed orientation.
Per-photo component choices and supplied alpha/masks retain their priority.

Fine colorful foliage on measured neutral paper also receives cleanup inside
small gaps, including gray or tinted backing. Dark stems use relative color
evidence, with bounded recovery of connections supported by the source. Large
pale tissue regions skip this pass. Check the connection warnings and preview;
the approved fern regression does not establish accuracy on every subject.

**More options → Background removal method → Simple background (older method)**
selects the previous extractor. Its interior protection restores enclosed
tissue when the photograph does not support a paper-colored hole, while retaining
convincing photographed holes. Supplied transparency and masks remain authored
inputs. Real damage, complex overlap and paper that resembles the leaf can still
need correction. See [the detailed 2D pipeline](2D_MASKING.md) for remaining limits.

## Processing and privacy

Geometry analysis uses an additional small-preview pass. Final textures are
rendered from the original capture through a composed native-resolution layout;
preview pixels do not supply the texture. Full-resolution RAW batches can take
minutes on the CPU. Turn off automatic orientation and pairing, with no explicit
rotation/pair choices, for the original one-pass route. Lighting cleanup remains
available in that route. Temporary previews are removed after the batch.

Results include PNG textures, a contact sheet, the processing report and
`LeafPreparation.json` with decisions, metrics and saved choices. Reports contain
local source paths and should be checked before sharing. The photo originals and
existing asset libraries are not edited. 3D-scan mode retains original photo
framing, bytes and exposure; leaf preparation is a separate workflow.

For source integrations:

```python
from cutout_prep.leaf_batch import prepare

prepare("photos", "new-results", size=4096,
        choices={"pairs": [{"front": "IMG_100.jpg", "back": "IMG_101.jpg"}]})
```

The original `cutout-prep` command retains its one-pass behavior. Its low-level
image settings and alignment API remain documented in [USAGE.md](USAGE.md).
