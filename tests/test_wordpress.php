<?php
// Offline validation and CAS contract test. This does not replace a real WP test.
define('ABSPATH', __DIR__);
function register_activation_hook(...$args) {}
function add_action(...$args) {}
function add_filter(...$args) {}
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
    public function prepare($sql, ...$args) { return [$sql, $args]; }
    public function get_var($query) { return $this->value; }
    public function query($query) {
        [, $args] = $query;
        if ($this->conflict || $this->value !== $args[2]) { return 0; }
        $this->value = $args[0]; return 1;
    }
}
function add_option($key, $value, ...$args) {
    global $wpdb;
    if ($wpdb->value !== null || $wpdb->conflict) { return false; }
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
check(isp_geofeed_generator_valid_csv("2001:4860:1234::/64,US,US-IL,Example,\n"), 'IPv6 CSV');
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
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', '')]));
check(!is_wp_error($result) && $result['sha256'] === hash('sha256', $old), 'first publication');
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$new, 'expected_sha256'=>hash('sha256', '')]));
check(is_wp_error($result) && $result->data['status'] === 409, 'stale hash rejected');
check(isp_geofeed_generator_read()['csv'] === $old, 'stale write preserves current feed');
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$new, 'expected_sha256'=>hash('sha256', $old)]));
check(!is_wp_error($result) && isp_geofeed_generator_read()['previous_csv'] === $old, 'update retains previous CSV');
$wpdb->conflict = true;
$result = isp_geofeed_generator_write(new WP_REST_Request('PUT', ['csv'=>$old, 'expected_sha256'=>hash('sha256', $new)]));
check(is_wp_error($result) && isp_geofeed_generator_read()['csv'] === $new, 'concurrent CAS cannot overwrite');
$wpdb->conflict = false;
$result = isp_geofeed_generator_write(new WP_REST_Request('DELETE', ['expected_sha256'=>hash('sha256', $new)]));
check(!is_wp_error($result) && isp_geofeed_generator_read()['csv'] === '', 'rollback to absent feed');
echo "PASS: $count offline WordPress checks\n";
