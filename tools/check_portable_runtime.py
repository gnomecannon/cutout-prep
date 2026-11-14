"""Validate both frozen workflows, including source-file provenance resources."""
import argparse,json,os,subprocess,sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage as ndi
from shape_fixtures import photograph,specimen


def main():
    p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    app=Path(a.app).resolve();output=Path(a.output).resolve()
    if output.exists():raise SystemExit('Use a new validation output directory.')
    output.mkdir(parents=True)
    env=dict(os.environ)
    for key in ('CUTOUT_PREP_MODEL_DIR','CUTOUT_PREP_2D_MODEL_DIR'):env.pop(key,None)
    subprocess.run([str(app),'--check-runtime',str(output/'Scan')],check=True,env=env)
    scan=json.loads((output/'Scan/Runtime Check.json').read_text());assert scan['ok'] and scan['frozen']
    inputs=output/'Inputs';inputs.mkdir()
    im=specimen('damaged');im.save(inputs/'Leaf_Front.png')
    im.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(inputs/'Leaf_Back.png')
    leaf=subprocess.run([str(app),'--leaf-worker',str(inputs),str(output/'Leaf'),'1024'],env=env)
    assert leaf.returncode in (0,2),leaf.returncode
    report=json.loads((output/'Leaf/ProcessingReport.json').read_text());assert report['counts'].get('processed')==2,report['counts']
    images=list((output/'Leaf').glob('*_BaseColor.png'));assert len(images)==2
    leaf_report=json.loads((output/'Leaf/LeafPreparation.json').read_text());assert leaf_report['counts']['aligned_pairs']==1,leaf_report['pairs']
    masks=[]
    for path in images:
        with Image.open(path) as im:
            assert im.size==(1024,1024) and im.mode=='RGBA'
            mask=np.array(im.getchannel('A'))>=128;masks.append(mask)
        holes=ndi.binary_fill_holes(mask)&~mask
        sizes=np.bincount(ndi.label(holes)[0].ravel())[1:]
        assert int((sizes>=9).sum())==2,'Two photographed holes must stay open'
        assert ndi.label(mask,np.ones((3,3)))[1]==1,'The thin stem must stay connected'
        assert not (mask[:12].any() or mask[-12:].any() or mask[:,:12].any() or mask[:,-12:].any())
    assert (masks[0]&masks[1]).sum()/(masks[0]|masks[1]).sum()>.96
    opaque=output/'Opaque Inputs';opaque.mkdir();photograph('damaged').save(opaque/'Object.png')
    choices=output/'Detailed Options.json';choices.write_text(json.dumps({'cutout_method':'detailed','orient_stems':False,'align_pairs':False}))
    detailed=subprocess.run([str(app),'--leaf-worker',str(opaque),str(output/'Detailed'),'1024','--leaf-options',str(choices)],env=env)
    assert detailed.returncode in (0,2)
    detail=json.loads((output/'Detailed/ProcessingReport.json').read_text());assert detail['counts'].get('processed')==1,detail['files']
    expected=json.loads(Path(__file__).with_name('cutout-model-manifest.json').read_text())['files']['model.onnx']['sha256']
    assert detail['files'][0]['cutout']['model_sha256']==expected
    subprocess.run([sys.executable,str(Path(__file__).with_name('check_fern_quality.py')),
                    '--app',str(app),'--output',str(output/'Real Fern')],check=True)
    result={'ok':True,'frozen_image_and_tracking':True,'frozen_leaf_outputs':2,'frozen_leaf_pairs':1,'frozen_leaf_holes_preserved':2,'frozen_detailed_backend':True,'leaf_fixture':'procedural lobed leaf, narrow stem and irregular holes; dependency/workflow check, not a real-photo accuracy test','source_provenance_resources_verified':True}
    result['frozen_approved_fern_reference']=True
    (output/'Portable Verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
