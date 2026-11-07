"""Portable Cutout Prep UI. Windows/macOS source; CPU-only, offline processing."""
from __future__ import annotations
import argparse, contextlib, copy, json, os, queue, runpy, subprocess, sys, threading, traceback, webbrowser
from pathlib import Path

def resources():return Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent/'resources'))

def model_directory():
    bundled=resources()/'models/sam2-tiny'
    return Path(os.environ.get('CUTOUT_PREP_MODEL_DIR',str(bundled)))

def leaf_worker(source,output,size):
    from cutout_prep import process_images
    return process_images.main([source,'--output',output,'--size',str(size)])

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
    p=argparse.ArgumentParser();p.add_argument('--leaf-worker',nargs=3);p.add_argument('--check-runtime');p.add_argument('--project');p.add_argument('--smoke',action='store_true');args=p.parse_args()
    if args.check_runtime:return check_runtime(args.check_runtime)
    if args.leaf_worker:
        Path(args.leaf_worker[1]).mkdir(parents=True,exist_ok=True)
        with (Path(args.leaf_worker[1])/'Leaf Worker.log').open('w',encoding='utf-8') as log,contextlib.redirect_stdout(log),contextlib.redirect_stderr(log):
            try:return leaf_worker(*args.leaf_worker)
            except Exception:traceback.print_exc();return 1
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    import numpy as np
    from PIL import Image,ImageTk
    from cutout_prep import scan_core as core

    class App:
        def __init__(self,root):
            self.root=root;self.project=None;self.index=0;self.predictor=None;self.photo=None;self.mask=None;self.display=None;self.bounds=(0,0,1,1);self.box_start=None;self.busy=False;self.cancel=threading.Event();self.events=queue.Queue();self.history={};self.child=None
            root.title('Cutout Prep — Photos & Scan Masks');root.geometry('1180x760');root.minsize(980,620)
            self.status=tk.StringVar(value='Choose photos or a folder, then choose a project folder. Originals stay untouched.')
            self.mode=tk.StringVar(value='object');self.tool=tk.StringVar(value='box');self.view=tk.StringVar(value='overlay');self.margin=tk.IntVar(value=0);self.allow_border=tk.BooleanVar(value=False)
            style=ttk.Style();style.theme_use('clam');style.configure('TButton',padding=(9,5));style.configure('TLabel',padding=2)
            notebook=ttk.Notebook(root);notebook.pack(fill='both',expand=True,padx=10,pady=8)
            self.scan_tab=ttk.Frame(notebook);self.leaf_tab=ttk.Frame(notebook);notebook.add(self.scan_tab,text='Scan masks');notebook.add(self.leaf_tab,text='Leaf & image cutouts')
            top=ttk.Frame(self.scan_tab);top.pack(fill='x')
            self.job_buttons=[]
            for text,command in [('Choose photos…',self.choose_files),('Choose folder…',self.choose_folder),('Open project…',self.open_project),('Save',self.save),('Guide',self.guide)]:
                b=ttk.Button(top,text=text,command=command);b.pack(side='left',padx=3,pady=4)
                if text not in ['Save','Guide']:self.job_buttons.append(b)
            options=ttk.Frame(self.scan_tab);options.pack(fill='x',pady=3)
            ttk.Label(options,text='Workflow:').pack(side='left')
            for text,value in [('Keep one object / target area','object'),('Keep scene, remove a distraction','scene')]:ttk.Radiobutton(options,text=text,variable=self.mode,value=value,command=self.change_mode).pack(side='left',padx=5)
            self.mode_hint=ttk.Label(self.scan_tab,text='Draw a box around the rock, leaf, log, or other target. Keep/Remove clicks refine its boundary.')
            self.mode_hint.pack(fill='x')
            self.border_check=ttk.Checkbutton(self.scan_tab,text='Target may continue beyond photo edges (cliffs / large surfaces)',variable=self.allow_border,command=self.change_border)
            self.border_check.pack(anchor='w',padx=3);self.job_buttons.append(self.border_check)
            tools=ttk.Frame(self.scan_tab);tools.pack(fill='x')
            for text,value in [('Box','box'),('Keep point','keep'),('Remove point','remove')]:ttk.Radiobutton(tools,text=text,variable=self.tool,value=value).pack(side='left',padx=4)
            for text,cmd in [('Undo',self.undo),('Clear selection',self.clear),('Preview mask',self.preview),('Approve view',self.approve),('Exclude / include',self.exclude)]:
                b=ttk.Button(tools,text=text,command=cmd);b.pack(side='left',padx=3)
                if text=='Preview mask':self.job_buttons.append(b)
            ttk.Label(tools,text='Edge margin:').pack(side='left',padx=(10,0));ttk.Spinbox(tools,from_=-5,to=5,width=3,textvariable=self.margin,command=self.change_margin).pack(side='left')
            panes=ttk.Panedwindow(self.scan_tab,orient='horizontal');panes.pack(fill='both',expand=True,pady=6)
            left=ttk.Frame(panes);right=ttk.Frame(panes);panes.add(left,weight=1);panes.add(right,weight=5)
            self.tree=ttk.Treeview(left,columns=('state',),show='tree headings',selectmode='browse',height=16);self.tree.heading('#0',text='Photograph');self.tree.heading('state',text='Status');self.tree.column('#0',width=175);self.tree.column('state',width=80);self.tree.pack(side='left',fill='both',expand=True)
            scroll=ttk.Scrollbar(left,orient='vertical',command=self.tree.yview);scroll.pack(side='right',fill='y');self.tree.configure(yscrollcommand=scroll.set);self.tree.bind('<<TreeviewSelect>>',self.select)
            self.canvas=tk.Canvas(right,bg='#25282d',highlightthickness=0);self.canvas.pack(fill='both',expand=True);self.canvas.bind('<Configure>',lambda e:self.draw());self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.drag);self.canvas.bind('<ButtonRelease-1>',self.release)
            foot=ttk.Frame(right);foot.pack(fill='x');ttk.Button(foot,text='◀ Previous',command=lambda:self.navigate(-1)).pack(side='left');ttk.Button(foot,text='Next ▶',command=lambda:self.navigate(1)).pack(side='left')
            for text,value in [('Overlay','overlay'),('Black/white mask','mask'),('Original','original')]:ttk.Radiobutton(foot,text=text,variable=self.view,value=value,command=self.draw).pack(side='left',padx=4)
            ttk.Button(foot,text='Next review',command=self.next_review).pack(side='right')
            self.detail=tk.StringVar(value='No project open.');ttk.Label(self.scan_tab,textvariable=self.detail,wraplength=1100).pack(fill='x')
            bottom=ttk.Frame(self.scan_tab);bottom.pack(fill='x',pady=4)
            for text,cmd in [('Process group',self.batch),('Process from this view',lambda:self.batch(True)),('Export ready / approved photos',self.export),('Open output folder',self.open_output)]:
                b=ttk.Button(bottom,text=text,command=cmd);b.pack(side='left',padx=3)
                if text!='Open output folder':self.job_buttons.append(b)
            self.cancel_button=ttk.Button(bottom,text='Cancel after this photo',command=self.cancel.set,state='disabled');self.cancel_button.pack(side='right')
            self.progress=ttk.Progressbar(self.scan_tab,mode='determinate');self.progress.pack(fill='x',pady=2)
            ttk.Label(root,textvariable=self.status,wraplength=1140).pack(fill='x',padx=12,pady=(0,8))
            self.build_leaf_tab(ttk,tk,filedialog,messagebox)
            root.protocol('WM_DELETE_WINDOW',self.close);root.bind('<Control-z>',lambda e:self.undo())
            if sys.platform=='darwin':root.bind('<Command-z>',lambda e:self.undo())
            root.after(150,self.poll)
            if args.project:self.load_project(Path(args.project))
            if args.smoke:root.after(1000,lambda:self.status.set('UI smoke check ready.'))
        def fail(self,error):messagebox.showerror('Cutout Prep',str(error),parent=self.root)
        def guide(self):webbrowser.open((resources()/'Guide.html').as_uri())
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
        def create(self,paths):
            if self.busy:return
            dest=filedialog.askdirectory(title='Choose an empty project/output folder',parent=self.root)
            if not dest:return
            try:self.replace_project(core.Project.create(paths,dest,self.mode.get()))
            except Exception as exc:self.fail(exc)
        def choose_files(self):
            paths=filedialog.askopenfilenames(title='Choose scan photographs',filetypes=[('Photographs','*.jpg *.jpeg *.png *.tif *.tiff *.heic *.heif *.webp *.bmp'),('All files','*')],parent=self.root)
            if paths:self.create(paths)
        def choose_folder(self):
            folder=filedialog.askdirectory(title='Choose the folder containing scan photos',parent=self.root)
            if folder:self.create([p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in core.EXTENSIONS and '.mask.' not in p.name.lower()])
        def open_project(self):
            f=filedialog.askopenfilename(title='Open Scan Project.json',filetypes=[('Scan project','*.json')],parent=self.root)
            if f:self.load_project(Path(f))
        def load_project(self,path):
            try:self.replace_project(core.Project.open(path))
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
                warnings=' '.join(r.get('warnings',[]));score=r.get('score');score_text=f' · model score {score:.2f}' if score is not None else ''
                self.detail.set(f'{self.index+1}/{len(self.project.data["photos"])} · {r["size"][0]}×{r["size"][1]} · {r["status"]}{score_text}  {warnings}')
            except Exception as exc:self.fail(exc)
        def draw(self):
            self.canvas.delete('all')
            if self.photo is None:
                self.canvas.create_text(max(200,self.canvas.winfo_width()/2),150,text='Choose a photo group to begin',fill='white',font=('TkDefaultFont',17));return
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
            r=self.row();r['approved']=False;r['status']='Selection changed';self.project.save();self.refresh_tree();self.draw()
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
            r['mask_sha256']=core.digest(path);r['approved']=True;r['status']='Approved';self.project.save();self.refresh_tree();self.show_photo()
        def exclude(self):
            if not self.project or self.busy:return
            r=self.row();r['excluded']=not r.get('excluded',False);self.project.save();self.refresh_tree();self.show_photo()
        def set_mode_hint(self):
            self.mode_hint.configure(text=('Draw a box around the target. Keep/Remove points refine the rock, log, plant, or other subject.' if self.mode.get()=='object' else 'Draw a box around a distraction to remove. Remove points select it; Keep points protect the scene. Start a new anchor when the distraction changes.'))
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
                self.events.put(('status','Loading local segmentation model on CPU…'))
                self.predictor=core.Predictor(model_directory())
            return self.predictor
        def preview(self):
            if not self.project:return self.fail('Choose a photo group and project folder first.')
            index=self.index
            def work():
                core.process_one(self.project,index,self.get_predictor());self.events.put(('status','Preview ready. Add points if needed, or process the group.'))
            self.run(work)
        def batch(self,from_here=False):
            if not self.project:return self.fail('Choose a photo group and project folder first.')
            start=self.index if from_here else 0;self.progress.configure(maximum=len(self.project.data['photos']))
            def work():
                predictor=self.get_predictor()
                core.process_group(self.project,predictor,self.cancel,lambda i,s:self.events.put(('progress',(i+1,s))),start)
                self.events.put(('status','Processing stopped.' if self.cancel.is_set() else 'Group processed. Inspect Review/Error views, then export the ready and approved photos.'))
            self.run(work)
        def export(self):
            if not self.project:return
            def work():
                report=core.export(self.project,cancel=self.cancel);good=sum(r['status']=='exported' for r in report);bad=sum(r['status']=='error' for r in report);held=sum(r['status'].startswith('not_exported') for r in report)
                self.events.put(('status',f'Exported {good} photos with matching masks. {held} need review; {bad} errors. See Export Report.json.'))
            self.run(work)
        def open_output(self):
            if self.project:webbrowser.open(self.project.root.as_uri())
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
            except queue.Empty:pass
            self.root.after(150,self.poll)
        def build_leaf_tab(self,ttk,tk,filedialog,messagebox):
            ttk.Label(self.leaf_tab,text='Prepare leaves and isolated image cutouts',font=('TkDefaultFont',16)).pack(anchor='w',pady=(15,8),padx=15)
            ttk.Label(self.leaf_tab,text='Uses the established leaf processor. This workflow crops, centers and resizes; use Scan masks for photogrammetry.',wraplength=1000).pack(anchor='w',padx=15)
            self.leaf_source=tk.StringVar();self.leaf_output=tk.StringVar();self.leaf_size=tk.IntVar(value=4096)
            for label,var in [('Photo folder',self.leaf_source),('Output folder',self.leaf_output)]:
                frame=ttk.Frame(self.leaf_tab);frame.pack(fill='x',padx=15,pady=10);ttk.Label(frame,text=label,width=15).pack(side='left');ttk.Entry(frame,textvariable=var).pack(side='left',fill='x',expand=True)
                def choose(v=var):
                    value=filedialog.askdirectory(parent=self.root)
                    if value:v.set(value)
                ttk.Button(frame,text='Browse…',command=choose).pack(side='left',padx=5)
            f=ttk.Frame(self.leaf_tab);f.pack(fill='x',padx=15,pady=8);ttk.Label(f,text='Square size').pack(side='left');ttk.Combobox(f,textvariable=self.leaf_size,values=[1024,2048,4096,8192],width=8,state='readonly').pack(side='left',padx=8)
            self.leaf_run=ttk.Button(self.leaf_tab,text='Prepare cutouts',command=self.run_leaf);self.leaf_run.pack(anchor='w',padx=15,pady=8);self.job_buttons.append(self.leaf_run)
            ttk.Label(self.leaf_tab,text='Choose a new output folder for a new batch. Originals and manually edited exports are protected. Complex backgrounds work better in Scan masks with a subject selection.',wraplength=1000).pack(anchor='w',padx=15,pady=12)
        def run_leaf(self):
            source=self.leaf_source.get();output=self.leaf_output.get();size=self.leaf_size.get()
            if not Path(source).is_dir() or not output:return self.fail('Choose both a photo folder and an output folder.')
            if Path(source).resolve()==Path(output).resolve():return self.fail('Choose an output folder separate from the original photo folder.')
            def work():
                Path(output).mkdir(parents=True,exist_ok=True)
                command=([sys.executable] if getattr(sys,'frozen',False) else [sys.executable,'-m','cutout_prep.desktop'])+['--leaf-worker',source,output,str(size)]
                flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
                self.events.put(('status','Preparing leaf/image cutouts. This batch runs to completion.'))
                with (Path(output)/'Cutout App.log').open('w',encoding='utf-8') as log:
                    self.child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,creationflags=flags);code=self.child.wait();self.child=None
                if code not in (0,2):raise RuntimeError('Cutout processing stopped. See Cutout App.log in the output folder.')
                self.events.put(('status','Cutouts prepared. Inspect Preview.jpg and ProcessingReport.json in the output folder.'))
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
