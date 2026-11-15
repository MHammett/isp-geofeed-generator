#!/usr/bin/env python3
"""Prompt locally and encrypt a credential for systemd. Never rotate implicitly."""
import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from isp_geofeed_generator.credentials import NAMES, valid_name


def credential_name(value):
    if not valid_name(value):
        raise argparse.ArgumentTypeError('Choose a built-in credential name or an EXT_ extension credential name')
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name', type=credential_name,
                        help='Built-in names: '+', '.join(sorted(NAMES))+'; extensions: EXT_<NAME>')
    parser.add_argument('--directory', default='/etc/isp-geofeed-generator/credentials')
    args = parser.parse_args(argv)
    if os.name != 'posix' or os.geteuid() != 0:
        parser.error('Run at a root prompt on a Linux host with systemd-creds')
    directory = Path(args.directory)
    if not directory.is_absolute() or directory.is_symlink():
        parser.error('Use an absolute, non-symlink credential directory')
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        parser.error('Credential directory must be root-owned mode 0700')
    target = directory / (args.name + '.cred')
    if target.exists() or target.is_symlink():
        parser.error('Credential already exists. Retrieve it from your secret manager before considering a separate rotation')
    value = getpass.getpass('Credential value (hidden): ')
    if not value or any(c in value for c in '\r\n\x00'):
        parser.error('Empty or multiline credentials are not accepted')
    old_umask = os.umask(0o077)
    try:
        result = subprocess.run(['systemd-creds','encrypt','--name='+args.name,'-',str(target)],
                                input=value.encode(), capture_output=True, check=False)
    except OSError:
        print('Could not start systemd-creds. No plaintext file was written.',file=sys.stderr)
        return 1
    finally:
        os.umask(old_umask)
    if result.returncode:
        print('Encryption failed. Inspect the host credential-encryption setup; no retry was made.',file=sys.stderr)
        return 1
    print('Encrypted credential saved. Add this non-secret unit setting:')
    print('LoadCredentialEncrypted='+args.name+':'+str(target))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
