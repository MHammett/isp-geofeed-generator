<?php
// Bootstrap the legacy stubs and verify their contract before the v2 cases.
ob_start(); require __DIR__.'/test_wordpress.php'; ob_end_clean();
define('ISP_GEOFEED_GENERATOR_OVERLAP_POLICY', 'longest_prefix');
class WP_REST_Response {
    public function __construct(public $data, public $status = 200, public $headers = []) {}
}
$count = 0; $newid = 0; $wpdb = new FakeDB();
function marked($body) {
    return '# isp-geofeed-generator v2 overlap_policy=longest_prefix body_sha256='.hash('sha256',$body)."\r\n".$body;
}
function policy_request($csv, $changes = []) {
    $doc = isp_geofeed_generator_read();
    $input = ['protocol_version'=>2,'csv'=>$csv,'overlap_policy'=>'longest_prefix','operation'=>'publish',
        'expected_sha256'=>hash('sha256',$doc['csv']),'expected_overlap_policy'=>$doc['overlap_policy'],
        'expected_required_overlap_policy'=>'longest_prefix','expected_publication_id'=>$doc['publication_id'],
        'publication_id'=>str_pad(dechex(++$GLOBALS['newid']),32,'0',STR_PAD_LEFT)];
    return new WP_REST_Request($csv === '' ? 'DELETE' : 'PUT', array_replace($input,$changes));
}
$legacy = "11.22.33.0/24,US,US-IL,A,\r\n";
$a = marked($legacy);
$b = marked($legacy."11.22.33.0/25,US,US-IL,B,\r\n");
$v6 = marked("2001:4860::/32,US,US-IL,A,\r\n2001:4860::/128,US,US-IL,B,\r\n");
check(isp_geofeed_generator_valid_csv($a,'longest_prefix'), 'nested marker without overlaps');
check(isp_geofeed_generator_valid_csv($b,'longest_prefix'), 'nested parent and child');
check(isp_geofeed_generator_valid_csv($v6,'longest_prefix'), 'nested IPv6');
check(!isp_geofeed_generator_valid_csv($a), 'strict parser refuses marker');
check(!isp_geofeed_generator_valid_csv($legacy,'longest_prefix'), 'nested marker is mandatory');
check(!isp_geofeed_generator_valid_csv(str_replace(',A,',',Z,',$a),'longest_prefix'), 'marker body hash');
check(!isp_geofeed_generator_valid_csv(marked($legacy.$legacy),'longest_prefix'), 'nested duplicates');
check(!isp_geofeed_generator_valid_csv(marked("8.0.0.0/6,US,US-IL,A,\r\n8.0.0.0/8,US,US-IL,B,\r\n"),'longest_prefix'), 'unsafe broad parent remains refused');
check(!isp_geofeed_generator_valid_csv(marked("11.22.33.0/24,XX,,A,\r\n"),'longest_prefix'), 'nested invalid ISO');
check(!isp_geofeed_generator_valid_csv(marked("2001:4860:ABCD::/48,US,US-IL,A,\r\n"),'longest_prefix'), 'nested canonical IPv6');
$state = isp_geofeed_generator_state_v2();
check($state->data['overlap_policy']==='reject' && $state->data['required_overlap_policy']==='longest_prefix', 'empty stored versus configured policy');
$old = isp_geofeed_generator_write(new WP_REST_Request('PUT',['csv'=>$legacy,'expected_sha256'=>hash('sha256','')]));
check(is_wp_error($old) && $old->data['status']===409 && $wpdb->value===null, 'old writer refused on empty nested site');
$wrong = isp_geofeed_generator_write_v2(policy_request($legacy,['overlap_policy'=>'reject']));
check(is_wp_error($wrong) && $wrong->data['status']===409 && $wpdb->value===null, 'desired policy must match configured policy');
$result = isp_geofeed_generator_write_v2(policy_request($a));
check(!is_wp_error($result) && $result['protocol_version']===2 && $result['overlap_policy']==='longest_prefix', 'first v2 insert');
$doc = isp_geofeed_generator_read();
check($doc['csv']===$a && $doc['previous_csv']==='' && $doc['previous_overlap_policy']==='reject', 'data and policy history inserted together');
$raw = $wpdb->value;
foreach ([['expected_required_overlap_policy'=>'reject'],['expected_overlap_policy'=>'reject'],
          ['expected_publication_id'=>str_repeat('f',32)],['expected_sha256'=>str_repeat('0',64)]] as $bad) {
    $result=isp_geofeed_generator_write_v2(policy_request($b,$bad));
    check(is_wp_error($result) && $result->data['status']===409 && $wpdb->value===$raw, 'stale policy/hash/owner refusal');
}
$result = isp_geofeed_generator_write_v2(policy_request($b,['publication_id'=>$doc['publication_id']]));
check(is_wp_error($result) && $result->data['status']===400 && $wpdb->value===$raw, 'changed publication ID is fresh');
$result = isp_geofeed_generator_write_v2(policy_request($a));
check(!is_wp_error($result) && $wpdb->value===$raw && $result['publication_id']===$doc['publication_id'], 'v2 direct no-op preserves document');
$result = isp_geofeed_generator_write_v2(policy_request($b));
check(!is_wp_error($result) && isp_geofeed_generator_read()['previous_csv']===$a, 'changed v2 retains prior marked data');
$raw=$wpdb->value;
$bad=isp_geofeed_generator_write_v2(policy_request($legacy,['operation'=>'restore','overlap_policy'=>'reject']));
check(is_wp_error($bad) && $bad->data['status']===409 && $wpdb->value===$raw, 'restore cannot invent a baseline');
$result=isp_geofeed_generator_write_v2(policy_request($a,['operation'=>'restore']));
check(!is_wp_error($result) && isp_geofeed_generator_read()['csv']===$a && isp_geofeed_generator_read()['previous_csv']===$b, 'conditional v2 restore keeps failed candidate history');
$wpdb = new FakeDB();$wpdb->value=json_encode(['csv'=>$legacy,'previous_csv'=>'']);
$result=isp_geofeed_generator_write_v2(policy_request($a));
check(!is_wp_error($result) && isp_geofeed_generator_read()['previous_overlap_policy']==='reject', 'explicit upgrade keeps strict baseline policy');
$result=isp_geofeed_generator_write_v2(policy_request($legacy,['operation'=>'restore','overlap_policy'=>'reject']));
check(!is_wp_error($result) && isp_geofeed_generator_read()['csv']===$legacy && isp_geofeed_generator_read()['overlap_policy']==='reject', 'upgrade recovery restores strict baseline despite nested configuration');
$wpdb = new FakeDB();$wpdb->write_error=true;
$result=isp_geofeed_generator_write_v2(policy_request($a));
check(is_wp_error($result) && $result->data['status']===503 && strpos($result->message,'private')===false, 'v2 database error stays private');
$wpdb = new FakeDB();$wpdb->value=json_encode(['protocol_version'=>3,'csv'=>$legacy,'previous_csv'=>'','publication_id'=>str_repeat('a',32)]);
check(is_wp_error(isp_geofeed_generator_read()), 'unknown stored protocol refused');
echo "PASS: $count offline WordPress policy-v2 checks\n";
