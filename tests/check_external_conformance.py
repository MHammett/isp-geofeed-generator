"""Compare pinned external tools on synthetic feeds, outside publication paths.

Requires a separately staged Candela runtime-only checkout and MaxMind executable.
No source credentials, MMDB database or third-party runtime code is bundled here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from isp_geofeed_generator.client import GeofeedError
from isp_geofeed_generator.feed import parse_feed

def run(argv,**kwargs):
    return subprocess.run(argv,capture_output=True,timeout=45,**kwargs)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candela',type=Path,required=True)
    parser.add_argument('--maxmind',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    tools=json.loads((ROOT/'tests/external-tools.json').read_text())
    executable_hash=hashlib.sha256(args.maxmind.read_bytes()).hexdigest()
    assert executable_hash in {row['executable_sha256'] for row in tools['maxmind'].values()},'Unrecognized verifier binary'
    revision=subprocess.check_output(['git','-C',str(args.candela),'rev-parse','HEAD'],text=True).strip()
    assert revision=='ede8916ee1045fa806554bb76112d0fecc63b40d','Unexpected Candela source revision'
    subprocess.run(['git','-C',str(args.candela),'diff','--exit-code','HEAD','--','src','package-lock.json','.babelrc'],check=True,capture_output=True)
    cases=json.loads((ROOT/'tests/fixtures/conformance.json').read_text(encoding='utf-8'))
    candela=run(['node',str(ROOT/'tests/candela_loader.cjs'),str(args.candela.resolve())],input=json.dumps(cases).encode())
    assert candela.returncode==0,candela.stderr.decode(errors='replace')
    external={row['name']:bool(row['errors']) for row in json.loads(candela.stdout)}
    results=[]
    with tempfile.TemporaryDirectory() as tmp:
        for case in cases:
            data=case['csv'].encode();path=Path(tmp)/(case['name']+'.csv');path.write_bytes(data)
            try:parse_feed(data);refused=False
            except GeofeedError:refused=True
            assert refused==case['core_refuses'],case['name']
            result=run([str(args.maxmind.resolve()),'-gf',str(path)])
            assert result.returncode in (0,1,2), 'Unexpected external process failure'
            results.append({'case':case['name'],'kind':case['kind'],'core_refuses':refused,
                            'candela_reports_errors':external[case['name']],
                            'maxmind_exit':result.returncode,'maxmind_reports_errors':result.returncode!=0})
    for row in results:
        if row['kind']=='valid':assert not row['candela_reports_errors'] and not row['maxmind_reports_errors'],row
        if row['case']=='invalid-prefix':assert row['candela_reports_errors'] and row['maxmind_reports_errors'],row
        if row['kind']=='iso':assert row['candela_reports_errors'],row
    report={'candela_revision':revision,'maxmind_version':'5.0.0',
            'maxmind_executable_sha256':executable_hash,
            'mmdb_comparison':False,'ownership_or_real_geography_verified':False,'results':results}
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
    print('PASS: pinned external conformance controls, with tool limits recorded')

if __name__=='__main__':main()
