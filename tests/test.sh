#!/usr/bin/env bash
set -euo pipefail
REPO=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$REPO"
while IFS= read -r file; do bash -n "$file"; done < <(find "$REPO" -path '*/.venv' -prune -o -path '*/venv' -prune -o -path '*/.git' -prune -o -name '*.sh' -print)
"${PYTHON:-python3}" -m unittest discover -s tests -v
PASS=0
FAIL=0
pass() { echo "PASS: $*"; PASS=$((PASS+1)); }
fail() { echo "FAIL: $*"; FAIL=$((FAIL+1)); }
HELPERS="${SCRIPTING_COMMON_PATH:-/opt/scripting-common}/lib/test_helpers.sh"
if [[ -f $HELPERS ]]; then
    source "$HELPERS"
    EXPECTED=$(find "$REPO/isp_geofeed_generator" -name '*.py' -type f | sort)
    assert_deploy_dry_run_matches "$REPO/deploy-update.sh" "$REPO/isp_geofeed_generator" "$EXPECTED" 'runtime modules' '\.py$'
    assert_deploy_dry_run_within_bounds "$REPO/deploy-update.sh" 10 60 'deploy plan'
    mkdir -p "$REPO/.venv/deploy-leak-canary"
    printf '%s\n' '# must not deploy' > "$REPO/.venv/deploy-leak-canary/canary.py"
    assert_no_path_leaks_into_deploy "$REPO/deploy-update.sh" "$REPO/.venv" 'venv canary'
else
    echo 'Shared scripting1 coverage helpers unavailable; running portable coverage assertion.'
    "${PYTHON:-python3}" tests/check_deploy.py
fi
if command -v php >/dev/null; then
    php -l wordpress/isp-geofeed-generator/isp-geofeed-generator.php
    php tests/test_wordpress.php
else
    echo 'PHP checks NOT MEASURED: install PHP CLI and run tests/test_wordpress.php before release.'
    [[ ${REQUIRE_PHP:-0} == 0 ]] || exit 1
fi
(( FAIL == 0 ))
