"""Stage a hash-pinned public binary for the separate Linux conformance job."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
from urllib.request import Request,urlopen

parser=argparse.ArgumentParser()
parser.add_argument('--directory',type=Path,required=True)
args=parser.parse_args()
settings=json.loads((Path(__file__).parent/'external-tools.json').read_text())['maxmind']['linux_amd64']
with urlopen(Request(settings['url'],headers={'User-Agent':'ISP-Geofeed-Generator-conformance'}),timeout=40) as response:
    data=response.read(30_000_001)
assert len(data)<=30_000_000 and hashlib.sha256(data).hexdigest()==settings['archive_sha256']
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as archive:
    matches=[row for row in archive.getmembers() if Path(row.name).name=='mm-geofeed-verifier' and row.isfile()]
    assert len(matches)==1
    content=archive.extractfile(matches[0]).read(30_000_001)
assert hashlib.sha256(content).hexdigest()==settings['executable_sha256']
args.directory.mkdir(parents=True,exist_ok=True)
target=args.directory/'mm-geofeed-verifier';target.write_bytes(content);target.chmod(0o755)
print('PASS: staged independently pinned verifier archive and executable hashes')
