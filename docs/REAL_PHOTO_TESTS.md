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
Failed inputs remain visible with their source preview and worker error. Use
`--existing` with the same case list, size and options to refresh the review
without running extraction again. Original/copy and recorded export hashes must
still match; changed exports are not silently treated as the worker's result.

To try the same groups through the desktop app, load the respective `Inputs`
folder. For the artwork group, select **More options â†’ Preserve existing artwork
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

<!-- PUBLIC-BASELINE -->
## Recorded online baseline: November 8, 2026

The Windows portable app v0.3.0 attempted all 18 pinned cases at 1536 pixels on
the CPU. Fifteen were opaque captures. One existing leaf alpha was processed in
normal photo-preparation mode; two supplied-alpha images used artwork
preservation mode. Those three are not background-removal successes.

No per-image mask painting, manual result repair or background replacement was
used for these online cases. All original and copied source hashes remained
unchanged. Three opaque captures produced no output and remain in the report
with their source preview and error. The other 12 opaque captures produced
outputs, including visibly wrong and partial results. A file being produced is
not the quality gate.

The following observations are assistant visual inspection at comparison scale,
not independent human acceptance or a general accuracy percentage. The group
includes multi-object and clutter controls beyond the intended isolated-subject
workflow. No 3D-scan masking or reconstruction conclusion follows from it.

