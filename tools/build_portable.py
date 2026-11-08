"""Build the desktop on its native OS, with a separately supplied local model."""
import argparse,hashlib,importlib.metadata,json,os,platform,plistlib,shutil,subprocess,sys
from pathlib import Path
from packaging.requirements import Requirement


def main():
    p=argparse.ArgumentParser();p.add_argument('--dist',required=True);p.add_argument('--work',required=True);p.add_argument('--model-dir',required=True);p.add_argument('--cutout-model-dir',required=True);p.add_argument('--incremental',action='store_true');a=p.parse_args()
    repo=Path(__file__).resolve().parents[1];package=repo/'src/cutout_prep';dist=Path(a.dist).resolve();work=Path(a.work).resolve();model=Path(a.model_dir).resolve();work.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(repo/'src'))
    from cutout_prep import __version__
    if sys.platform=='darwin':
        import cv2
        if any('x264' in p.name.lower() or 'x265' in p.name.lower() for p in Path(cv2.__file__).parent.rglob('*.dylib')):
            raise SystemExit('Use tools/build_macos_opencv.sh before packaging: this app does not need bundled video encoders.')
    fingerprints={str(path.relative_to(repo)).replace('\\','/'):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(package.rglob('*')) if path.is_file() and '__pycache__' not in path.parts}
    manifest=json.loads((repo/'tools/model-manifest.json').read_text())
    for name,row in manifest['files'].items():
        path=model/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Missing or mismatched model file: '+name)
    cutout_manifest=json.loads((repo/'tools/cutout-model-manifest.json').read_text())
    cutout_model=Path(a.cutout_model_dir).resolve();cutout_stage=work/'cutout-model'
    cutout_stage.mkdir(exist_ok=True)
    allowed=set(cutout_manifest['files'])|{'LICENSE','manifest.json'}
    if any(p.name not in allowed or not p.is_file() for p in cutout_stage.iterdir()):raise SystemExit('Preserve unexpected detailed-model staging files')
    for name,row in cutout_manifest['files'].items():
        path=cutout_model/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Missing or mismatched detailed model file: '+name)
        shutil.copy2(path,cutout_stage/name)
    shutil.copy2(repo/'tools/BiRefNet-LICENSE',cutout_stage/'LICENSE')
    (cutout_stage/'manifest.json').write_text(json.dumps(cutout_manifest,indent=2)+'\n',encoding='utf-8')
    licenses=work/'licenses';licenses.mkdir(exist_ok=True)
    pending=['Pillow','numpy','opencv-python-headless','scipy','pi-heif','rawpy','torch','torchvision','transformers','safetensors','pyinstaller','onnxruntime'];seen=set()
    versions={}
    while pending:
        name=pending.pop();key=name.lower().replace('_','-')
        if key in seen:continue
        seen.add(key);d=importlib.metadata.distribution(name);versions[d.metadata['Name']]=d.version
        for requirement in d.requires or []:
            r=Requirement(requirement)
            if r.marker is None or r.marker.evaluate({'extra':''}):pending.append(r.name)
        for f in d.files or []:
            if any(word in Path(f).name.lower() for word in ['license','notice','copying']):
                actual=Path(d.locate_file(f))
                if actual.is_file():
                    dest=licenses/(d.metadata['Name']+'-'+d.version)/str(f)
                    dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(actual,dest)
    for candidate in [Path(sys.base_prefix)/'LICENSE.txt',Path(sys.base_prefix)/'LICENSE']:
        if candidate.is_file():shutil.copy2(candidate,licenses/'Python-LICENSE.txt');break
    data=[(model,'models/sam2-tiny'),(package/'resources/Guide.html','.'),(package/'sRGB.icc','cutout_prep'),(repo/'LICENSE','.'),(repo/'THIRD_PARTY_NOTICES.md','.'),(repo/'tools/SAM2-LICENSE','models/sam2-tiny'),(licenses,'licenses')]
    data.append((cutout_stage,'models/birefnet-lite'))
    command=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--name','Cutout Prep','--distpath',str(dist),'--workpath',str(work/'pyinstaller'),'--specpath',str(work),'--paths',str(repo/'src'),'--additional-hooks-dir',str(repo/'tools/hooks')]
    if not a.incremental:command+=['--clean']
    if sys.platform=='darwin':command+=['--osx-bundle-identifier','io.github.gnomecannon.cutout-prep']
    for src,dest in data:command+=['--add-data',str(src)+os.pathsep+dest]
    for module in ['cutout_prep.process_images','cutout_prep.scan_core','cutout_prep.neural_cutout','onnxruntime','rawpy','pi_heif','scipy.ndimage','PIL._tkinter_finder','transformers.models.sam2.modeling_sam2','transformers.models.sam2.processing_sam2','transformers.models.sam2.image_processing_sam2','transformers.models.sam2.configuration_sam2']:
        command+=['--hidden-import',module]
    for module in ['pillow_heif','pytest','IPython','notebook','tensorflow','jax','torchaudio','matplotlib','tensorboard']:
        command+=['--exclude-module',module]
    command+=[str(package/'desktop.py')]
    env=dict(os.environ,HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='',PYTHONPATH=str(repo/'src'))
    subprocess.run(command,check=True,env=env)
    for name,sha in fingerprints.items():
        if hashlib.sha256((repo/name).read_bytes()).hexdigest()!=sha:raise SystemExit('App source changed during build: '+name)
    app=dist/('Cutout Prep.app' if sys.platform=='darwin' else 'Cutout Prep');extras=dist if sys.platform=='darwin' else app
    if sys.platform=='darwin':
        info=app/'Contents/Info.plist'
        with info.open('rb') as f:metadata=plistlib.load(f)
        metadata.update(CFBundleShortVersionString=__version__,CFBundleVersion=__version__)
        with info.open('wb') as f:plistlib.dump(metadata,f)
        subprocess.run(['codesign','--force','--deep','--sign','-',str(app)],check=True)
    for name,source in [('Guide.html',package/'resources/Guide.html'),('LICENSE',repo/'LICENSE'),('THIRD_PARTY_NOTICES.md',repo/'THIRD_PARTY_NOTICES.md')]:shutil.copy2(source,extras/name)
    (extras/'BUILD_INFO.json').write_text(json.dumps({'version':__version__,'platform':platform.platform(),'architecture':platform.machine(),'python':platform.python_version(),'source_sha256':fingerprints,'packages':versions,'model':manifest,'cutout_model':cutout_manifest,'opencv_profile':'image-only local build' if sys.platform=='darwin' else 'upstream Windows wheel'},indent=2)+'\n',encoding='utf-8')
    print(app)


if __name__=='__main__':main()
