# Changelog

## 0.1.0 — 2026-10-30

Initial experimental public release, extracted from a privately used photograph
preparation workflow.

- Automatic single-subject extraction on plain backgrounds, including connected
  thin-feature recovery, interior-hole checks, and edge-color cleanup.
- Color-managed 8-bit sRGB PNG exports with configurable square framing,
  linear-light premultiplied-alpha resampling, and invisible edge-color padding.
- Optional full-resolution DNG development with bounded capture-reference tone
  and shadow-color calibration.
- Photo and artwork presets; configurable retention of disconnected alpha
  components for existing transparent artwork.
- Managed repeat runs, duplicate checks, manual-edit protection, previews,
  per-file reports, and one-writer output locking.
- Advanced front/rear alignment API and stored UV-transform support.
- Portable package/CLI, Windows drag-and-drop launcher, synthetic examples,
  regression tests, and Windows/Linux CI.

Known limits include uncertain shadow colors, source-camera rendering differences,
incomplete extraction in dense fine foliage, and natural front/rear shape mismatch.
See the README and AI development disclosure before relying on the output.
