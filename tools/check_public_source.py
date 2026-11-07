"""Check the candidate source file set; this is not a complete secret audit."""
import argparse,json,re,subprocess
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--forbid',action='append',default=[]);a=p.parse_args()
    root=Path(__file__).resolve().parents[1]
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=root).decode().split('\0')
    patterns=[rb'-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----',rb'gh[pous]_[A-Za-z0-9]{30,}',rb'github_pat_[A-Za-z0-9_]{30,}',rb'[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"\']+',rb'/Users/[A-Za-z0-9_.-]+/']
    findings=[];count=0
    for name in names:
        if not name:continue
        path=root/name
        if not path.is_file():continue
        count+=1;data=path.read_bytes()
        if path.suffix.lower() in {'.safetensors','.heic','.heif','.dng','.rsproj','.rcproj','.pem','.key'} or path.name in {'Scan Project.json','Export Report.json','ProcessingReport.json'}:findings.append({'file':name,'reason':'private/generated input type'})
        if any(re.search(pattern,data) for pattern in patterns) or any(s.encode().lower() in data.lower() for s in a.forbid):findings.append({'file':name,'reason':'potential private identifier or secret'})
    print(json.dumps({'source_files_checked':count,'findings':findings},indent=2))
    return 1 if findings else 0


if __name__=='__main__':raise SystemExit(main())
