# Changelog

## 0.3.0 — leaf preparation and pair review

- Connect the established leaf background, interior protection and color pipeline
  to conservative stem-down orientation and explicit-name front/back alignment.
- Preserve existing per-photo recipes, skipped views, natural holes and each
  photographed outline; flag weak pairs instead of forcing a shape match.
- Add native review controls for quarter-turn orientation, unlabeled pairs,
  separate views and saved choices, with protected regeneration of owned outputs.
- Plan geometry with temporary previews; render final textures from original
  captures rather than reusing preview texture pixels. Retain the original
  one-pass route when geometry automation and explicit choices are disabled.
- Keep scan-mask processing and original scan photo bytes unchanged.

## 0.2.2 — simpler desktop workflow

- Make the main actions Load photo folder and Process photos; save ready scan
  results automatically, with guidance when a starting selection is needed.
- Create a fresh results folder beside the photos without a second folder picker.
  Preserve earlier batches and provide a manual save-location option.
- Move selection tools, display modes, edge settings, saved work and alternate
  scene handling into descriptive menus. Show review controls when relevant.
- Simplify leaf cutouts to Load photo folder and Process cutouts, with image size
  and save-location overrides under More options.

## 0.2.1 — experimental desktop scan release

- Add an optional Windows/Apple Silicon desktop app with guided SAM 2.1 masks,
  ordered-group tracking, saved projects, review/approval and protected exports.
- Preserve scan photo bytes, framing, EXIF orientation and full-size mask geometry.
- Add explicit permission for surfaces to continue beyond photo edges.
- Stop boundary-only warnings from holding unrelated following views; retain
  review propagation for uncertain target identity.
- Reuse the public leaf/image processor in the second tab.
- Use decoder-only pi-heif, retain bundled notices and provide dependency sources.
- Keep local scans, private paths, model weights and project data outside Git.


## 0.1.0 â€” 2026-10-30

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
