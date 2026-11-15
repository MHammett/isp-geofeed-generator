#!/usr/bin/env bash
# Install runtime only. Never copy secrets or deployment configuration from git.
set -euo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
DEST=${DEST:-/opt/isp-geofeed-generator}
DRY_RUN=0
[[ ${1:-} == --dry-run ]] && DRY_RUN=1
if (( ! DRY_RUN )); then
    [[ $EUID == 0 ]] || { echo 'Run from a root prompt, or use --dry-run.' >&2; exit 1; }
    [[ -f /opt/scripting-common/status.py && -f /opt/scripting-common/lockfile.py ]] || {
        echo 'scripting-common must be installed first.' >&2; exit 1;
    }
    getent group scripting >/dev/null
    getent passwd geofeed >/dev/null || useradd --system --user-group --home-dir /var/lib/isp-geofeed-generator --shell /usr/sbin/nologin geofeed
    usermod -aG scripting geofeed
    install -d -o root -g geofeed -m 0750 /etc/isp-geofeed-generator "$DEST"
    install -d -o geofeed -g geofeed -m 0750 /var/lib/isp-geofeed-generator
fi
put() {
    if (( DRY_RUN )); then
        echo "INSTALL root:geofeed 0644 $1 -> $2"
    else
        install -D -o root -g geofeed -m 0644 "$1" "$2"
    fi
}
while IFS= read -r file; do
    put "$file" "$DEST/${file#"$REPO/"}"
done < <(find "$REPO/isp_geofeed_generator" -type f -name '*.py' | sort)
while IFS= read -r file; do
    put "$file" "$DEST/${file#"$REPO/"}"
done < <(find "$REPO/tools" -type f -name '*.py' | sort)
put "$REPO/requirements.txt" "$DEST/requirements.txt"
while IFS= read -r file; do
    put "$file" "/etc/systemd/system/$(basename "$file")"
done < <(find "$REPO/systemd" -maxdepth 1 -type f \( -name '*.service' -o -name '*.timer' -o -name '*.slice' \) | sort)
if (( DRY_RUN )); then
    echo "RUN python3 -m venv $DEST/venv"
    echo "RUN $DEST/venv/bin/pip install -r $DEST/requirements.txt"
    echo 'RUN systemctl daemon-reload (timer remains disabled on first install)'
else
    python3 -m venv "$DEST/venv"
    "$DEST/venv/bin/pip" install -r "$DEST/requirements.txt"
    systemctl daemon-reload
    echo 'Installed. Configuration and timer state were preserved.'
    echo 'After setting /etc/isp-geofeed-generator/config.yaml and .env, use enable-timer.sh.'
fi
