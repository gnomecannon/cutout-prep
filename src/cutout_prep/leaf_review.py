"""Native, non-programmer controls for leaf orientation and explicit pairs."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageTk

from . import leaf_batch, leaf_geometry, process_images

ROTATIONS = {'Automatic stem direction': None, 'Keep photo orientation': 0,
             'Turn right 90°': 90, 'Turn upside down': 180, 'Turn left 90°': 270}


class LeafReviewDialog:
    def __init__(self, parent, source, output, choices, on_apply):
        self.source, self.output = Path(source).resolve(), Path(output).resolve()
        self.choices = leaf_batch.options(choices);self.on_apply = on_apply
        recipe=Path(self.choices['recipe']) if self.choices['recipe'] else self.source/'image-settings.json'
        settings=process_images.read_settings(recipe if recipe.is_file() else None)
        excluded={name for name,value in settings.get('images',{}).items() if value.get('skip')}
        self.names = sorted((p.name for p in self.source.iterdir() if p.is_file() and p.name not in excluded and not process_images.is_link_like(p) and p.suffix.lower() in process_images.EXTENSIONS), key=str.casefold)
        if not self.names:raise ValueError('Load a folder containing leaf photos first.')
        def short_label(index,name):
            stem=Path(name).stem
            for suffix in ('_Original','_BaseColor','_Source'):
                if stem.lower().endswith(suffix.lower()):stem=stem[:-len(suffix)]
            return f'{index+1}. '+(stem if len(stem)<=30 else '…'+stem[-29:])
        self.pair_labels={short_label(i,n):n for i,n in enumerate(self.names)}
        self.label_for={name:label for label,name in self.pair_labels.items()}
        self.report, self.preparation = {}, {}
        report = self.output / process_images.REPORT
        if report.is_file():
            data = json.loads(report.read_text(encoding='utf-8'))
            if data.get('input_root') == str(self.source):self.report = {r['source']: r for r in data['files'] if r.get('source')}
        report = self.output / leaf_batch.REPORT
        if report.is_file():
            data = json.loads(report.read_text(encoding='utf-8'))
            if data.get('schema') == leaf_batch.SCHEMA and data.get('input_root') == str(self.source):self.preparation = data
        self.top = tk.Toplevel(parent);self.top.title('Review leaf orientation and front/back pairs')
        self.top.geometry('1000x720');self.top.minsize(820, 620);self.top.transient(parent)
        self.top.grab_set()
        ttk.Label(self.top, text='Choose a photo, check its last saved result, then adjust the choices below.', wraplength=940).pack(fill='x', padx=12, pady=(10, 3))
        ttk.Label(self.top, text='For a paired leaf, set the front’s orientation; the back follows. Changes appear after processing again.', wraplength=940).pack(fill='x', padx=12)
        first = next((n for n in self.names if 'front' in n.lower()), self.names[0])
        self.photo_var = tk.StringVar(value=first);self.rotation_var = tk.StringVar()
        row = ttk.Frame(self.top);row.pack(fill='x', padx=12, pady=8)
        ttk.Label(row, text='Photo to review:').pack(side='left')
        combo = ttk.Combobox(row, values=self.names, textvariable=self.photo_var, state='readonly');combo.pack(side='left', fill='x', expand=True, padx=8)
        combo.bind('<<ComboboxSelected>>', lambda _: self.show_photo())
        center = ttk.Frame(self.top);center.pack(fill='both', expand=True, padx=12)
        self.canvas = tk.Canvas(center, background='#30353a', highlightthickness=0);self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda _: self.draw_preview())
        controls = ttk.Frame(center, width=300);controls.pack(side='right', fill='y', padx=(12, 0))
        ttk.Label(controls, text='Photo orientation').pack(anchor='w')
        rotation = ttk.Combobox(controls, values=list(ROTATIONS), textvariable=self.rotation_var, state='readonly', width=29);rotation.pack(fill='x', pady=4)
        rotation.bind('<<ComboboxSelected>>', lambda _: self.set_rotation())
        self.detail = tk.StringVar();ttk.Label(controls, textvariable=self.detail, wraplength=285).pack(fill='x', pady=(2, 12))
        ttk.Separator(controls).pack(fill='x', pady=8)
        ttk.Label(controls, text='Choose matching front and back photos').pack(anchor='w')
        self.front_var, self.back_var = tk.StringVar(), tk.StringVar()
        for text, variable in [('Front photo', self.front_var), ('Back / rear photo', self.back_var)]:
            ttk.Label(controls, text=text).pack(anchor='w', pady=(8, 0))
            ttk.Combobox(controls, values=list(self.pair_labels), textvariable=variable, state='readonly', width=37).pack(fill='x')
        ttk.Button(controls, text='Add this front/back pair', command=self.add_pair).pack(fill='x', pady=8)
        ttk.Label(controls, text='Named Front/Back photos are found automatically. Use these choices for unlabeled captures.', wraplength=285).pack(fill='x')
        pairs = ttk.LabelFrame(self.top, text='Front/back pairs');pairs.pack(fill='x', padx=12, pady=8)
        self.pair_list = tk.Listbox(pairs, height=3, exportselection=False);self.pair_list.pack(side='left', fill='both', expand=True, padx=5, pady=5)
        scrollbar = ttk.Scrollbar(pairs, orient='vertical', command=self.pair_list.yview);scrollbar.pack(side='left', fill='y');self.pair_list.configure(yscrollcommand=scrollbar.set)
        ttk.Button(pairs, text='Keep selected views separate', command=self.remove_pair).pack(side='right', padx=8)
        footer = ttk.Frame(self.top);footer.pack(fill='x', padx=12, pady=(0, 12))
        ttk.Button(footer, text='Apply choices and process again', command=self.apply).pack(side='left')
        ttk.Button(footer, text='Close without applying changes', command=self.close).pack(side='right')
        self.preview = None;self.display = None;self.refresh_pairs();self.show_photo()

    def show_photo(self):
        name = self.photo_var.get();angle = self.choices['rotations'].get(name)
        if name not in self.choices['rotations'] and not self.choices['orient_stems']:angle=0
        self.rotation_var.set(next(label for label, value in ROTATIONS.items() if value == angle))
        detail = self.preparation.get('files', {}).get(name, {})
        reason = detail.get('orientation', {}).get('reason', 'No saved orientation decision yet.')
        warnings = detail.get('warnings', [])
        self.detail.set(reason + ('\n\n' + '\n'.join(warnings) if warnings else '') + '\n\nThe picture shows the last saved result.')
        self.preview = None
        output_name = self.report.get(name, {}).get('output')
        if isinstance(output_name, str) and Path(output_name).name == output_name:
            path = self.output / output_name
            if path.is_file() and path.resolve().is_relative_to(self.output):
                with Image.open(path) as image:self.preview = image.convert('RGBA')
        self.draw_preview()

    def draw_preview(self):
        self.canvas.delete('all');w, h = max(1, self.canvas.winfo_width()), max(1, self.canvas.winfo_height())
        if self.preview is None:
            self.canvas.create_text(w/2, h/2, text='Process cutouts once to preview this photo.', width=max(120, w-40), fill='white');return
        image = self.preview.copy();image.thumbnail((max(1, w-16), max(1, h-16)), Image.Resampling.LANCZOS)
        backing = Image.new('RGBA', image.size, '#6a7075');backing.alpha_composite(image)
        self.display = ImageTk.PhotoImage(backing.convert('RGB'));self.canvas.create_image(w/2, h/2, image=self.display)

    def set_rotation(self):
        name = self.photo_var.get();angle = ROTATIONS[self.rotation_var.get()]
        if angle is None:self.choices['rotations'].pop(name, None)
        else:self.choices['rotations'][name] = angle
        self.detail.set('Choice saved in this window. Apply choices and process again to see the result.')

    def refresh_pairs(self):
        automatic, _ = leaf_geometry.named_pairs(self.names) if self.choices['align_pairs'] else ([], [])
        self.pairs = copy.deepcopy(self.choices['pairs'])
        claimed = {n for p in self.pairs for n in p.values()}
        self.pairs += [p for p in automatic if not claimed.intersection(p.values()) and not set(p.values()).intersection(self.choices['ignored_pairs'])]
        states = {(p['front'], p['back']): p['status'] for p in self.preparation.get('pairs', [])}
        self.pair_list.delete(0, 'end')
        for pair in self.pairs:
            state = states.get((pair['front'], pair['back']), 'chosen')
            self.pair_list.insert('end', f'{self.label_for.get(pair["front"],pair["front"])} ↔ {self.label_for.get(pair["back"],pair["back"])} — {state}')

    def add_pair(self):
        front=self.pair_labels.get(self.front_var.get(),self.front_var.get());back=self.pair_labels.get(self.back_var.get(),self.back_var.get())
        if front not in self.names or back not in self.names or front == back:
            messagebox.showinfo('Choose two different photos', 'Select the front and back photographs of the same leaf.', parent=self.top);return
        names = {front, back}
        self.choices['pairs'] = [p for p in self.choices['pairs'] if not names.intersection(p.values())]
        self.choices['pairs'].append({'front': front, 'back': back})
        self.choices['ignored_pairs'] = [n for n in self.choices['ignored_pairs'] if n not in names]
        self.refresh_pairs()

    def remove_pair(self):
        selection = self.pair_list.curselection()
        if not selection:return
        pair = self.pairs[selection[0]]
        self.choices['pairs'] = [p for p in self.choices['pairs'] if p != pair]
        self.choices['ignored_pairs'] = sorted(set(self.choices['ignored_pairs']) | set(pair.values()))
        self.refresh_pairs()

    def apply(self):
        choices = leaf_batch.options(self.choices)
        self.close();self.on_apply(choices)

    def close(self):
        self.top.grab_release();self.top.destroy()
