<?php
// Disposable integration fixture only. Never install this configuration on a site.
$fixture = json_decode(file_get_contents(getenv('GEOFEED_WP_FIXTURE')), true, 512, JSON_THROW_ON_ERROR);
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
