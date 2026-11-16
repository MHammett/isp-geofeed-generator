<?php
/**
 * Plugin Name: ISP Geofeed Generator
 * Description: Publish a validated CSV geofeed through a dedicated REST endpoint.
 * Version: 0.2.0
 * License: MIT
 * Requires PHP: 8.0
 */
if (!defined('ABSPATH')) { exit; }

const ISP_GEOFEED_GENERATOR_OPTION = 'isp_geofeed_generator_document';
const ISP_GEOFEED_SPECIAL_RANGES = [
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24', '192.168.0.0/16', '198.18.0.0/15',
    '192.88.99.0/24', '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4',
    '::/96', '::ffff:0:0/96', '64:ff9b::/96', '64:ff9b:1::/48', '100::/64',
    '2001::/32', '2001:2::/48', '2001:10::/28', '2001:20::/28',
    '2001:db8::/32', '2002::/16', '3fff::/20', '5f00::/16', 'fc00::/7', 'fe80::/10', 'fec0::/10', 'ff00::/8',
];

function isp_geofeed_generator_special_overlap($start, $end) {
    static $ranges = null;
    if ($ranges === null) {
        $ranges = [];
        foreach (ISP_GEOFEED_SPECIAL_RANGES as $cidr) {
            [$address, $bits] = explode('/', $cidr);
            $first = inet_pton($address);
            $bytes = array_values(unpack('C*', $first));
            foreach ($bytes as $i => $byte) {
                $host = min(8, max(0, ($i + 1) * 8 - (int)$bits));
                $bytes[$i] = $byte | ((1 << $host) - 1);
            }
            $ranges[] = [$first, pack('C*', ...$bytes)];
        }
    }
    foreach ($ranges as [$first, $last]) {
        if (strlen($first) === strlen($start) && strcmp($start, $last) <= 0 && strcmp($end, $first) >= 0) {
            return true;
        }
    }
    return false;
}

register_activation_hook(__FILE__, function () {
    add_role('isp_geofeed_generator_publisher', 'Geofeed Publisher', [
        'read' => true, 'publish_geofeed' => true,
    ]);
});

function isp_geofeed_generator_permission() {
    return is_ssl() && (current_user_can('publish_geofeed') || current_user_can('manage_options'));
}

function isp_geofeed_generator_read() {
    // Direct reads are intentional: state and CAS must see the same DB value.
    global $wpdb;
    $raw = $wpdb->get_var($wpdb->prepare(
        "SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", ISP_GEOFEED_GENERATOR_OPTION
    ));
    if ($wpdb->last_error) { return new WP_Error('geofeed_db', 'Cannot read feed state', ['status' => 503]); }
    if ($raw === null) { return ['raw' => null, 'csv' => '', 'previous_csv' => '']; }
    $doc = json_decode($raw, true);
    if (!is_array($doc) || !isset($doc['csv'], $doc['previous_csv'])) {
        return new WP_Error('geofeed_state', 'Stored feed is invalid', ['status' => 503]);
    }
    return ['raw' => $raw, 'csv' => $doc['csv'], 'previous_csv' => $doc['previous_csv']];
}

function isp_geofeed_generator_valid_csv($csv) {
    if (!is_string($csv) || $csv === '' || strlen($csv) > 1000000 ||
        substr($csv, -1) !== "\n" || preg_match('//u', $csv) !== 1) { return false; }
    // Keep exact bytes for CAS/recovery. Accept uniform CRLF or legacy uniform LF.
    $ending = strpos($csv, "\r\n") !== false ? "\r\n" : "\n";
    if (substr($csv, -strlen($ending)) !== $ending) { return false; }
    $seen = [];
    foreach (explode($ending, substr($csv, 0, -strlen($ending))) as $line) {
        // RFC 8805 has five unquoted fields. Postal code is deliberately empty.
        $row = explode(',', $line);
        if (count($row) !== 5 || $row[4] !== '' || strpos($line, '"') !== false ||
            preg_match('/[\x00-\x1f\x7f#]/', $line)) { return false; }
        [$cidr, $country, $region, $city] = $row;
        if (!preg_match('/^[A-Z]{2}$/D', $country) || trim($city) === '' || trim($city) !== $city ||
            ($region !== '' && !preg_match('/^'.preg_quote($country, '/').'\-[A-Z0-9]{1,3}$/D', $region))) { return false; }
        $parts = explode('/', $cidr);
        if (count($parts) !== 2 || !ctype_digit($parts[1]) || (string)(int)$parts[1] !== $parts[1]) { return false; }
        $packed = @inet_pton($parts[0]);
        if ($packed === false || !filter_var($parts[0], FILTER_VALIDATE_IP)) { return false; }
        $bits = (int)$parts[1];
        if ($bits > strlen($packed) * 8) { return false; }
        $bytes = array_values(unpack('C*', $packed));
        $end = $bytes;
        foreach ($bytes as $i => $byte) {
            $host = min(8, max(0, ($i + 1) * 8 - $bits));
            $mask = (1 << $host) - 1;
            if (($byte & $mask) !== 0) { return false; }
            $end[$i] = $byte | $mask;
        }
        // Require nonoverlapping ranges, checked as binary strings per family.
        $family = strlen($packed);
        $end_packed = pack('C*', ...$end);
        if (isp_geofeed_generator_special_overlap($packed, $end_packed)) { return false; }
        $seen[$family][] = [$packed, $end_packed];
    }
    foreach ($seen as $ranges) {
        usort($ranges, function ($a, $b) { return strcmp($a[0], $b[0]); });
        $last = null;
        foreach ($ranges as $range) {
            if ($last !== null && strcmp($range[0], $last) <= 0) { return false; }
            $last = $range[1];
        }
    }
    return true;
}

