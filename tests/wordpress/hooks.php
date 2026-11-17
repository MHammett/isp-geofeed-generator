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
        $capability = $user->has_cap('manage_options') ? 'administrator' :
            ($user->has_cap('publish_geofeed') ? 'publisher' : 'other');
        file_put_contents($dir.'/http-auth.log', (is_ssl() ? 'https' : 'http').' '.$capability."\n", FILE_APPEND | LOCK_EX);
    }
});
add_filter('pre_wp_mail', function () { return true; });
add_action('isp_geofeed_generator_feed_committed', function ($event) {
    $dir=getenv('GEOFEED_WP_CONTROL');
    $flag=$dir ? $dir.'/after-commit-oom' : '';
    if (!$flag || !is_file($flag)) { return; }
    $armed=json_decode(file_get_contents($flag, false, null, 0, 2048), true, 32, JSON_THROW_ON_ERROR);
    if (!is_array($armed) || count($armed)!==4 ||
        array_diff(array_keys($armed), ['nonce','candidate_sha256','before_sha256','api_version']) ||
        !is_string($armed['nonce'] ?? null) || !preg_match('/^[0-9a-f]{32}$/D',$armed['nonce']) ||
        !is_string($armed['candidate_sha256'] ?? null) || !preg_match('/^[0-9a-f]{64}$/D',$armed['candidate_sha256']) ||
        !is_string($armed['before_sha256'] ?? null) || !preg_match('/^[0-9a-f]{64}$/D',$armed['before_sha256']) ||
        !in_array($armed['api_version'] ?? null,[1,2],true)) {
        throw new RuntimeException('Invalid private after-commit control');
    }
    $doc=isp_geofeed_generator_read();
    if (is_wp_error($doc) || $event['method']!=='PUT' || $event['operation']!=='publish' ||
        $event['api_version']!==$armed['api_version'] ||
        hash('sha256',$doc['csv'])!==$armed['candidate_sha256'] || $event['sha256']!==$armed['candidate_sha256'] ||
        hash('sha256',$doc['previous_csv'])!==$armed['before_sha256'] || $event['previous_sha256']!==$armed['before_sha256']) {
        throw new RuntimeException('After-commit fault did not read the committed candidate and history');
    }
    // Consume first. The runner's conditional restore and any competing write must
    // be able to commit normally even though this response will be lost to OOM.
    if (!unlink($flag)) { throw new RuntimeException('Cannot consume private one-shot fault'); }
    $mib=1048576;
    $allocated=memory_get_usage(true);
    $limit=(intdiv($allocated+$mib-1,$mib)+16)*$mib;
    if (wp_convert_hr_to_bytes(ini_get('memory_limit'))!==256*$mib || $limit>192*$mib) {
        throw new RuntimeException('After-commit allocation is outside the bounded fixture budget');
    }
    ini_set('memory_limit',(string)$limit);
    if (wp_convert_hr_to_bytes(ini_get('memory_limit'))!==$limit || $limit<=$allocated) {
        throw new RuntimeException('After-commit memory limit was not measured above current allocation');
    }
    $proof=['nonce'=>$armed['nonce'],'api_version'=>$event['api_version'],
        'sha256'=>hash('sha256',$doc['csv']),'previous_sha256'=>hash('sha256',$doc['previous_csv']),
        'overlap_policy'=>$doc['overlap_policy'],'previous_overlap_policy'=>$doc['previous_overlap_policy'],
        'required_overlap_policy'=>$doc['required_overlap_policy'],'publication_id'=>$doc['publication_id'],
        'allocated_before_fault_bytes'=>$allocated,'peak_before_fault_bytes'=>memory_get_peak_usage(true),
        'oom_limit_bytes'=>$limit,'one_shot_consumed'=>true];
    if (file_put_contents($dir.'/after-commit-oom.log',json_encode($proof)."\n",FILE_APPEND|LOCK_EX)===false) {
        throw new RuntimeException('Cannot record private commit ordering proof');
    }
    $chunks=[];
    for ($i=0;$i<48;$i++) { $chunks[]=str_repeat('x',$mib); }
    // Reaching this is a failed control, never substitute an artificial HTTP 500.
    throw new RuntimeException('Real after-commit exhaustion was not reached within the allocation bound');
},5,1);
add_action('isp_geofeed_generator_feed_committed', function ($event) {
    $dir=getenv('GEOFEED_WP_CONTROL');
    $mode=$dir?trim(@file_get_contents($dir.'/delivery-mode')?:''):'';
    if ($mode==='') { return; }
    $doc=isp_geofeed_generator_read();
    if (is_wp_error($doc) || hash('sha256',$doc['csv'])!==$event['sha256']) {
        throw new RuntimeException('Fixture delivery action ran before its commit');
    }
    file_put_contents($dir.'/delivery.log',json_encode($event)."\n",FILE_APPEND|LOCK_EX);
    if ($mode==='fail') { throw new RuntimeException('PRIVATE simulated purge credential'); }
    if ($mode==='success' && file_put_contents($dir.'/purged.sha256',$event['sha256'],LOCK_EX)===false) {
        throw new RuntimeException('Fixture purge marker write failed');
    }
    // Mode no-effect deliberately accepts the action without changing the cached route.
},10,1);
add_action('rest_api_init', function () {
    header('X-Geofeed-Test-SAPI: '.PHP_SAPI);
    header('X-Geofeed-Test-OPcache: '.(ini_get('opcache.enable') ? '1' : '0'));
    header('X-Geofeed-Test-Post-Max: '.ini_get('post_max_size'));
    header('X-Geofeed-Test-Memory-Limit: '.ini_get('memory_limit'));
    $dir=getenv('GEOFEED_WP_CONTROL');
    if ($dir && is_file($dir.'/packet-probe')) {
        header('X-Geofeed-Test-Max-Packet: '.(int)$GLOBALS['wpdb']->get_var('SELECT @@SESSION.max_allowed_packet'));
    }
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
