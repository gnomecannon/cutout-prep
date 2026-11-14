"""Check a packaged app against the approved real-photo fern reference."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image,ImageDraw,ImageFont
from scipy import ndimage as ndi


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--app',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    output=Path(args.output).resolve();app=Path(args.app).resolve()
    if output.exists():raise SystemExit('Use a new fern validation output folder.')
    fixture=Path(__file__).resolve().parents[1]/'tests/fixtures/fern-paper'
    source=fixture/'source.jpg';expected=Image.open(fixture/'accepted-mask.png').convert('L')
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    original=sha(source)
    output.mkdir(parents=True);inputs=output/'Inputs';inputs.mkdir()
    shutil.copy2(source,inputs/'Fern.jpg')
    choices=output/'Options.json'
    choices.write_text(json.dumps({'orient_stems':False,'align_pairs':False,'balance_lighting':False,'cutout_method':'detailed'}))
    env=dict(os.environ,HF_HUB_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1',CUDA_VISIBLE_DEVICES='')
    for key in ('CUTOUT_PREP_MODEL_DIR','CUTOUT_PREP_2D_MODEL_DIR'):env.pop(key,None)
    with (output/'Worker.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([str(app),'--leaf-worker',str(inputs),str(output/'Results'),'1536','--leaf-options',str(choices)],
                              env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300)
    assert result.returncode in (0,2), 'Fern worker failed; inspect Worker.log'
    report=json.loads((output/'Results/ProcessingReport.json').read_text())
    record=next(r for r in report['files'] if r.get('source')=='Fern.jpg')
    assert record['status']=='processed',record
    info=record['cutout'];assert info['paper_foliage_applied']
    dest=output/'Results'/record['output']
    assert sha(dest)==report['outputs'][record['output']]['output_sha256']
    actual=Image.open(dest).convert('RGBA');alpha=np.array(actual.getchannel('A'))
    # Project the independent accepted alpha through the worker's recorded
    # source-to-output framing. There is no best-fit registration or elastic warp.
    bbox=record['source_bbox'];size=record['output_size'][0];padding=record['settings']['padding']
    reference=np.array(expected)
    inside=np.zeros(reference.shape,bool);inside[bbox[1]:bbox[3],bbox[0]:bbox[2]]=True
    clipped=int(((reference>=128)&~inside).sum())
    assert clipped<np.count_nonzero(reference>=128)*.005, 'Output framing lost captured fern tissue'
    cropped=expected.crop(bbox);scale=(size-2*padding)/max(cropped.size)
    dims=tuple(max(1,round(v*scale)) for v in cropped.size)
    framed=Image.new('L',(size,size));framed.paste(cropped.resize(dims,Image.Resampling.LANCZOS),((size-dims[0])//2,(size-dims[1])//2))
    ref=np.array(framed)>=128;mask=alpha>=128
    iou=float((mask&ref).sum()/(mask|ref).sum())
    recall=float((mask&ref).sum()/ref.sum())
    extra=float((mask&~ref).sum()/mask.sum())
    labels,count=ndi.label(mask,structure=np.ones((3,3)));sizes=np.bincount(labels.ravel())[1:]
    detached=max(sorted(sizes,reverse=True)[1:],default=0)
    assert iou>.975 and recall>.99 and extra<.018,(iou,recall,extra)
    assert detached<max(16,round(ref.sum()*.0001)), 'A significant frond is detached'
    assert info['uncertain_connections']==0
    assert sha(source)==original and sha(inputs/'Fern.jpg')==original
    board=Image.new('RGB',(1800,650),'#30353b');draw=ImageDraw.Draw(board)
    for col,(name,bg) in enumerate([('Black',(0,0,0)),('Magenta',(210,0,170)),('White',(255,255,255))]):
        tile=Image.new('RGBA',actual.size,(*bg,255));tile.alpha_composite(actual)
        tile=tile.convert('RGB');tile.thumbnail((600,600),Image.Resampling.LANCZOS)
        board.paste(tile,(600*col,35));draw.text((600*col+8,7),name,font=ImageFont.load_default(size=20),fill='white')
    board.save(output/'Fern Review.jpg',quality=96,subsampling=0)
    result={'ok':True,'version':report['version'],'reference_mask_iou':iou,'reference_foreground_recall':recall,
            'extra_foreground_fraction':extra,'largest_detached_piece_pixels':int(detached),
            'source_hashes_preserved':True,'paper_foliage_applied':True,'stems_recovered':info['stems_recovered'],
            'uncertain_connections':info['uncertain_connections'],
            'scope':'One reviewed real-photo example. This is not general extraction accuracy or visual acceptance of other photographs.'}
    (output/'Fern Quality.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
