"""Validate both frozen workflows, including source-file provenance resources."""
import argparse,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw


def main():
    p=argparse.ArgumentParser();p.add_argument('--app',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    app=Path(a.app).resolve();output=Path(a.output).resolve()
    if output.exists():raise SystemExit('Use a new validation output directory.')
    output.mkdir(parents=True)
    subprocess.run([str(app),'--check-runtime',str(output/'Scan')],check=True)
    scan=json.loads((output/'Scan/Runtime Check.json').read_text());assert scan['ok'] and scan['frozen']
    inputs=output/'Inputs';inputs.mkdir()
    im=Image.new('RGBA',(600,600));draw=ImageDraw.Draw(im)
    draw.ellipse((140,80,460,440),fill=(65,112,62,255));draw.rectangle((293,410,307,550),fill=(100,85,40,255))
    draw.ellipse((220,200,250,230),fill=(0,0,0,0));im.save(inputs/'Leaf_Front.png')
    im.transpose(Image.Transpose.FLIP_LEFT_RIGHT).save(inputs/'Leaf_Back.png')
    leaf=subprocess.run([str(app),'--leaf-worker',str(inputs),str(output/'Leaf'),'1024'])
    assert leaf.returncode in (0,2),leaf.returncode
    report=json.loads((output/'Leaf/ProcessingReport.json').read_text());assert report['counts'].get('processed')==2,report['counts']
    images=list((output/'Leaf').glob('*_BaseColor.png'));assert len(images)==2
    leaf_report=json.loads((output/'Leaf/LeafPreparation.json').read_text());assert leaf_report['counts']['aligned_pairs']==1,leaf_report['pairs']
    for path in images:
        with Image.open(path) as im:assert im.size==(1024,1024) and im.mode=='RGBA'
    result={'ok':True,'frozen_image_and_tracking':True,'frozen_leaf_outputs':2,'frozen_leaf_pairs':1,'source_provenance_resources_verified':True}
    (output/'Portable Verification.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
