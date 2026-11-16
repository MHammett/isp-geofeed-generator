"""Actual PHP processes must refuse missing/tampered ISO data and accept intact data."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

source=Path(__file__).resolve().parents[1]/'wordpress/isp-geofeed-generator'
worker='''define('ABSPATH', __DIR__);
function register_activation_hook(...$a){} function add_action(...$a){} function add_filter(...$a){}
require $argv[1];
echo json_encode(['tables'=>isp_geofeed_generator_iso_codes()!==false,
'csv'=>isp_geofeed_generator_valid_csv("11.22.33.0/24,US,US-IL,Example,\\r\\n")]);'''
for mode in ('missing','changed','valid'):
    with tempfile.TemporaryDirectory() as tmp:
        root=Path(tmp);module=root/'plugin.php';shutil.copyfile(source/'isp-geofeed-generator.php',module)
        if mode!='missing':shutil.copytree(source/'iso_data',root/'iso_data')
        if mode=='changed':(root/'iso_data/iso3166-1.json').write_text('{"private":"do not print"}')
        result=subprocess.run(['php','-r',worker,str(module)],capture_output=True,text=True,check=True,timeout=15)
        assert not result.stderr,result.stderr
        expected=mode=='valid'
        assert json.loads(result.stdout)=={'tables':expected,'csv':expected},mode
print('PASS: PHP ISO data missing/changed refusals and intact-data workload')
