"""Synthetic security fixtures. Never used by the runtime or live deployment."""
import time
from pathlib import Path
from isp_geofeed_generator.bogons import BogonIndex, BogonPolicy


def data(version, epoch=None):
    epoch = int(time.time()) if epoch is None else epoch
    rows = ['0.0.0.0/8', '10.0.0.0/8', '14.102.240.0/20', '127.0.0.0/8', '224.0.0.0/4'] if version == 4 else ['::/128', '4000::/3', 'fc00::/7', 'ff00::/8']
    return ('# last updated '+str(epoch)+'\n'+'\n'.join(rows)+'\n').encode()


def policy():
    return BogonPolicy({version: BogonIndex(data(version), version) for version in (4, 6)})


def files(directory):
    result = {}
    for version in (4, 6):
        path = Path(directory)/f'bogons-v{version}.txt'
        path.write_bytes(data(version))
        result[f'ipv{version}_file'] = str(path.resolve())
    return result
