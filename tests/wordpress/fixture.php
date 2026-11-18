<?php
// Private CLI fixture. This file lives outside the WordPress document root.
$geofeed_test_action = $argv[1] ?? '';
$geofeed_test_config = json_decode(file_get_contents(getenv('GEOFEED_WP_FIXTURE')), true, 512, JSON_THROW_ON_ERROR);
if ($geofeed_test_action === 'install') { define('WP_INSTALLING', true); }
require $geofeed_test_config['root'].'/wp-load.php';
require_once ABSPATH.'wp-admin/includes/plugin.php';
$geofeed_test_input = json_decode(stream_get_contents(STDIN), true) ?: [];
if ($geofeed_test_action === 'install') {
    require_once ABSPATH.'wp-admin/includes/upgrade.php';
    wp_install('Disposable Geofeed Test', 'fixture-admin', 'nobody@example.invalid', false, '', $geofeed_test_config['admin_password']);
    $result = activate_plugin('isp-geofeed-generator/isp-geofeed-generator.php');
    if (is_wp_error($result)) { throw new RuntimeException('Fixture plugin activation failed'); }
    update_option('permalink_structure', '/%postname%/');
    flush_rewrite_rules(false);
    $accounts = [];
    foreach (['publisher' => 'isp_geofeed_generator_publisher', 'reader' => 'subscriber', 'policy_admin' => 'administrator'] as $name => $role) {
        $id = wp_insert_user(['user_login' => $name, 'user_pass' => wp_generate_password(32),
            'user_email' => $name.'@example.invalid', 'role' => $role]);
        if (is_wp_error($id)) { throw new RuntimeException('Fixture user creation failed'); }
        $password = WP_Application_Passwords::create_new_application_password($id, ['name' => 'Disposable geofeed integration']);
        if (is_wp_error($password)) { throw new RuntimeException('Fixture application password failed'); }
        $accounts[$name] = $password[0];
    }
    echo json_encode(['accounts' => $accounts, 'wordpress' => $GLOBALS['wp_version'],
        'php' => PHP_VERSION, 'database' => $GLOBALS['wpdb']->get_var('SELECT VERSION()')]);
} elseif ($geofeed_test_action === 'snapshot') {
    global $wpdb;
    $raw = $wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", 'isp_geofeed_generator_document'));
    $collation = $wpdb->get_var($wpdb->prepare("SELECT COLLATION(option_value) FROM {$wpdb->options} WHERE option_name = %s", 'isp_geofeed_generator_document'));
    echo json_encode(['raw' => $raw, 'collation' => $collation,
        'max_allowed_packet' => (int)$wpdb->get_var('SELECT @@max_allowed_packet')]);
} elseif ($geofeed_test_action === 'storage-metadata' || $geofeed_test_action === 'storage-charset') {
    global $wpdb;
    if (PHP_SAPI !== 'cli' || getenv('GITHUB_ACTIONS') !== 'true' ||
        getenv('RUNNER_ENVIRONMENT') !== 'github-hosted' || getenv('GEOFEED_WP_STORAGE_PROTOTYPE') !== '1') {
        throw new RuntimeException('Storage experiment requires disposable prototype CLI');
    }
    // Only the private CLI fixture can change its disposable options column.
    if ($geofeed_test_action === 'storage-charset') {
        $collation = $geofeed_test_input['collation'] ?? '';
        $allowed = ['utf8_general_ci' => 'utf8', 'utf8mb3_general_ci' => 'utf8mb3',
            'utf8mb4_unicode_ci' => 'utf8mb4', 'utf8mb4_unicode_520_ci' => 'utf8mb4'];
        if (!isset($allowed[$collation])) { throw new RuntimeException('Unsupported disposable column collation'); }
        $charset = $allowed[$collation];
        if ($wpdb->query("ALTER TABLE {$wpdb->options} MODIFY option_value longtext CHARACTER SET $charset COLLATE $collation NOT NULL") === false) {
            throw new RuntimeException('Cannot change disposable column charset');
        }
    }
    $column = $wpdb->get_row("SHOW FULL COLUMNS FROM {$wpdb->options} LIKE 'option_value'", ARRAY_A);
    echo json_encode(['column_collation' => $column['Collation'], 'column_type' => $column['Type'],
        'connection' => $wpdb->get_row('SELECT @@character_set_client AS client, @@character_set_connection AS connection, @@character_set_results AS results', ARRAY_A)]);
} elseif ($geofeed_test_action === 'storage-driver-control') {
    global $wpdb;
    if (PHP_SAPI !== 'cli' || getenv('GITHUB_ACTIONS') !== 'true' ||
        getenv('RUNNER_ENVIRONMENT') !== 'github-hosted' || getenv('GEOFEED_WP_STORAGE_PROTOTYPE') !== '1') {
        throw new RuntimeException('Storage driver control requires disposable prototype CLI');
    }
    $query = $wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name = %s", 'isp_geofeed_generator_document');
    $before = $wpdb->get_var($query);
    $suppressed = $wpdb->suppress_errors(true);
    try {
        // Fixed unknown-column error. WHERE 1=0 also forbids changing any row.
        $failed = $wpdb->query("UPDATE {$wpdb->options} SET isp_geofeed_test_missing_column = 1 WHERE 1=0 AND option_name = 'isp_geofeed_generator_document'") === false;
        $error_present = $wpdb->last_error !== '';
    } finally { $wpdb->suppress_errors($suppressed); }
    echo json_encode(['query_failed' => $failed, 'error_present' => $error_present,
        'document_unchanged' => $before === $wpdb->get_var($query)]);
} elseif ($geofeed_test_action === 'reset') {
    delete_option('isp_geofeed_generator_document');
    if (isset($geofeed_test_input['csv'])) {
        add_option('isp_geofeed_generator_document', wp_json_encode(['csv' => $geofeed_test_input['csv'],
            'previous_csv' => $geofeed_test_input['previous_csv'] ?? '']), '', false);
    }
    echo '{}';
} else { throw new RuntimeException('Unknown fixture action'); }
