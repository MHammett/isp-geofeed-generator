<?php
// Offline hook ordering and failures. Real WordPress exercises the installed action separately.
ob_start(); require __DIR__.'/test_wordpress_v2.php'; ob_end_clean();
$count=0;
function delivery_request($version, $csv, $changes=[]) {
    if ($version===2) { return policy_request($csv,$changes); }
    $doc=isp_geofeed_generator_read();
    return new WP_REST_Request($csv===''?'DELETE':'PUT',array_replace([
        'csv'=>$csv,'expected_sha256'=>hash('sha256',$doc['csv'])],$changes));
}
foreach ([1,2] as $version) {
    $wpdb=new FakeDB();$events=[];$throw=false;
    $GLOBALS['geofeed_test_delivery']=function ($event) use (&$events,&$throw,$version) {
        $events[]=['event'=>$event,'state'=>isp_geofeed_generator_read()];
        if ($throw) {
            if ($version===1) { throw new RuntimeException('PRIVATE hook credential sentinel'); }
            throw new Error('PRIVATE hook credential sentinel');
        }
    };
    if ($version===2) { isp_geofeed_generator_configure_policy(configure_request('longest_prefix')); }
    check(count($events)===0,'policy configuration does not invoke delivery hook');
    $first="11.22.33.0/24,US,US-IL,A,\r\n";$second=str_replace(',A,',',B,',$first);
    if ($version===2) { $first=marked($first);$second=marked($second); }
    $write=$version===1?'isp_geofeed_generator_write':'isp_geofeed_generator_write_v2';
    $result=$write(delivery_request($version,$first));
    check(!is_wp_error($result) && count($events)===1,'changed publication invokes delivery hook exactly once');
    $event=$events[0]['event'];$state=$events[0]['state'];
    check(array_keys($event)===['schema_version','api_version','url','sha256','previous_sha256','overlap_policy','operation','method'], 'hook receives only fixed metadata fields');
    check($event['schema_version']===1 && $event['api_version']===$version && $event['url']===rest_url('isp-geofeed-generator/v1/feed') &&
        $event['sha256']===hash('sha256',$first) && $event['previous_sha256']===hash('sha256','') &&
        $event['overlap_policy']===($version===1?'reject':'longest_prefix') && $event['operation']==='publish' && $event['method']==='PUT', 'hook metadata matches exact committed publication');
    check($state['csv']===$first && $state['previous_csv']==='', 'hook runs after committed state is visible');
    $raw=$wpdb->value;$write(delivery_request($version,$first));
    check(count($events)===1 && $wpdb->value===$raw,'unchanged publication preserves state and skips hook');
    $result=$write(delivery_request($version,$second,['expected_sha256'=>str_repeat('0',64)]));
    check(is_wp_error($result) && $result->data['status']===409 && count($events)===1 && $wpdb->value===$raw,'stale publication cannot invoke hook');
    $result=$write(delivery_request($version,'not a feed'));
    check(is_wp_error($result) && $result->data['status']===400 && count($events)===1 && $wpdb->value===$raw,'invalid publication cannot invoke hook');
    $wpdb->conflict=true;$result=$write(delivery_request($version,$second));$wpdb->conflict=false;
    check(is_wp_error($result) && $result->data['status']===409 && count($events)===1 && $wpdb->value===$raw,'CAS loser cannot invoke hook');
    $wpdb->write_error=true;$result=$write(delivery_request($version,$second));$wpdb->write_error=false;
    check(is_wp_error($result) && $result->data['status']===503 && count($events)===1 && $wpdb->value===$raw,'database failure cannot invoke hook');
    $throw=true;$result=$write(delivery_request($version,$second));$throw=false;
    check(is_wp_error($result) && $result->code==='geofeed_delivery_hook' && $result->data===['status'=>503,'feed_committed'=>true] &&
        str_contains($result->message,'committed') && !str_contains($result->message,'PRIVATE'), 'hook failure reports committed state without exception details');
    $state=isp_geofeed_generator_read();
    check(count($events)===2 && $state['csv']===$second && $state['previous_csv']===$first &&
        $events[1]['state']['csv']===$second,'hook failure keeps exact committed current and prior state without retry');
    $raw=$wpdb->value;$result=$write(delivery_request($version,$second));
    check(!is_wp_error($result) && count($events)===2 && $wpdb->value===$raw,'repeat identical bytes is a no-op, not a blind hook retry');
    $result=$write(delivery_request($version,$first,$version===2?['operation'=>'restore']:[]));
    check(!is_wp_error($result) && count($events)===3 && $events[2]['event']['sha256']===hash('sha256',$first) &&
        $events[2]['event']['previous_sha256']===hash('sha256',$second) &&
        $events[2]['event']['operation']===($version===2?'restore':'publish'),'conditional recovery invokes hook for its own committed bytes');
    $result=$write(delivery_request($version,''));
    check(!is_wp_error($result) && count($events)===4 && $events[3]['event']['method']==='DELETE' &&
        $events[3]['event']['sha256']===hash('sha256','') && $events[3]['state']['csv']==='', 'changed deletion invokes hook after empty state is committed');
    $raw=$wpdb->value;$write(delivery_request($version,''));
    check(count($events)===4 && $wpdb->value===$raw,'unchanged deletion skips hook');
    if ($version===2) {
        isp_geofeed_generator_configure_policy(configure_request('reject'));
        isp_geofeed_generator_state_v2();
        check(count($events)===4,'policy-only change and inspection do not purge');
    }
}
unset($GLOBALS['geofeed_test_delivery']);
require __DIR__.'/../examples/wordpress-delivery-hook/wp-rocket.php';
$wpdb=new FakeDB();$first="11.22.33.0/24,US,US-IL,First,\r\n";$second=str_replace(',First,',',Second,',$first);
$result=isp_geofeed_generator_write(delivery_request(1,$first));
check(is_wp_error($result) && $result->code==='geofeed_delivery_hook' && isp_geofeed_generator_read()['csv']===$first, 'opted-in example fails closed when required cache helper is missing');
if (!function_exists('rocket_clean_files')) {
    function rocket_clean_files($urls) { $GLOBALS['geofeed_test_purge_urls'][]=$urls; }
}
$result=isp_geofeed_generator_write(delivery_request(1,$second));
check(!is_wp_error($result) && $GLOBALS['geofeed_test_purge_urls']===[[rest_url('isp-geofeed-generator/v1/feed')]], 'example requests only the fixed feed URL through documented provider helper');
isp_geofeed_generator_write(delivery_request(1,$second));
check(count($GLOBALS['geofeed_test_purge_urls'])===1,'example does not purge unchanged publication');
$refused=false;
try { do_action('isp_geofeed_generator_feed_committed',['schema_version'=>1,'url'=>'https://other.example/']); }
catch (RuntimeException $error) { $refused=true; }
check($refused && count($GLOBALS['geofeed_test_purge_urls'])===1,'example refuses a different URL without invoking provider helper');
foreach (['https://example.net/?rest_route=/isp-geofeed-generator/v1/feed',
          'http://example.net/wp-json/isp-geofeed-generator/v1/feed',
          'https://example.net/wp-json/isp-geofeed-generator/v1/feed#fragment'] as $bad_url) {
    $GLOBALS['geofeed_test_rest_url']=$bad_url;$refused=false;
    try { do_action('isp_geofeed_generator_feed_committed',['schema_version'=>1,'url'=>$bad_url]); }
    catch (RuntimeException $error) { $refused=true; }
    check($refused && count($GLOBALS['geofeed_test_purge_urls'])===1,'example refuses broad query-based or unsafe canonical purge URLs');
}
unset($GLOBALS['geofeed_test_rest_url']);
echo "PASS: $count offline WordPress delivery-hook checks\n";
