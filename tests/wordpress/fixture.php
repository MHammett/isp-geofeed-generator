<?php
// Private CLI fixture. This file lives outside the WordPress document root.
$action = $argv[1] ?? '';
$fixture = json_decode(file_get_contents(getenv('GEOFEED_WP_FIXTURE')), true, 512, JSON_THROW_ON_ERROR);
if ($action === 'install') { define('WP_INSTALLING', true); }
require $fixture['root'].'/wp-load.php';
require_once ABSPATH.'wp-admin/includes/plugin.php';
$input = json_decode(stream_get_contents(STDIN), true) ?: [];
if ($action === 'install') {
    require_once ABSPATH.'wp-admin/includes/upgrade.php';
    wp_install('Disposable Geofeed Test', 'fixture-admin', 'nobody@example.invalid', false, '', $fixture['admin_password']);
    $result = activate_plugin('isp-geofeed-generator/isp-geofeed-generator.php');
    if (is_wp_error($result)) { throw new RuntimeException('Fixture plugin activation failed'); }
    update_option('permalink_structure', '/%postname%/');
    flush_rewrite_rules(false);
    $accounts = [];
    foreach (['publisher' => 'isp_geofeed_generator_publisher', 'reader' => 'subscriber'] as $name => $role) {
        $id = wp_insert_user(['user_login' => $name, 'user_pass' => wp_generate_password(32),
            'user_email' => $name.'@example.invalid', 'role' => $role]);
        if (is_wp_error($id)) { throw new RuntimeException('Fixture user creation failed'); }
        $password = WP_Application_Passwords::create_new_application_password($id, ['name' => 'Disposable geofeed integration']);
        if (is_wp_error($password)) { throw new RuntimeException('Fixture application password failed'); }
        $accounts[$name] = $password[0];
    }
    echo json_encode(['accounts' => $accounts, 'wordpress' => $GLOBALS['wp_version'],
        'php' => PHP_VERSION, 'database' => $GLOBALS['wpdb']->get_var('SELECT VERSION()')]);
} elseif ($action === 'snapshot') {
    global $wpdb;
    $raw = $wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", 'isp_geofeed_generator_document'));
    $collation = $wpdb->get_var($wpdb->prepare("SELECT COLLATION(option_value) FROM {$wpdb->options} WHERE option_name = %s", 'isp_geofeed_generator_document'));
    echo json_encode(['raw' => $raw, 'collation' => $collation]);
} elseif ($action === 'reset') {
    delete_option('isp_geofeed_generator_document');
    if (isset($input['csv'])) {
        add_option('isp_geofeed_generator_document', wp_json_encode(['csv' => $input['csv'], 'previous_csv' => '']), '', false);
    }
    echo '{}';
} else { throw new RuntimeException('Unknown fixture action'); }
