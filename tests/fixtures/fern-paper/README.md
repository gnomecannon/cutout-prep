# Approved fern reference

`source.jpg` is **Fern-leaf-oliv.jpg** by Olegivvit (author attribution assumed
in the source metadata), from [Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Fern-leaf-oliv.jpg).
It is used under [CC BY 2.5](https://creativecommons.org/licenses/by/2.5/).
The original photograph is unchanged; SHA-256:
`cca4aceadb41ee1f7bf9248649153bad4929d90403100382c0ac3696df850162`.

`accepted-mask.png` is the reviewed, corrected alpha derived from that photograph.
Background/shadow pockets were removed and source-visible stems restored. It is
also supplied under CC BY 2.5. It is a human-approved example, not independently
annotated scientific ground truth or a promise of accuracy on other photographs.

`model-prior.png` records the global 1024-square BiRefNet Lite prediction, quantized
to 8-bit grayscale, before cleanup. The pinned model identity is in
`tools/cutout-model-manifest.json`. The reference tests can therefore exercise
real-photo refinement offline without downloading model weights. Full model and
packaged-app checks are separate from those recorded-prior tests.

These data licenses are separate from the application's MIT code license.
