"""Redact local build paths in our image-only Mac wheel and refresh signatures.

Only same-length diagnostic-string replacements are made in Mach-O files.
The original wheel is retained. The repacked wheel gets a fresh RECORD.
"""
import argparse,os,subprocess,sys,tempfile,zipfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--wheel',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    wheel=Path(a.wheel).resolve();output=Path(a.output).resolve();output.mkdir(parents=True,exist_ok=True)
    prefixes={str(Path.home()),tempfile.gettempdir(),str(Path(tempfile.gettempdir()).resolve())}
    with tempfile.TemporaryDirectory(prefix='opencv-wheel-') as tmp:
        root=Path(tmp)
        subprocess.run([sys.executable,'-m','wheel','unpack','--dest',str(root),str(wheel)],check=True)
        unpacked=next(p for p in root.iterdir() if p.is_dir())
        for path in unpacked.rglob('*'):
            if not path.is_file() or path.name=='RECORD':continue
            data=path.read_bytes();original=data
            for prefix in sorted(prefixes,key=len,reverse=True):
                needle=os.fsencode(prefix)
                if len(needle)<6:continue
                data=data.replace(needle,b'/build'+b'/'*(len(needle)-6))
            if data!=original:
                path.write_bytes(data)
                if path.suffix in {'.so','.dylib'}:subprocess.run(['codesign','--force','--sign','-',str(path)],check=True)
        subprocess.run([sys.executable,'-m','wheel','pack','--dest-dir',str(output),str(unpacked)],check=True)
    for result in output.glob('*.whl'):
        with zipfile.ZipFile(result) as z:
            assert not any('x264' in name.lower() or 'x265' in name.lower() for name in z.namelist())
    print('Sanitized image-only wheel ready.')


if __name__=='__main__':main()
