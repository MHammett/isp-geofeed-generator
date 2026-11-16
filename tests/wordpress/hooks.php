<?php
// Test-only MU plugin: no route, role or credential bypass is registered.
// A private control file can relax core's transport gate on this disposable
// loopback fixture. Real application-password verification still runs.
add_filter('wp_is_application_passwords_available', function ($available) {
    $dir = getenv('GEOFEED_WP_CONTROL');
    return ($dir && is_file($dir.'/allow-http-application-passwords')) ? true : $available;
});
add_action('application_password_did_authenticate', function ($user) {
    $dir = getenv('GEOFEED_WP_CONTROL');
    if ($dir && is_file($dir.'/allow-http-application-passwords')) {
        // Record only transport and capability, never the user or password.
        file_put_contents($dir.'/http-auth.log', (is_ssl() ? 'https' : 'http').' '.
            ($user->has_cap('publish_geofeed') ? 'publisher' : 'other')."\n", FILE_APPEND | LOCK_EX);
    }
});
add_filter('pre_wp_mail', function () { return true; });
add_action('rest_api_init', function () {
    header('X-Geofeed-Test-SAPI: '.PHP_SAPI);
    header('X-Geofeed-Test-OPcache: '.(ini_get('opcache.enable') ? '1' : '0'));
    header('X-Geofeed-Test-Post-Max: '.ini_get('post_max_size'));
    header('X-Geofeed-Test-Memory-Limit: '.ini_get('memory_limit'));
});
add_filter('query', function ($sql) {
    $dir = getenv('GEOFEED_WP_CONTROL');
    if (!$dir || !str_contains($sql, 'isp_geofeed_generator_document') ||
        !preg_match('/^(INSERT|REPLACE|UPDATE|DELETE)\b/i', ltrim($sql))) { return $sql; }
    // Log only the verb/PID, never SQL, headers, credentials or feed data.
    preg_match('/^\s*(\w+)/', $sql, $verb);
    file_put_contents($dir.'/writes.log', ($verb[1] ?? '?').' '.getmypid()."\n", FILE_APPEND | LOCK_EX);
    file_put_contents($dir.'/write-sizes.log', ($verb[1] ?? '?').' '.strlen($sql)."\n", FILE_APPEND | LOCK_EX);
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
