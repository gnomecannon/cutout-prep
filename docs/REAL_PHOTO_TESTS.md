# Real photo and shape review

A rounded green probe can check that model loading, a button, tracking and file
export work. It cannot establish that leaf teeth, holes, thin stems, feathers or
complex backgrounds are handled well. Successful processing, a high model score
and pair overlap are not visual acceptance.

## Repeatable public cases

[The public case manifest](../tools/public_samples.json) pins 18 online originals
with their source pages, authors, licenses, byte counts and source hashes. It
covers pointed/scalloped leaves, a fern, a dry leaf, insect damage, a pine cone,
fine flower petals, pale flowers, feathers, coal, a crystal, a shell, separate
objects, an outdoor leaf, a leaf skeleton and two transparent artwork examples.
Some are deliberately difficult controls, not supported unattended examples.

The photographs are not bundled or relicensed as software. Follow each source's
license before sharing the original or a derivative. The downloader verifies the
pinned original bytes and respects source rate limits. Downloads require a
network connection; ordinary processing and CI tests do not.

From a source checkout with the image dependencies installed:

```sh
python tools/download_public_samples.py --output ../CutoutPrepReview/Samples
python tools/review_leaf_photos.py ../CutoutPrepReview/Samples --cases ../CutoutPrepReview/Samples/photo-cases.json --provenance ../CutoutPrepReview/Samples/Sources.json --output ../CutoutPrepReview/Photos
python tools/review_leaf_photos.py ../CutoutPrepReview/Samples --cases ../CutoutPrepReview/Samples/artwork-cases.json --provenance ../CutoutPrepReview/Samples/Sources.json --output ../CutoutPrepReview/Artwork --artwork
```

Add `--app` with the installed executable path to test that portable app instead
of the source worker. Each run needs a new output folder. Captures are copied
into a separate `Inputs` directory, and original/copy hashes are checked again.
Open `Review.html` for the capture, prepared result and alpha side by side.
Reports include local filenames/paths; review them before sharing.

To try the same groups through the desktop app, load the respective `Inputs`
folder. For the artwork group, select **More options → Preserve existing artwork
colors and alpha**. The normal photo group uses the standard leaf cutout route.

## What to inspect

Record a finding for each case, including failures:

- Does the complete intended subject remain, including fine teeth and stems?
- Are the spaces between branches and genuine damaged holes transparent?
- Is intact discolored tissue retained instead of turned into holes?
- Does backing, contact shadow or overlapping clutter remain?
- Are natural color variation and existing translucent/separate alpha pieces
  preserved in the appropriate mode?
- Are orientation and front/rear identity correct? A matching silhouette alone
  does not prove the same specimen was photographed.

Opaque captures test extraction. Inputs with supplied transparency test alpha
and color preservation; do not count them as successful background removals.
Mask component/hole counts are diagnostic only. There are no independently
annotated ground-truth masks for this public case group, so do not report a
general accuracy percentage from it.

## Automated shape contracts

The offline regression and workflow fixtures include lobed and serrated leaves,
a branching sprig, irregular holes, discolored tissue, narrow stems and an
irregular rock outline. Extraction is checked against known procedural alpha;
rotation must preserve branch connectivity, holes and padding. Packaged leaf
checks verify actual pair output, two retained holes and a connected thin stem.
The native workflow uses consecutive views of one specimen for tracking and a
separate leaf folder for front/rear fitting.

These are still procedural fixtures. The independent real-photo review above is
needed to discover failures that the designed fixtures miss. A private
photographic-texture composite trial already found backing retained between
fine conifer branches, including on a plain background. That case remains a
known extraction limitation; no extraction algorithm change is claimed here.
