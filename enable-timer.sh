#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run from a root prompt.' >&2; exit 1; }
for file in /etc/isp-geofeed-generator/runtime.env /etc/isp-geofeed-generator/config.yaml; do
    [[ -s $file ]] || { echo "Missing $file" >&2; exit 1; }
    [[ $(stat -c %U "$file") == root && $(stat -c %G "$file") == geofeed && $(stat -c %a "$file") == 640 ]] || {
        echo "$file must be root:geofeed mode 0640" >&2; exit 1;
    }
done
# Execute the actual publish workload. A liveness check cannot enable a timer.
systemctl start isp-geofeed-generator.service
systemctl enable --now isp-geofeed-generator.timer
echo 'First publication succeeded. Daily timer enabled.'
