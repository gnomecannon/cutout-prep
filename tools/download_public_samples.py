"""Download the pinned public visual-review cases; never part of offline CI.

Source photographs have their own licenses, credited in public_samples.json.
This keeps the images out of the source package and preserves original bytes.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    a=p.parse_args()
    destination=a.output.resolve()
    if destination.exists():p.error('Choose a new download folder; existing files are preserved')
    cases=json.loads(Path(__file__).with_name('public_samples.json').read_text(encoding='utf-8'))
    destination.mkdir(parents=True)
    downloaded=[]
    for case in cases:
        name=case['file'];url=case['download_url']
        if Path(name).name!=name or any(c in name for c in '/\\:') or not url.startswith('https://upload.wikimedia.org/'):
            raise ValueError('Unexpected sample filename or download host')
        content=None
        for attempt in range(3):
            request=urllib.request.Request(url,headers={'User-Agent':'CutoutPrepValidation/0.3 (public sample evaluation)'})
            try:
                with urllib.request.urlopen(request,timeout=90) as response:
                    content=response.read(case['bytes']+1)
                break
            except urllib.error.HTTPError as error:
                if error.code!=429 or attempt==2:raise
                delay=int(error.headers.get('Retry-After','60'))
                print(f'Source rate limit: waiting {delay} seconds for {name}',flush=True)
                while delay>0:
                    interval=min(30,delay);time.sleep(interval);delay-=interval
        if len(content)!=case['bytes'] or hashlib.sha1(content).hexdigest()!=case['original_sha1']:
            raise RuntimeError('Sample differs from the pinned original: '+name)
        if case.get('sha256') and hashlib.sha256(content).hexdigest()!=case['sha256']:
            raise RuntimeError('Sample SHA256 differs: '+name)
        (destination/name).write_bytes(content)
        downloaded.append(case)
        # Retain credits even when a later download fails.
        (destination/'Sources.json').write_text(json.dumps(downloaded,indent=2)+'\n',encoding='utf-8')
        print(name,case['license'],flush=True)
        time.sleep(4)
    for mode in ('photo','artwork'):
        (destination/f'{mode}-cases.json').write_text(json.dumps([r['file'] for r in cases if r['mode']==mode],indent=2)+'\n',encoding='utf-8')
    print('Downloaded and verified',len(cases),'public review samples')


if __name__=='__main__':main()
