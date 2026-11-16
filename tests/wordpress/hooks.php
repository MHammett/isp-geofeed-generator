<?php
// Test-only MU plugin: no route, role or authentication bypass is registered.
add_filter('pre_wp_mail', function () { return true; });
add_action('rest_api_init', function () {
    header('X-Geofeed-Test-SAPI: '.PHP_SAPI);
    header('X-Geofeed-Test-OPcache: '.(ini_get('opcache.enable') ? '1' : '0'));
});
add_filter('query', function ($sql) {
    $dir = getenv('GEOFEED_WP_CONTROL');
    if (!$dir || !str_contains($sql, 'isp_geofeed_generator_document') ||
        !preg_match('/^(INSERT|REPLACE|UPDATE|DELETE)\b/i', ltrim($sql))) { return $sql; }
    // Log only the verb/PID, never SQL, headers, credentials or feed data.
    preg_match('/^\s*(\w+)/', $sql, $verb);
    file_put_contents($dir.'/writes.log', ($verb[1] ?? '?').' '.getmypid()."\n", FILE_APPEND | LOCK_EX);
    $mode = trim(@file_get_contents($dir.'/mode') ?: '');
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'PUT' ||
        !(($mode === 'first' && preg_match('/^(INSERT|REPLACE)\b/i', ltrim($sql))) ||
          ($mode === 'update' && preg_match('/^UPDATE\b/i', ltrim($sql))))) { return $sql; }
    file_put_contents($dir.'/arrived-'.getmypid(), 'ready');
    $deadline = microtime(true) + 12;
    while (count(glob($dir.'/arrived-*')) < 2) {
        if (microtime(true) > $deadline) { throw new RuntimeException('Integration race barrier expired'); }
        usleep(10000);
    }
    return $sql;
});
