<?php
// Offline validation and CAS contract test. This does not replace a real WP test.
define('ABSPATH', __DIR__);
function register_activation_hook(...$args) {}
function add_action($hook, ...$args) {
    if ($hook==='isp_geofeed_generator_feed_committed') { $GLOBALS['geofeed_test_delivery_actions'][]=$args[0]; }
}
function add_filter(...$args) {}
function do_action($hook, ...$args) {
    if ($hook === 'isp_geofeed_generator_feed_committed' && isset($GLOBALS['geofeed_test_delivery'])) {
        ($GLOBALS['geofeed_test_delivery'])(...$args);
    }
    if ($hook==='isp_geofeed_generator_feed_committed') {
        foreach ($GLOBALS['geofeed_test_delivery_actions']??[] as $callback) { $callback(...$args); }
    }
}
function rest_url($path) { return 'https://example.net/wp-json/'.ltrim($path, '/'); }
function add_role(...$args) {}
function is_ssl() { return $GLOBALS['ssl'] ?? true; }
function current_user_can($cap) { return in_array($cap, $GLOBALS['caps'] ?? [], true); }
function wp_cache_delete(...$args) {}
function wp_json_encode($value) { return json_encode($value); }
function is_wp_error($v) { return $v instanceof WP_Error; }
class WP_Error { public function __construct(public $code, public $message, public $data) {} }
class WP_REST_Request {
    public function __construct(private $method, private $params) {}
    public function get_method() { return $this->method; }
    public function get_json_params() { return $this->params; }
}
class FakeDB {
    public $options = 'wp_options'; public $last_error = ''; public $value = null; public $conflict = false;
    public $race_value = null; public $write_error = false;
    public function prepare($sql, ...$args) { return [$sql, $args]; }
    public function get_var($query) { $this->last_error = ''; return $this->value; }
    public function query($query) {
        [$sql, $args] = $query;
        $this->last_error = '';
        if ($this->write_error) { $this->last_error = 'private database detail'; return false; }
        if (str_starts_with($sql, 'INSERT IGNORE INTO ')) {
            if ($this->race_value !== null) { $this->value = $this->race_value; $this->race_value = null; }
            if ($this->value !== null || $this->conflict) { return 0; }
            $this->value = $args[1]; return 1;
        }
        if (!str_starts_with($sql, 'UPDATE ')) { throw new RuntimeException('Unexpected SQL'); }
        if ($this->conflict || $this->value !== $args[2]) { return 0; }
        $this->value = $args[0]; return 1;
    }
}
function add_option($key, $value, ...$args) {
    global $wpdb;
    // Real WordPress can upsert after a stale object-cache miss. Do not hide it.
    if ($wpdb->race_value !== null) { $wpdb->value = $wpdb->race_value; $wpdb->race_value = null; }
    if ($wpdb->write_error) { $wpdb->last_error = 'private database detail'; return false; }
    $wpdb->value = $value; return true;
}
require __DIR__.'/../wordpress/isp-geofeed-generator/isp-geofeed-generator.php';
$count = 0;
function check($condition, $label) {
    global $count;
    if (!$condition) { fwrite(STDERR, "FAIL: $label\n"); exit(1); }
    $count++;
}
$old = "11.22.33.0/24,US,US-IL,Old City,\n";
$new = "11.22.33.0/24,US,US-IL,New City,\n";
check(isp_geofeed_generator_valid_csv($old), 'valid UTF-8 five-field CSV');
$controls = json_decode(file_get_contents(__DIR__.'/fixtures/conformance.json'), true);
foreach ($controls as $case) {
    check(isp_geofeed_generator_valid_csv($case['csv']) === !$case['core_refuses'], 'shared conformance '.$case['name']);
}
$crlf = str_replace("\n", "\r\n", $old);
check(isp_geofeed_generator_valid_csv($crlf), 'RFC CRLF CSV');
foreach ([$crlf."11.22.34.0/24,US,US-IL,City,\n", str_replace("\n", "\r", $old),
    str_replace('Old City', "Old\rCity", $old), str_replace("\n", "\r\r\n", $old), $crlf."\r\n"] as $bad) {
    check(!isp_geofeed_generator_valid_csv($bad), 'reject mixed or malformed line endings');
}
check(isp_geofeed_generator_valid_csv("2001:4860:1234::/64,US,US-IL,Example,\n"), 'IPv6 CSV');
$special = json_decode(file_get_contents(__DIR__.'/fixtures/special-prefixes.json'), true);
check(ISP_GEOFEED_SPECIAL_RANGES === $special, 'WordPress special-space list matches shared fixture');
foreach ($special as $prefix) {
    check(!isp_geofeed_generator_valid_csv($prefix.",US,US-IL,Example,\n"), 'reject each shared special prefix');
}
foreach (['8.0.0.0/6', '64.0.0.0/2'] as $prefix) {
    check(!isp_geofeed_generator_valid_csv($prefix.",US,US-IL,Example,\n"), 'reject reserved space inside a broad prefix');
}
foreach (['', '<html>bad</html>', "11.0.0.1/24,US,US-IL,City,\n", $old.$old,
    "11.0.0.0/24,US,GB-ENG,City,\n", "11.0.0.0/24,US,US-IL,City,12345\n",
    "11.0.0.0/24,US,US-IL,\"City\",\n", "10.0.0.0/8,US,US-IL,City,\n",
    "100.64.0.0/10,US,US-IL,City,\n", "224.0.0.0/4,US,US-IL,City,\n",
    "11.0.0.0/24,US,US-IL,#comment,\n"] as $bad) {
    check(!isp_geofeed_generator_valid_csv($bad), 'reject malformed/unsafe CSV');
}
$GLOBALS['caps'] = [];
check(!isp_geofeed_generator_permission(), 'anonymous cannot publish');
$GLOBALS['caps'] = ['read'];
check(!isp_geofeed_generator_permission(), 'subscriber cannot publish');
$GLOBALS['caps'] = ['publish_geofeed'];
check(isp_geofeed_generator_permission(), 'publisher capability works');
$GLOBALS['ssl'] = false;
check(!isp_geofeed_generator_permission(), 'HTTP publish forbidden');
$GLOBALS['ssl'] = true;
$wpdb = new FakeDB();
$winner = json_encode(['csv'=>$old, 'previous_csv'=>'']);
$wpdb->race_value = $winner;
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$new, 'expected_sha256'=>hash('sha256', '')]));
check(is_wp_error($result) && $result->data['status'] === 409, 'concurrent first publication conflicts after stale absent read');
check($wpdb->value === $winner, 'concurrent first publication preserves winning bytes');
$wpdb = new FakeDB(); $wpdb->write_error = true;
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', '')]));
check(is_wp_error($result) && $result->data['status'] === 503, 'first-write database failure is not called a conflict');
check(!str_contains($result->message, 'private'), 'database detail stays private');
check($wpdb->value === null, 'database failure leaves absent feed unchanged');
$wpdb = new FakeDB();
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', '')]));
check(!is_wp_error($result) && $result['sha256'] === hash('sha256', $old), 'first publication');
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$new, 'expected_sha256'=>hash('sha256', '')]));
check(is_wp_error($result) && $result->data['status'] === 409, 'stale hash rejected');
check(isp_geofeed_generator_read()['csv'] === $old, 'stale write preserves current feed');
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$new, 'expected_sha256'=>hash('sha256', $old)]));
check(!is_wp_error($result) && isp_geofeed_generator_read()['previous_csv'] === $old, 'update retains previous CSV');
$before_error = $wpdb->value; $wpdb->write_error = true;
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', $new)]));
check(is_wp_error($result) && $result->data['status'] === 503, 'update database failure is not called a conflict');
check($wpdb->value === $before_error, 'failed database update retains previous bytes');
check(str_contains($result->message, 'max_allowed_packet') && !str_contains($result->message, 'private'), 'safe database size guidance');
$wpdb->write_error = false;
$wpdb->conflict = true;
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', $new)]));
check(is_wp_error($result) && isp_geofeed_generator_read()['csv'] === $new, 'concurrent CAS cannot overwrite');
$wpdb->conflict = false;
$result = isp_geofeed_generator_write(new WP_REST_Request('DELETE', ['expected_sha256'=>hash('sha256', $new)]));
check(!is_wp_error($result) && isp_geofeed_generator_read()['csv'] === '', 'rollback to absent feed');
$wpdb = new FakeDB();
isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', '')]));
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$crlf, 'expected_sha256'=>hash('sha256', $old)]));
check(!is_wp_error($result) && $result['sha256'] === hash('sha256', $crlf), 'CRLF migration confirms exact new hash');
check(isp_geofeed_generator_read()['previous_csv'] === $old, 'CRLF migration preserves exact LF recovery bytes');
$migrated = $wpdb->value;
isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$crlf, 'expected_sha256'=>hash('sha256', $crlf)]));
check($wpdb->value === $migrated, 'same CRLF bytes preserve previous version');
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', $crlf)]));
check(!is_wp_error($result) && isp_geofeed_generator_read()['csv'] === $old, 'guarded recovery can restore legacy LF');
echo "PASS: $count offline WordPress checks\n";
