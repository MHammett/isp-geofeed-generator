"""Observation-only helpers for a pinned disposable WordPress core copy."""
VALIDATION = "$this->last_error = __( 'WordPress database error: Could not perform query because it contains invalid data.' );"
DRIVER = '$this->result = mysqli_query( $this->dbh, $query );'
CALLS = {
    VALIDATION: "\n\t\t\tif ( function_exists( 'isp_geofeed_test_storage_layer_event' ) ) { isp_geofeed_test_storage_layer_event( 'wordpress_validation', $query, true, 0 ); }",
    DRIVER: "\n\t\t\tif ( function_exists( 'isp_geofeed_test_storage_layer_event' ) ) { isp_geofeed_test_storage_layer_event( 'driver_result', $query, $this->result === false, mysqli_errno( $this->dbh ) ); }",
}


def instrument_core(source):
    if 'isp_geofeed_test_storage_layer_event' in source:
        raise AssertionError('Pinned core needs one exact storage-layer observation anchor')
    for anchor in CALLS:
        if source.count(anchor) != 1:
            raise AssertionError('Pinned core needs one exact storage-layer observation anchor')
    for anchor, addition in CALLS.items():
        source = source.replace(anchor, anchor + addition)
    return source


def classify_trace(records):
    """Missing events and unsupported sequences are not measured outcomes."""
    if isinstance(records, list) and len(records) == 1:
        row = records[0]
        if (isinstance(row, dict) and set(row) == {'stage', 'failed', 'driver_error'}
                and type(row['failed']) is bool):
            if row == {'stage': 'wordpress_validation', 'failed': True, 'driver_error': 'not_applicable'}:
                return 'wordpress_validation'
            if row == {'stage': 'driver_result', 'failed': False, 'driver_error': 'none'}:
                return 'database_success'
            if row['stage'] == 'driver_result' and row['failed'] and row['driver_error'] in ('unknown_column', 'charset', 'other'):
                return 'database_driver'
    raise AssertionError('Missing or unsupported storage-layer evidence')
