"""Portable Cutout Prep UI. Windows/macOS source; CPU-only, offline processing."""
from __future__ import annotations
import argparse, contextlib, copy, json, os, queue, runpy, subprocess, sys, tempfile, threading, traceback, webbrowser
from pathlib import Path

def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent/'resources'))

def model_directory():
    bundled=resources()/'models/sam2-tiny'
    return Path(os.environ.get('CUTOUT_PREP_MODEL_DIR',str(bundled)))

def leaf_worker(source,output,size,choices=None):
    from cutout_prep import leaf_batch
    return leaf_batch.prepare(source,output,int(size),choices)

def check_runtime(output):
    """A file-based packaged-dependency check; no desktop or network needed."""
    from cutout_prep import scan_core as core
    import numpy as np
    from PIL import Image,ImageDraw
    destination=Path(output);destination.mkdir(parents=True,exist_ok=True)
    result={'frozen':bool(getattr(sys,'frozen',False)),'resources':str(resources())}
    with (destination/'Runtime.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
        try:
            image=Image.new('RGB',(640,480),'#ece7dc');draw=ImageDraw.Draw(image);draw.ellipse((180,100,470,410),fill='#4c713f')
            predictor=core.Predictor(model_directory());mask,score=predictor.predict(image,[[.5,.5,1]],[.25,.18,.77,.9])
            predictor.seed_sequence(image,mask);tracked,temporal_score=predictor.track_next(image)
            Image.fromarray(mask.astype(np.uint8)*255).save(destination/'Runtime Mask.png')
            result.update(ok=True,mask_size=[mask.shape[1],mask.shape[0]],mask_pixels=int(mask.sum()),score=score,temporal_pixels=int(tracked.sum()),temporal_score=temporal_score)
        except Exception:result.update(ok=False,error=traceback.format_exc())
    core.save_json(destination/'Runtime Check.json',result)
    return 0 if result['ok'] else 1

def main():
    p=argparse.ArgumentParser();p.add_argument('--leaf-worker',nargs=3);p.add_argument('--leaf-options',type=Path);p.add_argument('--check-runtime');p.add_argument('--project');p.add_argument('--smoke',action='store_true');args=p.parse_args()
    if args.check_runtime:return check_runtime(args.check_runtime)
    if args.leaf_worker:
        Path(args.leaf_worker[1]).mkdir(parents=True,exist_ok=True)
        with (Path(args.leaf_worker[1])/'Leaf Worker.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            try:return leaf_worker(*args.leaf_worker,choices=json.loads(args.leaf_options.read_text(encoding='utf-8')) if args.leaf_options else None)
            except Exception:traceback.print_exc();return 1
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    import numpy as np
    from PIL import Image,ImageTk
    from cutout_prep import scan_core as core
    from cutout_prep.desktop_paths import create_results_folder
    from cutout_prep import __version__

    class App:
        def __init__(self,root):
            self.root=root;self.project=None;self.index=0;self.predictor=None;self.photo=None;self.mask=None;self.display=None;self.bounds=(0,0,1,1);self.box_start=None;self.busy=False;self.cancel=threading.Event();self.events=queue.Queue();self.history={};self.child=None
            root.title(f'Cutout Prep {__version__}');root.geometry('1080x740');root.minsize(820,600)
            self.status=tk.StringVar(value='Load a photo folder to begin. Your original photos stay untouched.')
            self.mode=tk.StringVar(value='object');self.tool=tk.StringVar(value='box');self.view=tk.StringVar(value='overlay');self.margin=tk.IntVar(value=0);self.allow_border=tk.BooleanVar(value=False)
            self.new_mode=tk.StringVar(value='object')
            style=ttk.Style();style.theme_use('clam');style.configure('TButton',padding=(9,5));style.configure('TLabel',padding=2)
            notebook=ttk.Notebook(root);notebook.pack(fill='both',expand=True,padx=10,pady=8)
            self.scan_tab=ttk.Frame(notebook);self.leaf_tab=ttk.Frame(notebook);notebook.add(self.scan_tab,text='Photos for 3D scanning');notebook.add(self.leaf_tab,text='Leaf & image cutouts')
            top=ttk.Frame(self.scan_tab);top.pack(fill='x')
            self.load_button=ttk.Button(top,text='Load photo folder…',command=self.choose_folder);self.load_button.pack(side='left',padx=3,pady=6)
            self.process_button=ttk.Button(top,text='Process photos',command=self.batch);self.process_button.pack(side='left',padx=3)
            self.results_button=ttk.Button(top,text='Show results folder',command=self.open_output);self.results_button.pack(side='left',padx=3)
            self.more_button=ttk.Menubutton(top,text='More options');self.more_button.pack(side='right',padx=3)
            self.job_buttons=[self.load_button,self.process_button,self.more_button]
            self.build_scan_menu()
            self.mode_hint=ttk.Label(self.scan_tab,wraplength=1000)
            self.mode_hint.pack(fill='x',padx=3,pady=(3,5));self.set_mode_hint()
            panes=ttk.Panedwindow(self.scan_tab,orient='horizontal');panes.pack(fill='both',expand=True,pady=6)
            left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=5)
            self.tree=ttk.Treeview(left,columns=('state',),show='tree headings',selectmode='browse',height=16);self.tree.heading('#0',text='Photograph');self.tree.heading('state',text='Status');self.tree.column('#0',width=175);self.tree.column('state',width=80);self.tree.pack(side='left',fill='both',expand=True)
            scroll=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.bind('<<TreeviewSelect>>',self.select)
            self.canvas=tk.Canvas(right,bg='#25282d',highlightthickness=0);self.canvas.pack(fill='both',expand=True);self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.release)
            foot=ttk.Frame(right);self.photo_navigation=foot;ttk.Button(foot,text='Previous photo',command=lambda:self.navigate(-1)).pack(side='left',pady=4);ttk.Button(foot,text='Next photo',command=lambda:self.navigate(1)).pack(side='left',padx=4)
            self.detail=tk.StringVar(value='No photo folder loaded.');self.detail_label=ttk.Label(self.scan_tab,textvariable=self.detail,wraplength=1000);self.detail_label.pack(fill='x')
            self.review_bar=ttk.Frame(self.scan_tab)
            self.adjust_button=ttk.Menubutton(self.review_bar,text='Adjust this selection');self.adjust_button.configure(menu=self.selection_menu)
            self.review_button=ttk.Button(self.review_bar,text='Find photos needing review',command=self.next_review)
            self.approve_button=ttk.Button(self.review_bar,text='Use this photo’s result',command=self.approve)
            self.exclude_button=ttk.Button(self.review_bar,text='Skip this photo',command=self.exclude)
            self.job_buttons += [self.adjust_button,self.review_button,self.approve_button,self.exclude_button]
            self.cancel_button=ttk.Button(self.review_bar,text='Stop after current photo',command=self.cancel.set,state='disabled')
            self.progress=ttk.Progressbar(self.scan_tab,mode='determinate');self.progress.pack(fill='x',pady=2)
            self.status_label=ttk.Label(root,textvariable=self.status,wraplength=1000);self.status_label.pack(fill='x',padx=12,pady=(0,8))
            self.build_leaf_tab(ttk,tk,filedialog,messagebox)
            self.update_controls()
            root.bind('<Configure>',lambda event:self.fit_text() if event.widget==root else None)
            root.protocol('WM_DELETE_WINDOW',self.close);root.bind('<Control-z>',lambda e:self.undo())
            if sys.platform=='darwin':root.bind('<Command-z>',lambda e:self.undo())
            root.after(150,self.poll)
            if args.project:self.load_project(Path(args.project))
            if args.smoke:root.after(1000,lambda:self.status.set('UI smoke check ready.'))
        def fail(self,error):messagebox.showerror('Cutout Prep',str(error),parent=self.root)
        def guide(self):webbrowser.open((resources()/'Guide.html').as_uri())
        def fit_text(self):
            width=max(400,self.root.winfo_width()-40)
            for label in [self.mode_hint,self.detail_label,self.status_label,*self.leaf_tab.winfo_children()]:
                if isinstance(label,ttk.Label):label.configure(wraplength=width)
        def build_scan_menu(self):
            menu=tk.Menu(self.more_button,tearoff=False);self.scan_menu=menu;self.more_button.configure(menu=menu)
            menu.add_command(label='Load selected photos…',command=self.choose_files)
            menu.add_command(label='Load folder and choose save location…',command=lambda:self.choose_folder(True))
            menu.add_command(label='Open saved work…',command=self.open_project)
            menu.add_command(label='Save progress now',command=self.save)
            menu.add_separator()
            workflow=tk.Menu(menu,tearoff=False)
            workflow.add_radiobutton(label='Keep one object or surface',variable=self.new_mode,value='object',command=self.set_mode_hint)
            workflow.add_radiobutton(label='Keep scene; remove selected area',variable=self.new_mode,value='scene',command=self.set_mode_hint)
            menu.add_cascade(label='For the next photo group',menu=workflow)
            settings=tk.Menu(menu,tearoff=False)
            settings.add_checkbutton(label='Subject continues beyond photo edges (cliffs)',variable=self.allow_border,command=self.change_border)
            border=tk.Menu(settings,tearoff=False)
            for value in [-5,-3,-1,0,1,3,5]:
                label='Original outline' if value==0 else f'{"Smaller" if value<0 else "Larger"} selected area ({value:+d})'
                border.add_radiobutton(label=label,variable=self.margin,value=value,command=self.change_margin)
            settings.add_cascade(label='Adjust selected area’s outline',menu=border)
            menu.add_cascade(label='Mask settings',menu=settings)
            self.selection_menu=tk.Menu(menu,tearoff=False)
            for label,value in [('Draw a box around the subject','box'),('Click areas to keep','keep'),('Click areas to remove','remove')]:
                self.selection_menu.add_radiobutton(label=label,variable=self.tool,value=value,command=self.set_mode_hint)
            self.selection_menu.add_separator()
            for label,command in [('Undo last selection change',self.undo),('Clear this selection',self.clear),('Preview this photo’s result',self.preview)]:
                self.selection_menu.add_command(label=label,command=command)
            menu.add_cascade(label='Adjust this selection',menu=self.selection_menu)
            view=tk.Menu(menu,tearoff=False)
            for label,value in [('Highlight the kept area','overlay'),('Show black and white mask','mask'),('Show original photo','original')]:
                view.add_radiobutton(label=label,variable=self.view,value=value,command=self.draw)
            view.add_command(label='Show photo details…',command=self.photo_details)
            menu.add_cascade(label='Photo display',menu=view)
            menu.add_command(label='Process again from this photo',command=lambda:self.batch(True))
            menu.add_command(label='Save ready photos and masks again',command=self.export)
            menu.add_separator();menu.add_command(label='Read the quick guide',command=self.guide)
        def update_controls(self):
            loaded=self.project is not None;idle=not self.busy
            for label in ['Save progress now','Adjust this selection','Photo display','Process again from this photo','Save ready photos and masks again']:
                self.scan_menu.entryconfigure(label,state='normal' if loaded and idle else 'disabled')
            self.process_button.configure(state='normal' if loaded and idle else 'disabled')
            ready=loaded and (self.project.root/'Prepared Photos').is_dir()
            self.results_button.configure(state='normal' if ready else 'disabled')
            if hasattr(self,'leaf_run'):
                self.leaf_run.configure(state='normal' if idle and self.leaf_source.get() else 'disabled')
                has_results=bool(self.leaf_output.get()) and (Path(self.leaf_output.get())/'ProcessingReport.json').is_file()
                self.leaf_results_button.configure(state='normal' if has_results else 'disabled')
            if loaded:
                self.photo_navigation.pack(fill='x')
                self.review_bar.pack(fill='x',pady=4,before=self.progress)
                self.adjust_button.pack(side='left',padx=3)
                self.exclude_button.pack(side='left',padx=3)
                self.cancel_button.pack(side='right',padx=3)
                row=self.row();has_mask=bool(row.get('mask'))
                if has_mask:
                    self.approve_button.pack(side='left',padx=3)
                    self.approve_button.configure(state='normal' if idle and not row.get('excluded') and row['status'] not in ('Selection changed','Error') else 'disabled')
                else:self.approve_button.pack_forget()
                count=sum(not r.get('excluded') and r['status'] in ('Review','Error','Selection changed') for r in self.project.data['photos'])
                if count:
                    self.review_button.configure(text=f'Review {count} photo{"s" if count!=1 else ""}')
                    self.review_button.pack(side='left',padx=3)
                else:self.review_button.pack_forget()
                self.exclude_button.configure(text='Use this photo again' if row.get('excluded') else 'Skip this photo')
            else:self.review_bar.pack_forget();self.photo_navigation.pack_forget()
        def photo_details(self):
            if not self.project:return
            row=self.row();score=row.get('score')
            text=f'{row["name"]}\n{row["size"][0]} × {row["size"][1]} pixels\nStatus: {row["status"]}'
            if score is not None:text+=f'\nModel score: {score:.2f} (not an accuracy guarantee)'
            messagebox.showinfo('Photo details',text,parent=self.root)
        def row(self):return self.project.data['photos'][self.index] if self.project else None
        def save(self):
            if self.project:
                try:self.project.save();self.status.set('Project saved. You can close and reopen it to continue.')
                except Exception as exc:self.fail(exc)
        def replace_project(self,new):
            if self.project:self.project.save();self.project.close()
            self.project=new;self.index=0;self.mode.set(new.data['mode']);self.margin.set(new.data.get('margin',0));self.allow_border.set(new.data.get('allow_border',False));self.history={};self.refresh_tree();self.show_photo();self.set_mode_hint()
        def change_border(self):
            if self.project:
                self.project.data['allow_border']=bool(self.allow_border.get());self.project.save()
                self.status.set('Edge setting saved. Preview or process again to update mask checks; existing approvals are preserved.')
        def create(self,paths,photo_folder=None,choose_location=False):
            if self.busy:return
            paths=list(paths)
            if not paths:return self.fail('This folder has no supported photos. Choose JPEG, HEIC, PNG or TIFF photographs.')
            if choose_location:
                dest=filedialog.askdirectory(title='Choose a separate folder for results and saved work',parent=self.root)
                if not dest:return
            else:
                try:dest=create_results_folder(photo_folder or Path(paths[0]).parent,'Scan Masks')
                except OSError:
                    dest=filedialog.askdirectory(title='Choose where to save results; the photo folder’s parent is not writable',parent=self.root)
                    if not dest:return
            if Path(dest).resolve() in {Path(p).resolve().parent for p in paths}:
                return self.fail('Choose a results folder separate from your original photos.')
            try:
                if Path(dest).exists() and any(Path(dest).iterdir()):
                    return self.fail('Choose an empty results folder. To continue previous work, use More options → Open saved work.')
                project=core.Project.create(paths,dest,self.new_mode.get())
                project.data.update(allow_border=bool(self.allow_border.get()),margin=int(self.margin.get()));project.save()
                self.replace_project(project);self.tool.set('box');self.set_mode_hint();self.update_controls()
                self.status.set(f'Loaded {len(project.data["photos"])} photos. Results will save in “{project.root.name}”. Draw a box around what to {"keep" if self.mode.get()=="object" else "remove"}.')
            except Exception as exc:self.fail(exc)
        def choose_files(self):
            paths=filedialog.askopenfilenames(title='Choose scan photographs',filetypes=[('Photographs','*.jpg *.jpeg *.png *.tif *.tiff *.heic *.heif *.webp *.bmp'),('All files','*')],parent=self.root)
            if paths:self.create(paths)
        def choose_folder(self,choose_location=False):
            folder=filedialog.askdirectory(title='Choose the folder containing scan photos',parent=self.root)
            if folder:self.create([p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in core.EXTENSIONS and '.mask.' not in p.name.lower()],folder,choose_location)
        def open_project(self):
            f=filedialog.askopenfilename(title='Open saved photo group',filetypes=[('Saved work (Scan Project.json)','*.json')],parent=self.root)
            if f:self.load_project(Path(f))
        def load_project(self,path):
            try:self.replace_project(core.Project.open(path));self.update_controls()
            except Exception as exc:self.fail(exc)
        def refresh_tree(self):
            if not self.project:return
            selected=str(self.index);self.tree.delete(*self.tree.get_children())
            for i,r in enumerate(self.project.data['photos']):self.tree.insert('','end',iid=str(i),text=r['name'],values=('Excluded' if r.get('excluded') else r['status'],))
            if self.tree.exists(selected):self.tree.selection_set(selected);self.tree.see(selected)
        def select(self,event=None):
            selected=self.tree.selection()
            if selected:self.index=int(selected[0]);self.show_photo()
        def show_photo(self):
            if not self.project:return
            try:
                r=self.row();self.photo=core.load_photo(r['path']);self.mask=self.project.read_mask(r,self.photo.size);self.draw()
                warnings=' '.join(r.get('warnings',[]))
                self.detail.set(f'Photo {self.index+1} of {len(self.project.data["photos"])} · {r["status"]}  {warnings}')
                self.update_controls()
            except Exception as exc:self.fail(exc)
        def draw(self):
            self.canvas.delete('all')
            if self.photo is None:
                self.canvas.create_text(max(200,self.canvas.winfo_width()/2),150,text='Load a photo folder to begin',fill='white',font=('TkDefaultFont',17));return
            image=self.photo.copy()
            if self.mask is not None and self.view.get()!='original':
                if self.view.get()=='mask':image=Image.fromarray(self.mask.astype(np.uint8)*255).convert('RGB')
                else:
                    a=np.array(image).astype(float);a[~self.mask]*=.25;a[self.mask]=a[self.mask]*.83+np.array([20,180,100])*.17;image=Image.fromarray(np.clip(a,0,255).astype(np.uint8))
            width=max(1,self.canvas.winfo_width()-12);height=max(1,self.canvas.winfo_height()-12);image.thumbnail((width,height),Image.Resampling.LANCZOS)
            x=(self.canvas.winfo_width()-image.width)/2;y=(self.canvas.winfo_height()-image.height)/2;self.bounds=(x,y,image.width,image.height);self.display=ImageTk.PhotoImage(image);self.canvas.create_image(x,y,anchor='nw',image=self.display)
            r=self.row()
            if r:
                for px,py,label in r.get('points',[]):
                    cx=x+px*image.width;cy=y+py*image.height;color='#2aff80' if (label==1)==(self.mode.get()=='object') else '#ff6464';self.canvas.create_oval(cx-5,cy-5,cx+5,cy+5,fill=color,outline='white',width=1)
                box=r.get('box')
                if box:self.canvas.create_rectangle(x+box[0]*image.width,y+box[1]*image.height,x+box[2]*image.width,y+box[3]*image.height,outline='#ffd166',width=2)
        def normalized(self,event):
            x,y,w,h=self.bounds
            if w<=0 or h<=0 or not x<=event.x<=x+w or not y<=event.y<=y+h:return None
            return [min(.999999,max(0,(event.x-x)/w)),min(.999999,max(0,(event.y-y)/h))]
        def remember(self):
            r=self.row();self.history.setdefault(self.index,[]).append((copy.deepcopy(r.get('points',[])),copy.deepcopy(r.get('box'))))
        def changed(self):
            r=self.row();r['approved']=False;r['status']='Selection changed';self.project.save();self.refresh_tree();self.draw();self.update_controls()
        def press(self,event):
            if not self.project or self.busy:return
            point=self.normalized(event)
            if point is None:return
            if self.tool.get()=='box':self.box_start=point;return
            self.remember();label=1 if self.tool.get()=='keep' else 0
            if self.mode.get()=='scene':label=1-label
            self.row()['points'].append([*point,label]);self.changed()
        def drag(self,event):
            if self.box_start is None:return
            point=self.normalized(event)
            if point:
                self.draw();x,y,w,h=self.bounds;self.canvas.create_rectangle(x+self.box_start[0]*w,y+self.box_start[1]*h,x+point[0]*w,y+point[1]*h,outline='#ffd166',width=2)
        def release(self,event):
            if self.box_start is None:return
            point=self.normalized(event);start=self.box_start;self.box_start=None
            if point and abs(point[0]-start[0])>.01 and abs(point[1]-start[1])>.01:
                self.remember();self.row()['box']=[min(start[0],point[0]),min(start[1],point[1]),max(start[0],point[0]),max(start[1],point[1])];self.changed()
        def undo(self):
            if self.busy or not self.project:return
            stack=self.history.get(self.index,[])
            if stack:self.row()['points'],self.row()['box']=stack.pop();self.changed()
        def clear(self):
            if not self.project or self.busy:return
            self.remember();self.row()['points']=[];self.row()['box']=None;self.changed()
        def navigate(self,delta):
            if not self.project:return
            self.index=max(0,min(len(self.project.data['photos'])-1,self.index+delta));self.tree.selection_set(str(self.index));self.tree.see(str(self.index));self.show_photo()
        def next_review(self):
            if not self.project:return
            rows=self.project.data['photos']
            for offset in range(1,len(rows)+1):
                index=(self.index+offset)%len(rows);row=rows[index]
                if not row.get('excluded') and row['status'] in ('Review','Error','Selection changed'):
                    self.index=index;self.tree.selection_set(str(index));self.tree.see(str(index));self.show_photo();return
            self.status.set('No flagged views. Inspect the silhouettes before importing the exported photos.')
        def approve(self):
            if not self.project or self.busy:return
            r=self.row();path=self.project.mask_path(r)
            if not path or not path.exists():return self.fail('Preview or process this view first.')
            if r['status']=='Selection changed':return self.fail('Preview the changed selection before approving its mask.')
            r['mask_sha256']=core.digest(path);r['approved']=True;r['status']='Approved';self.project.save();self.refresh_tree();self.show_photo();self.export()
        def exclude(self):
            if not self.project or self.busy:return
            r=self.row();r['excluded']=not r.get('excluded',False);self.project.save();self.refresh_tree();self.show_photo()
            if (self.project.root/'Export Report.json').exists():self.export()
        def set_mode_hint(self):
            mode=self.mode.get() if self.project else self.new_mode.get()
            if self.tool.get()=='box':
                text='Draw a box around what to keep, then choose Process photos. Ready results save automatically.' if mode=='object' else 'Draw a box around the unwanted area, then choose Process photos. The surrounding scene is kept.'
            else:text=f'Click areas to {"keep" if self.tool.get()=="keep" else "remove"}, then choose Adjust this selection → Preview this photo’s result.'
            if not self.project:text='Load photo folder → draw around what to keep → Process photos.'
            self.mode_hint.configure(text=text)
        def change_mode(self):
            if self.project and self.mode.get()!=self.project.data['mode']:
                self.mode.set(self.project.data['mode']);messagebox.showinfo('Workflow is fixed for this project','Create a separate project for the other workflow so existing masks keep their meaning.',parent=self.root)
            self.set_mode_hint()
        def change_margin(self):
            if self.project and not self.busy:self.project.data['margin']=int(self.margin.get());self.project.save()
        def run(self,work):
            if self.busy:return
            self.busy=True;self.cancel.clear();self.cancel_button.configure(state='normal')
            for b in self.job_buttons:b.configure(state='disabled')
            def target():
                try:work()
                except BaseException as exc:self.events.put(('error',str(exc)))
                finally:self.events.put(('done',None))
            threading.Thread(target=target,daemon=True).start()
        def get_predictor(self):
            if self.predictor is None:
                if not (model_directory()/'config.json').is_file():
                    raise RuntimeError('The local processing model is missing. Extract the complete app download, or follow the source setup in the quick guide.')
                self.events.put(('status','Loading the local photo-processing model…'))
                self.predictor=core.Predictor(model_directory())
            return self.predictor
        def preview(self):
            if not self.project:return self.fail('Choose a photo group and project folder first.')
            index=self.index
            def work():
                core.process_one(self.project,index,self.get_predictor());self.events.put(('status','Preview ready. Add points if needed, or process the group.'))
            self.run(work)
        def batch(self,from_here=False):
            if not self.project:return self.fail('Load a photo folder first.')
            start=self.index if from_here else 0;self.progress.configure(maximum=len(self.project.data['photos']))
            rows=self.project.data['photos']
            first=next((i for i in range(start,len(rows)) if not rows[i].get('excluded')),None)
            if first is None:
                self.status.set('All photos are skipped. Restore a photo before processing.');return
            previous=rows[start-1] if start>0 else None
            can_resume=previous and previous.get('mask') and not core.tracking_uncertain(previous)
            if not (rows[first].get('points') or rows[first].get('box') or rows[first].get('approved') or can_resume):
                self.index=first;self.tree.selection_set(str(first));self.show_photo();self.tool.set('box');self.set_mode_hint()
                self.status.set('First, draw a box around what to keep. This tells the app which part of the photo is your subject.');return
            def work():
                predictor=self.get_predictor()
                core.process_group(self.project,predictor,self.cancel,lambda i,s:self.events.put(('progress',(i+1,s))),start)
                if self.cancel.is_set():self.events.put(('status','Processing stopped. Results were not updated; choose Process photos when ready to continue.'))
                else:self.export_results()
            self.run(work)
        def export_results(self):
            report=core.export(self.project,cancel=self.cancel)
            good=sum(r['status']=='exported' for r in report);bad=sum(r['status']=='error' for r in report)
            held=sum(not r.get('excluded') and r['status']!='Ready' and not r.get('approved') for r in self.project.data['photos'])
            self.events.put(('status',f'Saved {good} photos with masks. {held} need review; {bad} could not be saved. Choose Show results folder for the files to import into RealityScan.'))
        def export(self):
            if not self.project:return
            self.run(self.export_results)
        def open_output(self):
            if self.project:webbrowser.open((self.project.root/'Prepared Photos').as_uri())
        def poll(self):
            try:
                while True:
                    kind,value=self.events.get_nowait()
                    if kind=='status':self.status.set(value)
                    elif kind=='error':self.status.set('Stopped: '+value);self.fail(value)
                    elif kind=='progress':self.progress['value']=value[0];self.status.set(f'Photo {value[0]}: {value[1]}');self.refresh_tree()
                    elif kind=='done':
                        self.busy=False;self.cancel_button.configure(state='disabled')
                        for b in self.job_buttons:b.configure(state='normal')
                        if self.project:self.refresh_tree();self.show_photo()
                        self.update_controls()
            except queue.Empty:pass
            self.root.after(150,self.poll)
        def build_leaf_tab(self,ttk,tk,filedialog,messagebox):
            self.leaf_source=tk.StringVar();self.leaf_output=tk.StringVar();self.leaf_size=tk.IntVar(value=4096)
            self.leaf_orient=tk.BooleanVar(value=True);self.leaf_align=tk.BooleanVar(value=True);self.leaf_lighting=tk.BooleanVar(value=True)
            self.leaf_preserve=tk.BooleanVar(value=False)
            self.leaf_method=tk.StringVar(value='auto');self.leaf_keep_pieces=tk.BooleanVar(value=True)
            self.leaf_choices={};self.leaf_review=None
            bar=ttk.Frame(self.leaf_tab);bar.pack(fill='x',pady=6)
            self.leaf_load=ttk.Button(bar,text='Load photo folder…',command=self.choose_leaf_folder);self.leaf_load.pack(side='left',padx=3)
            self.leaf_run=ttk.Button(bar,text='Process cutouts',command=self.run_leaf);self.leaf_run.pack(side='left',padx=3)
            self.leaf_results_button=ttk.Button(bar,text='Show cutout results',command=self.open_leaf_output);self.leaf_results_button.pack(side='left',padx=3)
            more=ttk.Menubutton(bar,text='More options');more.pack(side='right',padx=3)
            menu=tk.Menu(more,tearoff=False);more.configure(menu=menu)
            self.leaf_menu=menu
            menu.add_command(label='Review leaf orientation and front/back pairs…',command=self.review_leaves)
            menu.add_checkbutton(label='Preserve existing artwork colors and alpha',variable=self.leaf_preserve,command=self.update_leaf_style)
            method_menu=tk.Menu(menu,tearoff=False)
            method_menu.add_radiobutton(label='Detailed subjects (recommended)',variable=self.leaf_method,value='auto')
            method_menu.add_radiobutton(label='Simple background (older method)',variable=self.leaf_method,value='classic')
            menu.add_cascade(label='Background removal method',menu=method_menu)
            menu.add_checkbutton(label='Keep separate objects and small pieces',variable=self.leaf_keep_pieces)
            menu.add_checkbutton(label='Turn clear leaf stems downward',variable=self.leaf_orient)
            menu.add_checkbutton(label='Align named front/back leaf pairs',variable=self.leaf_align)
            menu.add_checkbutton(label='Balance brightness and shadows',variable=self.leaf_lighting)
            menu.add_command(label='Load saved leaf settings…',command=self.choose_leaf_recipe)
            menu.add_separator()
            menu.add_command(label='Choose a different save folder…',command=self.choose_leaf_output)
            size=tk.Menu(menu,tearoff=False)
            for value in [1024,2048,4096,8192]:size.add_radiobutton(label=f'{value} × {value} pixels',variable=self.leaf_size,value=value)
            menu.add_cascade(label='Cutout image size',menu=size)
            menu.add_separator();menu.add_command(label='Read the quick guide',command=self.guide)
            self.job_buttons += [self.leaf_load,self.leaf_run,more]
            self.leaf_source.trace_add('write',lambda *_:self.update_controls())
            self.leaf_output.trace_add('write',lambda *_:self.update_controls())
            ttk.Label(self.leaf_tab,text='Load a photo folder, then choose Process cutouts. Results save in a new folder beside your photos.',wraplength=900).pack(anchor='w',pady=12,padx=3)
            self.leaf_description=ttk.Label(self.leaf_tab,text='Photo cutouts: automatic background removal, balanced brightness/shadows and optional leaf orientation/pairing. Review choices under More options.',wraplength=900);self.leaf_description.pack(anchor='w',padx=3,pady=(0,12))
            ttk.Label(self.leaf_tab,text='Photo folder:').pack(anchor='w',padx=3)
            ttk.Label(self.leaf_tab,textvariable=self.leaf_source,wraplength=900).pack(anchor='w',padx=12,pady=(0,12))
            ttk.Label(self.leaf_tab,text='Results folder:').pack(anchor='w',padx=3)
            ttk.Label(self.leaf_tab,textvariable=self.leaf_output,wraplength=900).pack(anchor='w',padx=12,pady=(0,20))
            ttk.Label(self.leaf_tab,text='This creates square cutout images for leaves, decals and artwork. For 3D scans, use Photos for 3D scanning to keep the original framing.',wraplength=900).pack(anchor='w',padx=3,pady=12)
        def choose_leaf_folder(self):
            if self.busy:return
            folder=filedialog.askdirectory(title='Choose photos to turn into cutouts',parent=self.root)
            if not folder:return
            try:output=create_results_folder(folder,'Cutouts')
            except OSError:
                output=filedialog.askdirectory(title='Choose where to save the cutouts',parent=self.root)
                if not output:return
            self.leaf_choices={};self.leaf_source.set(folder);self.leaf_output.set(str(output))
            self.status.set('Photo folder loaded. Choose Process cutouts; original photos stay untouched.')
        def choose_leaf_output(self):
            if self.busy:return
            folder=filedialog.askdirectory(title='Choose a separate folder for cutout results',parent=self.root)
            if folder:
                try:
                    from cutout_prep import leaf_batch
                    report=Path(folder)/leaf_batch.REPORT
                    if report.is_file():
                        saved=leaf_batch._read_report(report,Path(self.leaf_source.get()).resolve())
                        choices=leaf_batch.options(saved['options']);self.leaf_choices=choices
                        self.leaf_orient.set(choices['orient_stems']);self.leaf_align.set(choices['align_pairs']);self.leaf_lighting.set(choices['balance_lighting'])
                        self.leaf_preserve.set(choices['preserve_artwork']);self.leaf_method.set(choices['cutout_method']);self.leaf_keep_pieces.set(choices['keep_separate_objects']);self.update_leaf_style()
                    self.leaf_output.set(folder)
                except Exception as exc:self.fail(exc)
        def choose_leaf_recipe(self):
            path=filedialog.askopenfilename(title='Choose image-settings.json for leaf preparation',filetypes=[('Photo preparation settings','*.json')],parent=self.root)
            if path:
                try:
                    from cutout_prep.process_images import read_settings
                    read_settings(Path(path));self.leaf_choices['recipe']=path
                    self.status.set('Saved leaf settings selected. Their per-photo choices take priority over automatic orientation.')
                except Exception as exc:self.fail('Choose a photo-preparation recipe (image-settings.json). '+str(exc))
        def leaf_options(self):
            from cutout_prep import leaf_batch
            return leaf_batch.options({**self.leaf_choices,'orient_stems':bool(self.leaf_orient.get()),'align_pairs':bool(self.leaf_align.get()),'balance_lighting':bool(self.leaf_lighting.get()),'preserve_artwork':bool(self.leaf_preserve.get()),'cutout_method':self.leaf_method.get(),'keep_separate_objects':bool(self.leaf_keep_pieces.get())})
        def update_leaf_style(self):
            preserve=self.leaf_preserve.get()
            if preserve:self.leaf_orient.set(False);self.leaf_align.set(False);self.leaf_lighting.set(False);self.leaf_keep_pieces.set(True)
            for label in ('Turn clear leaf stems downward','Align named front/back leaf pairs','Balance brightness and shadows','Background removal method','Keep separate objects and small pieces'):
                self.leaf_menu.entryconfigure(label,state='disabled' if preserve else 'normal')
            self.leaf_description.configure(text='Prepared artwork: supplied colors, transparency and separate alpha pieces are kept. Automatic photo cleanup and geometry are disabled; explicit review choices can still be applied.' if preserve else 'Photo cutouts: automatic background removal, balanced brightness/shadows and optional leaf orientation/pairing. Review choices under More options.')
        def review_leaves(self):
            if self.busy:return
            if not self.leaf_source.get() or not self.leaf_output.get():return self.fail('Load a leaf photo folder first.')
            try:
                from cutout_prep.leaf_review import LeafReviewDialog
                choices=self.leaf_options();report=Path(self.leaf_output.get())/'LeafPreparation.json'
                if not self.leaf_choices and report.is_file():
                    saved=json.loads(report.read_text(encoding='utf-8'))
                    if saved.get('input_root')==str(Path(self.leaf_source.get()).resolve()):choices={**saved['options'],**{k:choices[k] for k in ('orient_stems','align_pairs','balance_lighting','preserve_artwork','cutout_method','keep_separate_objects')}}
                self.leaf_review=LeafReviewDialog(self.root,self.leaf_source.get(),self.leaf_output.get(),choices,self.apply_leaf_choices)
            except Exception as exc:self.fail(exc)
        def apply_leaf_choices(self,choices):
            self.leaf_choices=choices;self.leaf_orient.set(choices['orient_stems']);self.leaf_align.set(choices['align_pairs']);self.leaf_lighting.set(choices['balance_lighting'])
            self.leaf_preserve.set(choices['preserve_artwork']);self.leaf_method.set(choices['cutout_method']);self.leaf_keep_pieces.set(choices['keep_separate_objects']);self.update_leaf_style()
            self.run_leaf()
        def open_leaf_output(self):
            output=self.leaf_output.get()
            if output and Path(output).is_dir():webbrowser.open(Path(output).resolve().as_uri())
        def run_leaf(self):
            source=self.leaf_source.get();output=self.leaf_output.get();size=self.leaf_size.get()
            if not Path(source).is_dir() or not output:return self.fail('Choose both a photo folder and an output folder.')
            if Path(source).resolve()==Path(output).resolve():return self.fail('Choose an output folder separate from the original photo folder.')
            choices=self.leaf_options()
            def work():
                Path(output).mkdir(parents=True,exist_ok=True)
                descriptor,request=tempfile.mkstemp(prefix='.leaf-request-',suffix='.json',dir=output)
                with os.fdopen(descriptor,'w',encoding='utf-8') as stream:json.dump(choices,stream)
                command=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-m','cutout_prep.desktop'])+['--leaf-worker',source,output,str(size),'--leaf-options',request]
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                self.events.put(('status','Preparing artwork with supplied colors and transparency. This batch runs to completion.' if choices['preserve_artwork'] else 'Preparing lighting, cutouts and leaf orientation/pairs. This batch runs to completion.'))
                try:
                    with (Path(output)/'Cutout App.log').open('w',encoding='utf-8') as log:
                        self.child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=flags);code=self.child.wait();self.child=None
                finally:
                    if Path(request).resolve().is_relative_to(Path(output).resolve()):Path(request).unlink(missing_ok=True)
                if code not in (0,2):raise RuntimeError('Cutout processing stopped. See Cutout App.log in the output folder.')
                report=json.loads((Path(output)/'ProcessingReport.json').read_text(encoding='utf-8'));leaf=json.loads((Path(output)/'LeafPreparation.json').read_text(encoding='utf-8'))
                count=report['counts'].get('processed',0)+report['counts'].get('unchanged',0);review=report['counts'].get('review_required',0)
                pairs=sum(p['status'] in ('aligned','saved') for p in leaf['pairs']);errors=report['counts'].get('error',0)
                issue=f'; {errors} could not be processed' if errors else ''
                self.events.put(('status',f'Prepared {count} cutouts and {pairs} front/back pairs; {review} need review{issue}. Choose Show cutout results, or More options → Review leaf orientation and front/back pairs.'))
            self.run(work);self.cancel_button.configure(state='disabled')
        def close(self):
            if self.busy:
                self.cancel.set();self.status.set('Waiting for the current photo/batch to finish before closing.');self.root.after(300,self.close_when_idle);return
            if self.project:self.project.save();self.project.close()
            self.root.destroy()
        def close_when_idle(self):
            if self.busy:self.root.after(300,self.close_when_idle)
            else:self.close()
    root=tk.Tk();App(root);root.mainloop()
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        error=traceback.format_exc()
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror('Cutout Prep could not start',error)
        except Exception:pass
        raise
