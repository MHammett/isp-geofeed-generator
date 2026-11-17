<?php
/**
 * Plugin Name: Local Geofeed Delivery Hook Example for WP Rocket
 * Description: Optional local integration. Install separately on staging after review.
 * License: MIT
 */
if (!defined('ABSPATH')) { exit; }

add_action('isp_geofeed_generator_feed_committed', function ($event) {
    if (!is_array($event) || ($event['schema_version'] ?? null)!==1 ||
        ($event['url'] ?? null)!==rest_url('isp-geofeed-generator/v1/feed')) {
        throw new RuntimeException('Unexpected geofeed delivery event');
    }
    if (!function_exists('rocket_clean_files')) {
        throw new RuntimeException('Required local cache helper is unavailable');
    }
    // This requests the documented URL-path purge. Public read-back remains required.
    // It does not establish that a separate host or CDN cache was cleared.
    rocket_clean_files([$event['url']]);
}, 10, 1);
