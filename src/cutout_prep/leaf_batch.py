"""Leaf preparation around the established, source-preserving image processor.

Small temporary previews determine geometry only. Final color and alpha are
rendered from the original capture, with one composed native-resolution layout.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile

import cv2
import numpy as np
from PIL import Image

from . import __version__, leaf_geometry as geometry, pair_alignment, process_images as prep

REPORT = 'LeafPreparation.json'
SCHEMA = 'cutout-prep-leaf-preparation-1'
DEFAULT_OPTIONS = {'orient_stems': True, 'align_pairs': True, 'balance_lighting': True,
                   'preserve_artwork': False, 'keep_separate_objects': True, 'cutout_method':'auto',
                   'rotations': {}, 'pairs': [], 'ignored_pairs': [], 'recipe': None}


def relative_name(value):
    if not isinstance(value, str) or not value or Path(value).name != value or any(c in value for c in '/\\:') or value in ('.', '..'):
        raise ValueError('Leaf choices must name a photo in the loaded folder.')
    return value


def options(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(DEFAULT_OPTIONS):
        raise ValueError('Unrecognized leaf preparation options.')
    result = {**copy.deepcopy(DEFAULT_OPTIONS), **copy.deepcopy(value)}
    for key in ('orient_stems', 'align_pairs', 'balance_lighting', 'preserve_artwork','keep_separate_objects'):
        if type(result[key]) is not bool:
            raise ValueError(f'{key} must be true or false.')
    if result['preserve_artwork']:
        result.update(orient_stems=False,align_pairs=False,balance_lighting=False,keep_separate_objects=True)
    if result['cutout_method'] not in ('auto','detailed','classic'):
        raise ValueError('Choose automatic detailed or classic background removal')
    if not isinstance(result['rotations'], dict) or not isinstance(result['pairs'], list):
        raise ValueError('Invalid saved leaf orientation or pairs.')
    for name, angle in result['rotations'].items():
        relative_name(name)
        if type(angle) is not int or angle not in (0, 90, 180, 270):
            raise ValueError('Leaf rotations must be quarter-turns.')
    if not isinstance(result['ignored_pairs'], list):
        raise ValueError('Invalid separate-view choices.')
    for name in result['ignored_pairs']:relative_name(name)
    claimed = set()
    for pair in result['pairs']:
        if not isinstance(pair, dict) or set(pair) != {'front', 'back'}:
            raise ValueError('Each leaf pair needs a front and a back photo.')
        for name in pair.values():
            relative_name(name)
            if name.casefold() in claimed:
                raise ValueError('A photo can belong to only one front/back pair.')
            claimed.add(name.casefold())
    if result['recipe'] is not None and not isinstance(result['recipe'], str):
        raise ValueError('Choose a leaf settings file, or leave it unset.')
    return result


def _read_report(path, source):
    data = json.loads(path.read_text(encoding='utf-8'))
    if data.get('schema') != SCHEMA or data.get('input_root') != str(source):
        raise ValueError('Existing leaf preparation report belongs to other work; choose a new results folder.')
    return data


def prepare(source, destination, size=4096, choices=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    prior_path = destination / REPORT
    prior = _read_report(prior_path, source) if prior_path.exists() else None
    selected = options(prior['options'] if choices is None and prior else choices)
    if not source.is_dir() or source == destination or destination in source.parents:
        raise ValueError('Choose a photo folder and a separate results folder.')
    size = int(size)
    recipe = Path(selected['recipe']).resolve() if selected['recipe'] else source / 'image-settings.json'
    settings = prep.read_settings(recipe if recipe.is_file() else None)
    if selected['recipe'] and not recipe.is_file():
        raise ValueError('The selected leaf settings file is missing.')
    preset='artwork' if selected['preserve_artwork'] else 'photo'
    defaults = {**prep.DEFAULTS, **prep.PRESETS[preset], **settings.get('defaults', {}), 'size': size}
    if not selected['balance_lighting']:
        defaults.update(exposure='none', shadow_lift=0.)
    prep.validate_options(defaults)
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / '.leaf-preparation.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError('Leaf preparation is already running here, or an interrupted run needs recovery.') from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        return _prepare(source, destination, size, selected, settings, defaults, recipe)
    finally:
        os.close(fd);lock.unlink()


def _prepare(source, destination, size, selected, settings, defaults, recipe):
    recipe_hash = prep.file_hash(recipe) if recipe.is_file() else None
    padding = defaults['padding'];analysis_size = min(size, 1024)
    analysis_padding = max(1, round(padding * analysis_size / size))
    lighting = ['--preset','artwork' if selected['preserve_artwork'] else 'photo']
    lighting += ['--cutout-method',selected['cutout_method']]
    if 'components' not in settings.get('defaults',{}):
        lighting += ['--components','all' if selected['keep_separate_objects'] else 'largest']
    if not selected['balance_lighting']:lighting += ['--exposure', 'none', '--shadow-lift', '0']
    mask_hashes = {}
    configured = [settings.get('defaults', {}), *settings.get('images', {}).values()]
    for entry in configured:
        if entry.get('mask'):
            path = (source / entry['mask']).resolve()
            if path.is_file():mask_hashes[path] = prep.file_hash(path)
    with tempfile.TemporaryDirectory(prefix='.leaf-previews-', dir=destination) as temporary:
        scratch = Path(temporary).resolve()
        if not scratch.is_relative_to(destination):
            raise ValueError('Unexpected preview location.')
        frozen_recipe = scratch / 'input-settings.json'
        frozen_recipe.write_text(json.dumps(settings), encoding='utf-8')
        if not selected['orient_stems'] and not selected['align_pairs'] and not selected['rotations'] and not selected['pairs']:
            code = prep.main([str(source), '--output', str(destination), '--settings', str(frozen_recipe),
                              '--size', str(size), '--update', *lighting])
            return _finish(source, destination, selected, {}, [], None, code)
        previews = scratch / 'Previews'
        code = prep.main([str(source), '--output', str(previews), '--settings', str(frozen_recipe),
                          '--size', str(analysis_size), '--padding', str(analysis_padding), *lighting])
        if code not in (0, 2) or not (previews / prep.REPORT).is_file():
            raise ValueError('Could not prepare leaf previews. See the processing log.')
        stage = json.loads((previews / prep.REPORT).read_text(encoding='utf-8'))
        rows = {r['source']: r for r in stage['files'] if r.get('source') and r.get('status') in ('processed', 'unchanged')}
        layouts, notes = {}, {}

        def alpha(name):
            with Image.open(previews / rows[name]['output']) as image:
                return np.array(image.getchannel('A'))

        for name, row in rows.items():
            image_settings = settings.get('images', {}).get(name, {})
            saved_layout = 'uv_transform' in image_settings
            saved_rotation = 'rotation_degrees' in image_settings or 'rotation_degrees' in settings.get('defaults', {})
            if name in selected['rotations']:
                decision = {'clockwise_degrees': selected['rotations'][name], 'confident': True, 'reason': 'User-selected orientation'}
            elif selected['orient_stems'] and not saved_layout and not saved_rotation:
                decision = geometry.stem_direction(alpha(name))
            else:
                decision = {'clockwise_degrees': 0, 'confident': False,
                            'reason': 'Saved leaf geometry preserved' if saved_layout or saved_rotation else 'Photo orientation kept'}
            layouts[name] = geometry.rotated_frame(alpha(name), decision['clockwise_degrees'], analysis_padding)
            uncertain_direction = selected['orient_stems'] and not decision['confident'] and decision['reason'].startswith(('Several similar tips', 'Stem direction'))
            notes[name] = {'orientation': decision, 'review_required': bool(uncertain_direction),
                           'warnings': ['Stem direction is unclear; check the orientation or keep the photographed direction.'] if uncertain_direction else []}

        automatic, ambiguous = geometry.named_pairs(rows) if selected['align_pairs'] else ([], [])
        for name in ambiguous:
            notes[name]['review_required'] = True
            notes[name]['warnings'].append('Several front/back candidates share this name; choose the pair explicitly.')
        pairs = copy.deepcopy(selected['pairs'])
        claimed = {name for pair in pairs for name in pair.values()}
        pairs += [pair for pair in automatic if not claimed.intersection(pair.values()) and not set(pair.values()).intersection(selected['ignored_pairs'])]
        pair_reports = []
        for pair in pairs:
            front, back = pair['front'], pair['back']
            record = {**pair, 'status': 'review'};pair_reports.append(record)
            if front not in rows or back not in rows:
                record['reason'] = 'A selected pair photo is missing, skipped, duplicated or could not be prepared.'
                for name in (front, back):
                    if name in notes:
                        notes[name]['review_required'] = True;notes[name]['warnings'].append(record['reason'])
                continue
            manual = pair in selected['pairs']
            if not manual and any('uv_transform' in settings.get('images', {}).get(name, {}) for name in (front, back)):
                record.update(status='saved', reason='Existing pair recipe preserved');continue
            try:
                a = geometry.alpha_canvas(alpha(front), layouts[front])
                b = geometry.alpha_canvas(alpha(back), layouts[back])
                plan = pair_alignment.estimate_alignment(a, b, padding=analysis_padding)
                record['metrics'] = plan['metrics']
                if not geometry.reliable_pair(plan):
                    raise ValueError('The outlines do not match closely enough. Independent shapes were kept; inspect this pair.')
                layouts[front] = np.asarray(plan['front_matrix']) @ layouts[front]
                layouts[back] = np.asarray(plan['back_matrix']) @ layouts[back]
                record.update(status='aligned', rear_reflected=True, transform_kind=plan['transform_kind'])
            except ValueError as exc:
                record['reason'] = str(exc)
                for name in (front, back):
                    notes[name]['review_required'] = True;notes[name]['warnings'].append(str(exc))

        final_settings = copy.deepcopy(settings)
        final_settings.setdefault('images', {})
        for name, layout in layouts.items():
            if not np.allclose(layout, np.eye(3), atol=1e-10, rtol=0):
                entry = final_settings['images'].setdefault(name, {})
                original = np.asarray(entry.get('uv_transform', np.eye(3)), dtype=float)
                entry['uv_transform'] = (geometry.normalized_transform(layout, analysis_size) @ original).tolist()
            notes[name]['layout_uv'] = geometry.normalized_transform(layout, analysis_size).tolist()
        # Geometry decisions must correspond to the same original bytes/recipe.
        if (prep.file_hash(recipe) if recipe.is_file() else None) != recipe_hash:
            raise ValueError('Leaf settings changed during preparation; run again when editing is finished.')
        for row in stage['files']:
            if row.get('source_sha256') and prep.file_hash(source / row['source']) != row['source_sha256']:
                raise ValueError('A source photo changed during preparation; previous results are preserved.')
        if any(prep.file_hash(path) != sha for path, sha in mask_hashes.items()):
            raise ValueError('A supplied mask changed during preparation; previous results are preserved.')
        final_recipe = scratch / 'final-settings.json'
        final_recipe.write_text(json.dumps(final_settings), encoding='utf-8')
        code = prep.main([str(source), '--output', str(destination), '--settings', str(final_recipe),
                          '--size', str(size), '--update', *lighting])
        return _finish(source, destination, selected, notes, pair_reports, analysis_size, code)


def _finish(source, destination, selected, notes, pair_reports, analysis_size, code):
    if code not in (0, 2):return code
    report_path = destination / prep.REPORT
    report = json.loads(report_path.read_text(encoding='utf-8'))
    for row in report['files']:
        if row.get('source') in notes:
            detail = notes[row['source']];row['leaf_preparation'] = detail
            row['review_required'] = bool(row.get('review_required') or detail['review_required'])
            row.setdefault('warnings', []).extend(detail['warnings'])
    review = sum(bool(row.get('review_required')) for row in report['files'])
    if review:report['counts']['review_required'] = review
    report['leaf_preparation_report'] = REPORT
    prep.atomic_bytes(report_path, json.dumps(report, indent=2, ensure_ascii=False).encode())
    result = {'schema': SCHEMA, 'version': __version__, 'input_root': str(source), 'options': selected,
              'analysis_size': analysis_size, 'files': notes, 'pairs': pair_reports,
              'counts': {'aligned_pairs': sum(p['status'] == 'aligned' for p in pair_reports),
                         'pairs_needing_review': sum(p['status'] == 'review' for p in pair_reports),
                         'rotated_photos': sum(n['orientation']['clockwise_degrees'] != 0 for n in notes.values())},
              'limits': 'Filename roles are pairing hints, not specimen identification. Quarter-turn orientation needs a clear stem. Natural holes and independent silhouettes remain. Final textures use the original capture, not preview pixels.'}
    prep.atomic_bytes(destination / REPORT, json.dumps(result, indent=2, ensure_ascii=False).encode())
    return 2 if code == 2 or review else 0
