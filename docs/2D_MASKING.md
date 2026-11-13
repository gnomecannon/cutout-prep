# Detailed 2D cutouts

The normal desktop workflow remains **Load photo folder → Process cutouts**.
The portable app includes a local foreground model and runs without uploading
images, executing downloaded Python code or using a paid service.

## What changes in 0.4

Opaque photos use [BiRefNet Lite](https://huggingface.co/ZhengPeng7/BiRefNet_lite),
through a pinned [ONNX conversion](https://huggingface.co/onnx-community/BiRefNet_lite-ONNX).
The model predicts object coverage before bounded edge cleanup. Confirmed solid
interiors retain opaque alpha and their captured RGB, so edge color projection
cannot turn bright rock glints into holes. Predicted gaps are not flood-filled.
Uncertain boundaries receive local foreground/background color refinement.

An incomplete prediction can be recovered for fine material on measured uniform
dark backing. This checks a robust dark border cluster and source contrast;
it is not a general clutter fallback. Such results carry a review warning.

**More options → Keep separate objects and small pieces** is on by default.
It prevents the final image cleanup from discarding other segmented objects.
Several significant separate subjects do not trigger a guessed stem rotation.
The previous extractor remains under **Background removal method → Simple
background (older method)**. Existing per-photo settings remain authoritative.

Supplied transparency and explicit masks bypass automatic extraction. Choose
**Preserve existing artwork colors and alpha** for already prepared sprites or
drawings; it also disables automatic photographic lighting and geometry. RAW
tone/reference handling, brightness/shadow preparation and pair controls remain.

The image-model input is 1024 square pixels; edge refinement works at up to 2048
pixels on the long edge. Final color textures are rendered from the original
capture, not the analysis preview. Very fine detail below those analysis scales
can still be lost. Inferred alpha is not measured optical transmission.

## Fine fronds on bright paper: 0.4.1

The first detailed pass still left white backing around fine fern leaflets.
Thin chromatic subjects with measured bright neutral backing and retained paper
now receive four overlapping close-view predictions. Confident colored source
material stays protected, local predictions may only reduce the global mask,
and excessive coverage disagreement rejects the correction. An alpha ceiling
prevents the edge projection from growing rejected paper back into the gaps.

This pass is automatic and conditional; it does not remove white pixels from
every image. Broad solid objects, predominantly pale subjects and backgrounds
without the required paper evidence keep the previous route. Supplied alpha
and masks continue to bypass extraction. Qualifying captures take additional
CPU inference time. Pale details, tiny structures and mixed materials still
need visual review.

## Fractional paper rims: 0.4.2

Some fine edges still retained partly transparent white backing after the close
views. Qualifying captures now receive a bounded finishing pass around those
existing edges. It requires a neutral-paper connection to transparent backing,
nearby opaque colored material and a supported foreground/background color fit.
Nearby measured paper can account for soft contact shadows.

The pass only reduces coverage below alpha 242 and within four analysis pixels
of the existing boundary. Captured near-opaque material, enclosed pale tissue
without a backing connection, and saturated colored edges remain unchanged.
RGB unmixing requires the tighter color fit; weaker supported fits retain RGB
while reducing coverage, avoiding amplification of capture/compression noise.
It adds no model inference or user steps. Fine pale detail still needs review.

## Real-photo evidence and limits

The [pinned online cases](REAL_PHOTO_TESTS.md) preserve the v0.3 baseline. Direct
comparisons showed substantially less backing inside fern branches, recovered
feather detail, a solid rock mask without glint holes, and correct leaf selection
in the outdoor example. Separate shell/almond subjects were retained. A dense,
cropped insect-damage example required the limited dark-backing recovery.

A separate known-alpha trial used seven real photographic leaf cutouts on two
generated simple backgrounds. On the conifer with a soft shadow, retained
background fell from about 9.0% to 2.5% of the predicted foreground, while reference
foreground recall stayed above 99.9%. Some backing remained. These are reference
recovery measurements on composites, not general real-photo accuracy.

Small branch gaps, soft hair, shadows, cropped subjects and overlapping clutter
still need inspection. Small detached background specks can remain when keeping
all foreground pieces. A source photograph can hide or merge surfaces that
cannot be recovered faithfully. Processing success and a model score are not
visual acceptance. The 3D scan-mask workflow and source photo bytes/framing are
unchanged; this does not repair mesh slabs or recover physical roughness.

## Source setup

Install `.[cutout]`, download the pinned model with
`python tools/download_model.py --kind cutout --output MODEL_FOLDER`, and set
`CUTOUT_PREP_2D_MODEL_DIR` to that folder. The basic Python image CLI still works
without the optional model/runtime using the classic method. `--cutout-method
detailed` requires the model; `--cutout-method classic` explicitly selects the
old method. Portable builds require their bundled model to be complete.

Both model and CPU runtime are MIT licensed. Their notices, model hashes and
source revisions travel with the portable app. See
[third-party notices](../THIRD_PARTY_NOTICES.md).
