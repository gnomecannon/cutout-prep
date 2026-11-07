# Validation of the experimental desktop release

Checks establish specific behaviors, not a general mask-accuracy score.

## Automated and packaged checks

- 54 regression tests passed locally, covering the existing image processor,
  original-byte preservation, EXIF mask orientation, full-size exports, protected
  manual changes, project locks and review/tracking behavior. One Windows symlink
  privilege check was skipped. macOS also passed the source regression suite.
- Native Windows x64 and Apple Silicon packages passed real local image-model
  and temporal-tracking inference from their bundled model.
- A native Tk workflow exercise passed on Windows and macOS: box/point selection,
  undo, preview, save/reopen, persisted edge settings, cancellation, batch export,
  and three leaf/image cutouts. That harness supplies file-picker return values;
  it does **not** establish human OS-picker acceptance. The compiled Windows
  layout and native photo-picker opening were separately observed.
- Original photo hashes and exported source pixel dimensions were checked.
  An automatic Ready label does not establish a pixel-perfect silhouette.

## Real photo-group trials

| Group | Photos | Automatic outcome | Observed limitation |
| --- | ---: | --- | --- |
| Controlled turntable rock | 56 | 56 ready/exported, two initial selections | Capture coverage, contact/support edges and real material appearance still need inspection |
| Korno cliff subset | 7 | 7 ready/exported with expected-edge setting enabled | Some peripheral rock is omitted; wires crossing the face and small surface vegetation remain |
| Turntable skull subset | 46 | 9 ready/exported, 37 held for review | The later selections themselves reach the image border; those warnings remain intentionally active |

The cliff masks did not become more accurate when their framing warning was
removed. The setting records an expected capture condition. Identity uncertainty
continues to hold following frames until a new selection or approval.

Earlier trials also exercised an outdoor statue and a difficult bicycle scene.
The bicycle retained overlapping bench/background pixels even with a high model
score and lost tracking as the target became cropped, occluded or absent. It is
not an example of a supported unattended workflow.

## Reconstruction integration

RealityScan 2.2 imported all 56 exported rock mask layers, aligned the photos into
two components, and exported a CPU sparse-preview mesh from the selected largest
component: 24,500 vertices / 48,996 faces. This verifies a mask-import/alignment/
preview-mesh path. It does not verify a dense, complete, textured reconstruction,
the unseen underside, elimination of every support artifact, or physical material
properties. No private rock photographs or reconstruction project are published.

## Public example

![Original and retained cliff surface](images/cliff-comparison.jpg)

The source photograph is Zbytovsky's
[Korno climbing rock view 01](https://commons.wikimedia.org/wiki/File:Photogrammetry_dataset_of_Korno_climbing_rock_01.jpg),
published under CC0. The repository includes a resized, EXIF-free photograph and
the generated binary mask. The comparison dims excluded pixels; it is not a new
photograph or independently drawn ground-truth mask. The mask's imperfect edges
remain visible. The complete public dataset is linked from the source page.