| Source case | Visual finding | Observation |
| --- | --- | --- |
| [01-oak-lobes.jpg](<https://commons.wikimedia.org/wiki/File:Quercus_palustris_leaf_(white_background).jpg>) | Useful at review scale | Deep sinuses, major points and narrow stem retained; low-resolution source limits edge detail. |
| [02-oak-scallops.jpg](<https://commons.wikimedia.org/wiki/File:Quercus_dumosa_leaf_(white_background).jpg>) | Useful at review scale | Captured scalloped/spiny outline and stem retained on white backing; reflective leaf texture kept. Original is tightly framed at the apex, so capture coverage still needs inspection. |
| [03-fern.jpg](<https://commons.wikimedia.org/wiki/File:Fern-leaf-oliv.jpg>) | Wrong/unusable mask | Large areas of white backing remain enclosed between fronds. Successful processing does not establish a usable cutout. |
| [04-dry-leaf.jpg](<https://commons.wikimedia.org/wiki/File:Dried_Leaf.jpg>) | Wrong/unusable mask | Textured/color-shifted backing confused extraction: much leaf tissue removed and a background region retained. |
| [05-insect-damage.jpg](<https://commons.wikimedia.org/wiki/File:Eaten-Leaf-White-Oak-Close-Up_2012-08-02-15.48.47-ZS-PMax_(7700429782).jpg>) | No output | Rejected with Colored backing has insufficient subject color contrast; no mask produced for the densely skeletonized tissue. |
| [06-pine-cone.jpg](<https://commons.wikimedia.org/wiki/File:Pinus_nigra_cone.jpg>) | Needs cleanup | Main cone isolated, but some pale scale ends are eroded and small edge defects remain. |
| [07-aster.jpg](<https://commons.wikimedia.org/wiki/File:Aster_flower_head_(54914780595).jpg>) | Useful at review scale | Overlapping broad yellow petals and concave joins retained on white backing. |
| [08-white-orchid.jpg](<https://commons.wikimedia.org/wiki/File:Phalaenopsis_Cultivar_White_01.jpg>) | Useful at review scale | Main pale flower cluster and bud isolated from purple backing; small stem joins still need close inspection. |
| [09-white-feather.jpg](<https://commons.wikimedia.org/wiki/File:A_single_white_feather_closeup.jpg>) | No output | Rejected for insufficient subject color contrast despite visibly distinct pale feather on dark backing. |
| [10-feather-duster.jpg](<https://commons.wikimedia.org/wiki/File:Ostrich_Feather_Duster_cropped.jpg>) | Needs cleanup | Main duster retained, but fine/translucent strands and gaps collapse toward an opaque silhouette. |
| [11-coal.jpg](<https://commons.wikimedia.org/wiki/File:2011-06-13-Houille.jpg>) | Needs cleanup | Main rock retained, but bright glints become false transparent speckles and some contact shadow/backing remains. |
| [12-amethyst.jpg](<https://commons.wikimedia.org/wiki/File:Amethyst-sample3.jpg>) | No output | Rejected for insufficient subject color contrast; no cutout for the cropped glossy crystal sample. |
| [13-shell.jpg](<https://commons.wikimedia.org/wiki/File:Cepaea_hortensis_-_Shell_09.JPG>) | Needs cleanup | Only one shell view retained from the five-view plate; its right edge has erosion. This is a multi-object control, not an all-subject success. |
| [14-multiple-almonds.jpg](<https://commons.wikimedia.org/wiki/File:Almonds_-_in_shell,_shell_cracked_open,_shelled,_blanched.jpg>) | Unsupported group | Opaque multi-object photo: lower subjects dropped and the two upper subjects remain joined. Current one-subject extraction does not preserve the group. |
| [15-outdoor-leaf.jpg](<https://commons.wikimedia.org/wiki/File:Oak_leaf_P8260005.jpg>) | Wrong/unusable mask | Selected a crossing twig instead of the intended leaf in outdoor clutter. |
| [16-skeleton.png](<https://commons.wikimedia.org/wiki/File:Dried_leaf_skeleton.png>) | Existing alpha retained | Existing leaf alpha retained its main shape and puncture. This supplied-alpha input checks preservation through photo preparation; it does not test new background extraction. |
| [17-flower-alpha.png](<https://commons.wikimedia.org/wiki/File:Trifolium_repens_macro_flower_cutout.png>) | Artwork retained | Artwork mode retained pale flower color variation, thin petals, stem and supplied transparent gaps at review scale. |
| [18-line-art-alpha.png](<https://commons.wikimedia.org/wiki/File:Rose_Flower_(PSF).png>) | Artwork retained | Artwork mode retained black/white line detail, small branches and supplied alpha without applying photographic brightness/shadow changes. |

These cases establish repeatable targets for improvement: backing inside fine
branch gaps, pale edge erosion, glints turned into false holes, and incorrect
selection in textured clutter. The extraction algorithm and installed apps were
not changed by that baseline validation work.

The expanded offline suite passed 69 tests on Windows, macOS and Linux (one
Windows symlink-privilege skip). The revised native Windows workflow and
installed portable topology checks also passed. The latter retained two
irregular holes and a connected stem while fitting a lobed pair. These software
checks remain separate from the real-photo findings above.

## Version 0.4 comparison

The [detailed 2D pipeline](2D_MASKING.md) was developed against these same pinned
originals. The following observations are assistant visual inspection at
comparison scale, not independent human acceptance. No per-image painted masks
or manual result repairs were used. The three supplied-alpha cases remain
preservation checks and must not be counted as extraction successes.

Both native Windows x64 and Apple Silicon Mac portable apps processed all 18
cases at 1536 output pixels, including all 15 opaque captures. Original and
copied source hashes were unchanged. All inferred cutouts retain review flags.
Producing 18 files does not mean every silhouette is production-ready.

| Cases | Observed change and remaining limit |
| --- | --- |
| 01, 02, 07 | Broad leaf/flower outlines, points and stems remain useful at comparison scale. The tightly framed leaf apex is still a capture limitation. |
| 03 fern | Most backing trapped between fronds removed. Small inner gaps and soft edges still need inspection. |
| 04 dry leaf | Intended leaf and narrow stem recovered instead of the textured backing. |
| 05 insect damage | Dense webbing recovered using the limited uniform-dark-backing fallback, with an explicit warning. Fine tissue/alpha still needs full-size review. |
| 06 cone | More pale scale ends retained; source resolution still limits fine edges. |
| 08 orchid | Pale petals, bud and main stem retained. Automatic stem orientation turns the group; disable it when capture orientation is desired. |
| 09 white feather | Previously rejected feather now isolated. Fine barbs and soft coverage remain approximations. |
| 10 duster | More outer strands retained, but the dense center is still mostly opaque and some gaps are lost. |
| 11 coal | Bright glints remain opaque instead of becoming false holes. Inspect the contact edge and photographed material. |
| 12 crystal | Previously rejected sample now produces a cutout. Cropped coverage and dark fissures remain ambiguous; physical transparency is unmeasured. |
| 13 shells | All five views retained with improved silhouette boundaries. |
| 14 almonds | All four subjects retained separately; the large bridge between the upper pair removed. |
| 15 outdoor leaf | Intended leaf recovered instead of only the crossing twig. Overlapping twig/seed material remains where it touches or hides the leaf. |
| 16–18 supplied alpha | Existing alpha/shape retained through photo preparation or artwork mode; no new extraction claim. |

These cases show useful improvements without establishing a general success
rate. Small background specks, narrow gaps, hair, contact shadows and occlusion
can remain. The foreground model analyzes a 1024-pixel square and bounded edge
refinement cannot restore arbitrary detail below its analysis scale. The scan
workflow and reconstruction/material limitations are unchanged.

## Version 0.4.1 fern correction

The fern's retained white spots prompted a conditional close-view pass, rather
than treating the first 0.4 output as accepted. Four overlapping predictions
are combined conservatively on thin colorful subjects with measured bright
neutral backing. Edge cleanup cannot grow rejected paper back into those gaps.

On the original fern at 1952 × 1470 analysis pixels, retained bright neutral
pixels fell from 7,744 to 168 at alpha ≥ 128. The color proxy uses minimum RGB
≥ 220 and channel span < 24; it is not a ground-truth mask or a general accuracy
score. More than 99.8% of previously near-opaque colored pixels remained above
the same alpha threshold (the source proxy uses old alpha ≥ 230 and channel
span ≥ 40). Fine pale edges still need inspection.

A separate real-photo conifer composite on bright neutral paper with a soft
shadow improved retained-background fraction from 2.80% to 1.78%, while reference
foreground recall stayed above 99.99%. The six broad-leaf controls were unchanged.
All other 14 opaque online captures were pixel-identical at the same bounded
analysis input; pale flowers, the feather, shells and rock highlights kept their
previous route. Supplied alpha remains a separate preservation control.

## Version 0.4.2 finishing comparison

The remaining fractional paper rims prompted a bounded edge-matte correction.
Using the same fern color proxy and analysis resolution, retained bright neutral
pixels fell from 168 to 13. At the masking stage, all existing pixels at alpha
242 or higher kept their color and alpha exactly. The finishing pass does not
guess replacement colors for weak fits; it only reduces their coverage.

The held-out conifer composite improved background leakage from 1.785% to 1.745%
with unchanged reference foreground recall (99.9925%). The six broad-leaf controls
and the other 14 opaque online captures stayed pixel-identical at the same bounded
inputs. These small case studies remain separate from independent visual acceptance;
fine pale material, noise and reflections can remain ambiguous.
