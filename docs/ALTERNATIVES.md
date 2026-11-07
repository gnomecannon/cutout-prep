# Related tools

Cutout Prep combines guided scan masks and traditional game-asset cutout
preparation in a small, offline desktop workflow. Its segmentation models and
general masking approach are established techniques, not new research.

- [RealityScan](https://rshelp.capturingreality.com/en-US/tools/mask.htm) generates
  AI masks and masks from reconstructed meshes inside its reconstruction workflow.
- [Metashape](https://agisoft.freshdesk.com/support/solutions/articles/31000153479)
  supports manual, AI, background-reference and model-based mask generation.
- [SAM Mask GUI](https://github.com/catfield123/sam-mask-gui) offers point/brush
  editing, propagation, full-resolution masks and SAM3 text prompts. It has richer
  editing controls than this initial Cutout Prep desktop release.
- [rembg](https://github.com/danielgatis/rembg) offers automatic background removal,
  folder processing, CPU support and several model choices.

No matched accuracy or speed benchmark against these projects has been run.
This release's particular focus is ready-to-run Windows/Apple Silicon packaging,
unchanged scan photograph copies, RealityScan mask naming, explicit review, and
the existing leaf/image-cutout workflow. These benefits are a combination of
workflow choices, not a claim that other projects cannot provide them.
