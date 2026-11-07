"""Download only the exact public checkpoint recorded in model-manifest.json."""
import argparse,hashlib,json,os,tempfile,urllib.request
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
    manifest=json.loads((Path(__file__).parent/'model-manifest.json').read_text())
    root=Path(a.output).resolve();root.mkdir(parents=True,exist_ok=True)
    for name,row in manifest['files'].items():
        dest=root/name
        if dest.exists():
            if hashlib.sha256(dest.read_bytes()).hexdigest()!=row['sha256']:raise SystemExit('Existing file differs; preserved: '+name)
            continue
        url=f'https://huggingface.co/{manifest["repository"]}/resolve/{manifest["revision"]}/{name}'
        fd,tmp=tempfile.mkstemp(prefix='.model-download-',dir=root)
        try:
            sha=hashlib.sha256();size=0
            with os.fdopen(fd,'wb') as f,urllib.request.urlopen(url,timeout=60) as response:
                while chunk:=response.read(1024*1024):
                    size+=len(chunk)
                    if size>row['bytes']:raise ValueError('Unexpected download size')
                    sha.update(chunk);f.write(chunk)
            if size!=row['bytes'] or sha.hexdigest()!=row['sha256']:raise ValueError('Model digest mismatch: '+name)
            os.replace(tmp,dest)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
        print('Verified',name,flush=True)


if __name__=='__main__':main()
