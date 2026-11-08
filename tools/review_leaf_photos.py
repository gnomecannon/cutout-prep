"""Run a selected real-photo group and make a local visual review, not a quality pass.

The JSON case file is a list of plain filenames in the input folder. Captures
are copied into a new output directory and all source hashes are checked again.
The report includes private local filenames and photographs; do not publish it
without reviewing their permissions and contents.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cutout_prep import leaf_batch, process_images as prep


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decoded(path):
    if path.suffix.lower() == '.dng':
        from cutout_prep.raw_decode import load_dng
        return Image.fromarray(load_dng(path, prep.srgb_encode)[0])
    return Image.fromarray(prep.load_image(path)[0])


def fit(image, size, background=(74, 78, 84)):
    image = image.copy().convert('RGBA')
    image.thumbnail(size, Image.Resampling.LANCZOS)
    tile = Image.new('RGB', size, background)
    tile.paste(image, ((size[0]-image.width)//2, (size[1]-image.height)//2), image)
    return tile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    parser.add_argument('--cases', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--size', type=int, default=2048)
    parser.add_argument('--app', type=Path, help='Optional installed portable executable; otherwise source worker')
    parser.add_argument('--artwork', action='store_true', help='Preserve supplied artwork colors and all alpha pieces')
    parser.add_argument('--provenance', type=Path, help='Optional source/credit/license manifest for the selected filenames')
    args = parser.parse_args()
    folder, output = args.folder.resolve(), args.output.resolve()
    names = json.loads(args.cases.read_text(encoding='utf-8-sig'))
    if not isinstance(names, list) or not names or any(not isinstance(n, str) or Path(n).name != n or any(c in n for c in '/\\:') for n in names):
        parser.error('Cases must be a nonempty JSON list of plain filenames')
    if len({n.casefold() for n in names}) != len(names):
        parser.error('Duplicate case filename')
    paths = [folder / n for n in names]
    provenance = {r['file']: r for r in json.loads(args.provenance.read_text(encoding='utf-8-sig'))} if args.provenance else {}
    if not all(p.is_file() and not p.is_symlink() for p in paths):
        parser.error('Every selected photo must be a regular file in the input folder')
    if output.exists() or folder == output or output in folder.parents:
        parser.error('Use a new output folder separate from the originals')
    output.mkdir(parents=True)
    inputs = output / 'Inputs'; inputs.mkdir()
    originals = {p.name: sha(p) for p in paths}
    for p in paths:
        shutil.copy2(p, inputs / p.name)
        if sha(inputs / p.name) != originals[p.name]:
            raise RuntimeError('Input copy hash mismatch')
    start = time.monotonic()
    choices = {'preserve_artwork': True} if args.artwork else {}
    options_path = output/'Worker Options.json'
    options_path.write_text(json.dumps(choices)+'\n', encoding='utf-8')
    with (output / 'Worker.log').open('w', encoding='utf-8') as log:
        if args.app:
            code = subprocess.run([str(args.app.resolve()), '--leaf-worker', str(inputs), str(output/'Results'), str(args.size), '--leaf-options', str(options_path)], stdout=log, stderr=subprocess.STDOUT).returncode
        else:
            import contextlib
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                code = leaf_batch.prepare(inputs, output/'Results', args.size, choices)
    if code not in (0, 2):
        raise RuntimeError(f'Photo worker failed ({code}); see Worker.log')
    results = output / 'Results'
    processing = json.loads((results/'ProcessingReport.json').read_text())
    geometry = json.loads((results/'LeafPreparation.json').read_text())
    views = output / 'Review'; views.mkdir()
    font = ImageFont.load_default(size=18)
    records = []
    for index, name in enumerate(names):
        output_name = prep.output_name(inputs/name, prep.DEFAULTS)
        dest = results / output_name
        if not dest.is_file():
            records.append({'photo': name, 'status': 'no output; inspect worker report'})
            continue
        capture = decoded(inputs/name)
        cutout = Image.open(dest).convert('RGBA')
        alpha = np.array(cutout.getchannel('A'))
        mask = alpha >= 128
        holes, count = ndi.label(ndi.binary_fill_holes(mask) & ~mask)
        hole_sizes = np.bincount(holes.ravel())[1:]
        component_count = ndi.label(mask, np.ones((3,3)))[1]
        record = {'photo': name, 'output': output_name, 'opaque_pixels': int(mask.sum()),
                  'provenance': provenance.get(name),
                  'input_kind': 'supplied alpha; tests preservation, not background extraction' if capture.getchannel('A').getextrema()[0] < 255 else 'opaque capture; tests extraction',
                  'components': component_count, 'holes_at_least_9_pixels': int((hole_sizes >= 9).sum()),
                  'orientation': geometry['files'].get(name, {}).get('orientation'),
                  'visual_acceptance': 'UNREVIEWED; counts and successful processing are not quality scores'}
        records.append(record)
        row = Image.new('RGB', (1800, 660), '#272b31')
        for column, (image, label) in enumerate([(capture, 'Decoded capture (no cleanup)'), (cutout, 'Prepared color and alpha'), (cutout.getchannel('A').convert('RGB'), 'Alpha: white kept, black removed')]):
            row.paste(fit(image, (600, 570)), (column*600, 45))
            ImageDraw.Draw(row).text((column*600+12, 15), label, fill='white', font=font)
        ImageDraw.Draw(row).text((12, 628), f'{index+1:02d}. {name}', fill='white', font=font)
        row.save(views/f'{index+1:02d}.jpg', quality=94)
    unchanged = all(sha(folder/n) == v and sha(inputs/n) == v for n, v in originals.items())
    if not unchanged:
        raise RuntimeError('Original or copied photo hash changed')
    report = {'worker': str(args.app.resolve()) if args.app else 'source', 'seconds': time.monotonic()-start,
              'source_hashes_unchanged': unchanged, 'source_hashes': originals, 'case_count': len(names),
              'output_size': args.size, 'choices': choices, 'worker_code': code, 'processing_counts': processing['counts'],
              'geometry_counts': geometry['counts'], 'pairs': geometry['pairs'], 'cases': records,
              'opaque_capture_count': sum(r.get('input_kind','').startswith('opaque') for r in records),
              'supplied_alpha_count': sum(r.get('input_kind','').startswith('supplied') for r in records),
              'quality_status': 'Visual review required; no independent ground-truth masks or general accuracy claim'}
    (output/'Review.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    rows = ''
    for i,r in enumerate(records):
        if 'output' not in r:continue
        source = r.get('provenance') or {}
        credit = html.escape(source.get('credit',''))
        page = source.get('source_page','')
        link = f'<a href="{html.escape(page, quote=True)}">Source and license</a>' if page.startswith('https://commons.wikimedia.org/') else ''
        rows += f'<section><h2>{html.escape(r["photo"])}</h2><img src="Review/{i+1:02d}.jpg"><p>Inspect lobes, teeth, stems, true holes, false holes, leftover backing, color and pair identity.</p><p>{credit} {html.escape(source.get("license",""))} {link}. Changes: resized capture preview; generated cutout and alpha.</p></section>'
    (output/'Review.html').write_text('<!doctype html><meta charset="utf-8"><title>Real leaf photo review</title><style>body{background:#20242a;color:#eee;font:17px system-ui;margin:24px}img{width:100%;max-width:1800px}section{margin:36px 0}h2{font-size:19px}</style><h1>Real leaf photo review</h1><p>Local photographs. Successful processing and mask overlap do not establish visual quality. Images remain unreviewed until a human or visual inspection records findings.</p>'+rows, encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['case_count','processing_counts','geometry_counts','source_hashes_unchanged','seconds']}, indent=2))


if __name__ == '__main__':
    main()
