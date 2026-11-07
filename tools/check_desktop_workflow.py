"""Exercise native Tk callbacks with procedural inputs and supplied picker results.

This tests authoring/save/reopen/cancel/export/leaf integration, not human picker
interaction. Run with the desktop dependencies and a local model available.
"""
import argparse,json,os,sys,time,traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--model-dir',required=True);a=p.parse_args()
    output=Path(a.output).resolve()
    if output.exists():raise SystemExit('Use a new, empty validation output path.')
    output.mkdir(parents=True);photos=output/'Inputs';photos.mkdir()
    from PIL import Image,ImageDraw
    for i in range(3):
        im=Image.new('RGB',(1000,900),'#ece7dc');d=ImageDraw.Draw(im);d.ellipse((240+i*6,180,760+i*6,760),fill=(65+i*3,112,62));im.save(photos/f'fixture-{i}.png')
    source=str(Path(__file__).resolve().parents[1]/'src');sys.path.insert(0,source)
    os.environ['PYTHONPATH']=source+os.pathsep+os.environ.get('PYTHONPATH','')
    os.environ['CUTOUT_PREP_MODEL_DIR']=str(Path(a.model_dir).resolve())
    os.environ['OMP_NUM_THREADS']='4'
    import tkinter as tk
    from tkinter import ttk,filedialog,messagebox
    from cutout_prep import desktop,scan_core as core
    real_tk=tk.Tk;real_button=ttk.Button;captured={};result={'picker_results_supplied':True,'native_picker_interaction_tested':False};phase=[0];deadline=time.monotonic()+240
    def button(*args,**kwargs):
        owner=getattr(kwargs.get('command'),'__self__',None)
        if owner is not None and owner.__class__.__name__=='App':captured['app']=owner
        return real_button(*args,**kwargs)
    def fail(*args,**kwargs):raise RuntimeError(str(args))
    def tick():
        root=captured['root'];app=captured.get('app')
        try:
            if time.monotonic()>deadline:raise TimeoutError('Desktop workflow timed out')
            if app is None or app.busy:root.after(100,tick);return
            n=phase[0];phase[0]+=1
            if n==0:
                assert str(app.process_button['state'])=='disabled'
                with patch.object(filedialog,'askdirectory',return_value=str(photos)) as picker:app.choose_folder()
                assert picker.call_count==1
                assert len(app.project.data['photos'])==3
                assert app.project.root.parent==photos.parent and app.project.root!=photos
                app.batch();assert not app.busy and app.predictor is None
                result['one_folder_picker_and_selection_guidance']=True
            elif n==1:
                app.allow_border.set(True);app.change_border();x,y,w,h=app.bounds
                app.press(SimpleNamespace(x=x+w*.18,y=y+h*.12));app.release(SimpleNamespace(x=x+w*.85,y=y+h*.9));assert app.row()['box']
                app.batch()
            elif n==2:
                assert app.project.read_mask(app.row()) is not None
                report=json.loads((app.project.root/'Export Report.json').read_text())
                assert sum(r['status']=='exported' for r in report['photos'])==3
                result['process_button_saves_results_automatically']=True
                before=list(app.row()['points']);app.tool.set('keep');x,y,w,h=app.bounds
                app.press(SimpleNamespace(x=x+w*.5,y=y+h*.5));app.undo();assert app.row()['points']==before
                app.preview()
            elif n==3:
                app.save();path=app.project.root/'Scan Project.json';app.project.close();app.project=None;app.load_project(path)
                assert app.allow_border.get() and app.row()['box'];app.batch();app.cancel.set()
            elif n==4:
                result['cancellation_reached_idle']=True;app.batch()
            elif n==5:
                assert all(r['mask'] for r in app.project.data['photos']);app.approve()
            elif n==6:
                report=json.loads((app.project.root/'Export Report.json').read_text());exported=[r for r in report['photos'] if r['status']=='exported'];assert len(exported)==3,report['photos']
                for row in exported:
                    assert core.digest(app.project.root/'Prepared Photos'/row['file'])==row['source_sha256']
                    with Image.open(app.project.root/'Prepared Photos'/row['mask']) as im:assert list(im.size)==row['raw_size']
                result['scan_exports_verified']=3
                with patch.object(filedialog,'askdirectory',return_value=str(photos)) as picker:app.choose_leaf_folder()
                assert picker.call_count==1 and Path(app.leaf_output.get()).parent==photos.parent
                app.leaf_size.set(1024);app.run_leaf()
            elif n==7:
                report=json.loads((Path(app.leaf_output.get())/'ProcessingReport.json').read_text());assert report['counts'].get('processed')==3,report['counts']
                result['leaf_outputs_verified']=3;urls=[]
                with patch.object(desktop.webbrowser,'open',side_effect=lambda url:urls.append(url)):app.guide()
                assert urls and (desktop.resources()/'Guide.html').is_file()
                result.update(ok=True,box_points_undo=True,save_reopen=True,edge_setting_persisted=True,guide_resource_verified=True)
                (output/'Desktop Workflow.json').write_text(json.dumps(result,indent=2)+'\n');app.close();return
            root.after(150,tick)
        except Exception:
            result.update(ok=False,error=traceback.format_exc());(output/'Desktop Workflow.json').write_text(json.dumps(result,indent=2)+'\n')
            if app and app.project:app.project.close()
            root.destroy()
    def root(*args,**kwargs):
        widget=real_tk(*args,**kwargs);captured['root']=widget
        def callback_error(kind,value,tb):
            result.update(ok=False,error=''.join(traceback.format_exception(kind,value,tb)))
            (output/'Desktop Workflow.json').write_text(json.dumps(result,indent=2)+'\n')
            app=captured.get('app')
            if app and app.project:app.project.close()
            widget.destroy()
        widget.report_callback_exception=callback_error
        widget.after(800,tick);return widget
    with patch.object(tk,'Tk',side_effect=root),patch.object(ttk,'Button',side_effect=button),patch.object(messagebox,'showerror',side_effect=fail),patch.object(sys,'argv',['cutout-prep-gui']):desktop.main()
    print(json.dumps(result,indent=2))
    return 0 if result.get('ok') else 1


if __name__=='__main__':raise SystemExit(main())
