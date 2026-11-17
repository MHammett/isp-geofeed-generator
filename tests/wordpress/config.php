<?php
// Disposable integration fixture only. Never install this configuration on a site.
$fixture = json_decode(file_get_contents(getenv('GEOFEED_WP_FIXTURE')), true, 512, JSON_THROW_ON_ERROR);
// Finite fixture budgets only. A private flag can lower feed PUTs while GETs stay
// available for preflight and read-only failure diagnosis. Never copy to a site.
$geofeed_test_control = getenv('GEOFEED_WP_CONTROL');
$geofeed_test_routes = ['/wp-json/isp-geofeed-generator/v1/feed' => 1,
    '/wp-json/isp-geofeed-generator/v2/feed' => 2];
$geofeed_test_api = $geofeed_test_routes[$_SERVER['REQUEST_URI'] ?? ''] ?? null;
$geofeed_test_put = ($_SERVER['REQUEST_METHOD'] ?? '') === 'PUT' && $geofeed_test_api !== null;
$geofeed_test_memory = '256M';
if ($geofeed_test_control && $geofeed_test_put && is_file($geofeed_test_control.'/memory-probe')) {
    $geofeed_test_memory = trim(file_get_contents($geofeed_test_control.'/memory-probe', false, null, 0, 32));
    if (!in_array($geofeed_test_memory, ['64M', '256M'], true)) {
        throw new RuntimeException('Invalid fixture memory budget');
    }
}
ini_set('memory_limit', $geofeed_test_memory);
define('WP_MEMORY_LIMIT', $geofeed_test_memory);
define('WP_MAX_MEMORY_LIMIT', $geofeed_test_memory);
if ($geofeed_test_control && $geofeed_test_put) {
    // Register before core's fatal handler. Free a small reserve so a real OOM can
    // record fixed metadata without copying the fatal message, SQL or feed data.
    $geofeed_test_reserve = str_repeat('x', 131072);
    register_shutdown_function(function () use ($geofeed_test_control, $geofeed_test_api, &$geofeed_test_reserve) {
        $geofeed_test_reserve = null;
        $last = error_get_last();
        $oom = is_array($last) && $last['type'] === E_ERROR &&
            str_contains($last['message'], 'Allowed memory size of ');
        file_put_contents($geofeed_test_control.'/memory-observations.log', json_encode([
            'api_version' => $geofeed_test_api, 'memory_limit' => ini_get('memory_limit'),
            'peak_allocated_bytes' => memory_get_peak_usage(true), 'oom' => $oom,
            'hard_limit_percent' => ini_get('memory_hard_limit_percent') === false ? null : ini_get('memory_hard_limit_percent')
        ])."\n", FILE_APPEND | LOCK_EX);
    });
}
define('DB_NAME', $fixture['database']);
define('DB_USER', $fixture['db_user']);
define('DB_PASSWORD', $fixture['db_password']);
define('DB_HOST', 'localhost');
define('DB_CHARSET', 'utf8mb4');
define('DB_COLLATE', 'utf8mb4_unicode_ci');
define('WP_HOME', $fixture['url']);
define('WP_SITEURL', $fixture['url']);
define('DISABLE_WP_CRON', true);
define('AUTOMATIC_UPDATER_DISABLED', true);
define('DISALLOW_FILE_MODS', true);
define('WP_HTTP_BLOCK_EXTERNAL', true);
define('WP_DEBUG', false);
define('WP_DEBUG_DISPLAY', false);
define('WP_ENVIRONMENT_TYPE', 'staging');
// The front proxy overwrites this private header. Forged X-Forwarded-Proto alone
// cannot make a direct HTTP request secure. Both listeners bind only to loopback.
if (($_SERVER['REMOTE_ADDR'] ?? '') === '127.0.0.1' &&
    hash_equals($fixture['proxy_nonce'], $_SERVER['HTTP_X_GEOFEED_TEST_PROXY'] ?? '')) {
    $_SERVER['HTTPS'] = 'on';
}
$table_prefix = 'wp_';
if (!defined('ABSPATH')) { define('ABSPATH', __DIR__.'/'); }
require_once ABSPATH.'wp-settings.php';
