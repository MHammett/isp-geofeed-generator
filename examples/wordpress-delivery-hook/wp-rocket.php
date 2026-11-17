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
    $parts=parse_url($event['url']);
    if (!is_array($parts) || ($parts['scheme']??null)!=='https' || empty($parts['host']) ||
        isset($parts['query']) || isset($parts['fragment']) || isset($parts['user']) || isset($parts['pass']) ||
        !str_ends_with($parts['path']??'', '/isp-geofeed-generator/v1/feed')) {
        // The provider recursively clears URL paths. A query-based REST URL can
        // have path "/", so refuse it instead of widening the purge to the site.
        throw new RuntimeException('Configure a narrow canonical HTTPS REST path before enabling this integration');
    }
    if (!function_exists('rocket_clean_files')) {
        throw new RuntimeException('Required local cache helper is unavailable');
    }
    // This requests the documented URL-path purge. Public read-back remains required.
    // It does not establish that a separate host or CDN cache was cleared.
    rocket_clean_files([$event['url']]);
}, 10, 1);