function isp_geofeed_generator_write(WP_REST_Request $request) {
    global $wpdb;
    $input = $request->get_json_params();
    $csv = $request->get_method() === 'DELETE' ? '' : ($input['csv'] ?? null);
    $expected = $input['expected_sha256'] ?? '';
    if (!is_string($expected) || !preg_match('/^[a-f0-9]{64}$/D', $expected) ||
        ($csv !== '' && !isp_geofeed_generator_valid_csv($csv)) ||
        ($request->get_method() !== 'DELETE' && $csv === '')) {
        return new WP_Error('geofeed_invalid', 'Invalid CSV or expected hash', ['status' => 400]);
    }
    $before = isp_geofeed_generator_read();
    if (is_wp_error($before)) { return $before; }
    if (!hash_equals(hash('sha256', $before['csv']), $expected)) {
        return new WP_Error('geofeed_conflict', 'Feed changed; read state before publishing', ['status' => 409]);
    }
    if ($before['csv'] === $csv) { return ['sha256' => hash('sha256', $csv)]; }
    $next = wp_json_encode(['csv' => $csv, 'previous_csv' => $before['csv']]);
    if ($before['raw'] === null) {
        // add_option can upsert after a stale cache miss. Never replace a winner.
        $changed = $wpdb->query($wpdb->prepare(
            "INSERT IGNORE INTO {$wpdb->options} (option_name, option_value, autoload) VALUES (%s, %s, %s)",
            ISP_GEOFEED_GENERATOR_OPTION, $next, 'no'
        ));
    } else {
        // BINARY avoids a case-insensitive collation weakening the CAS check.
        $changed = $wpdb->query($wpdb->prepare(
            "UPDATE {$wpdb->options} SET option_value = %s WHERE option_name = %s AND BINARY option_value = BINARY %s",
            $next, ISP_GEOFEED_GENERATOR_OPTION, $before['raw']
        ));
    }
    if ($changed === false || $wpdb->last_error) {
        return new WP_Error('geofeed_db', 'Cannot write feed state. Check database health and max_allowed_packet for large feeds', ['status' => 503]);
    }
    if ($changed !== 1) { return new WP_Error('geofeed_conflict', 'Concurrent update; read state before publishing', ['status' => 409]); }
    wp_cache_delete(ISP_GEOFEED_GENERATOR_OPTION, 'options');
    wp_cache_delete('notoptions', 'options');
    return ['sha256' => hash('sha256', $csv)];
}

add_action('rest_api_init', function () {
    register_rest_route('isp-geofeed-generator/v1', '/feed', [
        ['methods' => 'GET', 'permission_callback' => '__return_true', 'callback' => function () {
            $doc = isp_geofeed_generator_read();
            if (is_wp_error($doc)) { return $doc; }
            if ($doc['csv'] === '') { return new WP_Error('geofeed_empty', 'No feed published', ['status' => 404]); }
            return new WP_REST_Response($doc['csv'], 200, [
                'Content-Type' => 'text/csv; charset=utf-8',
                'Cache-Control' => 'no-store, no-cache, must-revalidate, max-age=0',
                'X-Content-Type-Options' => 'nosniff',
            ]);
        }],
        ['methods' => 'PUT,DELETE', 'permission_callback' => 'isp_geofeed_generator_permission', 'callback' => 'isp_geofeed_generator_write'],
    ]);
    register_rest_route('isp-geofeed-generator/v1', '/state', [
        'methods' => 'GET', 'permission_callback' => 'isp_geofeed_generator_permission',
        'callback' => function () {
            $doc = isp_geofeed_generator_read();
            if (is_wp_error($doc)) { return $doc; }
            return new WP_REST_Response(['csv' => $doc['csv'], 'previous_csv' => $doc['previous_csv'],
                'sha256' => hash('sha256', $doc['csv'])], 200, ['Cache-Control' => 'no-store']);
        },
    ]);
});

add_filter('rest_pre_serve_request', function ($served, $result, $request) {
    if ($request->get_route() === '/isp-geofeed-generator/v1/feed' &&
        $request->get_method() === 'GET' && $result->get_status() === 200) {
        echo $result->get_data(); // Validated CSV only; suppress REST's JSON encoding.
        return true;
    }
    return $served;
}, 10, 3);
