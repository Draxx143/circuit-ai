PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    publisher TEXT NOT NULL,
    document_type TEXT NOT NULL,
    url TEXT NOT NULL,
    document_version TEXT,
    accessed_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'official_datasheet_reviewed', 'official_product_page_reviewed',
        'needs_review', 'conflicting'
    )),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS components (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_number TEXT NOT NULL COLLATE NOCASE UNIQUE,
    manufacturer TEXT NOT NULL,
    category TEXT NOT NULL,
    component_type TEXT NOT NULL DEFAULT '',
    function_text TEXT NOT NULL DEFAULT '',
    common_applications TEXT NOT NULL DEFAULT '',
    specs_json TEXT NOT NULL DEFAULT '{}',
    recommended_operating_json TEXT NOT NULL DEFAULT '{}',
    absolute_max_json TEXT NOT NULL DEFAULT '{}',
    package TEXT,
    pin_count INTEGER,
    operating_temperature TEXT,
    datasheet_url TEXT,
    datasheet_section TEXT,
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    accessed_on TEXT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    )),
    last_reviewed TEXT,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS component_datasheets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
    page_or_section TEXT NOT NULL DEFAULT '',
    revision TEXT,
    notes TEXT NOT NULL DEFAULT '',
    UNIQUE(component_id, source_id)
);

CREATE TABLE IF NOT EXISTS component_pins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    pin_name TEXT NOT NULL,
    pin_number TEXT NOT NULL,
    function_text TEXT NOT NULL,
    electrical_role TEXT,
    conditions TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    UNIQUE(component_id, pin_number, pin_name)
);

CREATE TABLE IF NOT EXISTS component_diagnostic_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_code TEXT NOT NULL UNIQUE,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    operating_range_key TEXT NOT NULL,
    signal_aliases_json TEXT NOT NULL DEFAULT '[]',
    pin_description TEXT NOT NULL DEFAULT '',
    measurement_unit TEXT NOT NULL DEFAULT 'V',
    description TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    )),
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS circuit_topologies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topology_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT NOT NULL,
    expected_behavior TEXT NOT NULL DEFAULT '',
    failure_modes_json TEXT NOT NULL DEFAULT '[]',
    measurement_points_json TEXT NOT NULL DEFAULT '[]',
    diagnostic_limits TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    )),
    last_reviewed TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS failure_modes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    failure_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    failure_type TEXT NOT NULL DEFAULT 'hypothesis',
    summary TEXT NOT NULL,
    symptom_codes_json TEXT NOT NULL DEFAULT '[]',
    causes_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '{}',
    limitations TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    )),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS diagnostic_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    test_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    purpose TEXT NOT NULL,
    steps_json TEXT NOT NULL DEFAULT '[]',
    measurement_state TEXT NOT NULL CHECK (measurement_state IN (
        'power_off_only', 'powered_measurement', 'board_dependent', 'inspection'
    )),
    risk_level TEXT NOT NULL CHECK (risk_level IN (
        'low', 'caution', 'high', 'board_dependent'
    )),
    prerequisites_json TEXT NOT NULL DEFAULT '[]',
    possible_outcomes_json TEXT NOT NULL DEFAULT '[]',
    limitations TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    ))
);

CREATE TABLE IF NOT EXISTS diagnostic_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
    priority INTEGER NOT NULL DEFAULT 100,
    trigger_symptoms_json TEXT NOT NULL DEFAULT '[]',
    conditions_json TEXT NOT NULL DEFAULT '{}',
    action_json TEXT NOT NULL DEFAULT '{}',
    explanation TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    validation_status TEXT NOT NULL CHECK (validation_status IN (
        'official_datasheet_reviewed', 'verified_multiple_sources', 'needs_review',
        'conflicting', 'experimental', 'lab_tested'
    )),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS repair_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number TEXT NOT NULL UNIQUE,
    board_name TEXT NOT NULL,
    board_manufacturer TEXT NOT NULL DEFAULT '',
    board_model TEXT NOT NULL DEFAULT '',
    application TEXT NOT NULL DEFAULT '',
    expected_input_voltage REAL,
    expected_input_unit TEXT NOT NULL DEFAULT 'V',
    expected_input_source TEXT NOT NULL DEFAULT '',
    reference_component TEXT NOT NULL DEFAULT '',
    fault_description TEXT NOT NULL DEFAULT '',
    symptoms_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','completed')),
    verification_status TEXT NOT NULL DEFAULT 'unverified' CHECK (verification_status IN (
        'unverified', 'verified', 'rejected'
    )),
    confirmed_cause TEXT NOT NULL DEFAULT '',
    repaired_component TEXT NOT NULL DEFAULT '',
    final_outcome TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    submitted_by TEXT NOT NULL DEFAULT '',
    diagnosis_json TEXT NOT NULL DEFAULT '{}',
    is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES repair_cases(id) ON DELETE CASCADE,
    signal TEXT NOT NULL,
    measured_value REAL NOT NULL,
    unit TEXT NOT NULL,
    conditions TEXT NOT NULL DEFAULT '',
    expected_value REAL,
    tolerance_percent REAL,
    expected_source TEXT NOT NULL DEFAULT '',
    measurement_state TEXT NOT NULL DEFAULT 'unknown' CHECK (measurement_state IN (
        'power_off', 'powered', 'unknown'
    )),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS repair_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id INTEGER NOT NULL REFERENCES repair_cases(id) ON DELETE CASCADE,
    test_code TEXT NOT NULL,
    test_title TEXT NOT NULL,
    result TEXT NOT NULL CHECK (result IN (
        'supports', 'contradicts', 'inconclusive', 'not_performed'
    )),
    notes TEXT NOT NULL DEFAULT '',
    test_details_json TEXT NOT NULL DEFAULT '{}',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    tested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS case_components (
    case_id INTEGER NOT NULL REFERENCES repair_cases(id) ON DELETE CASCADE,
    component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE RESTRICT,
    inspection_notes TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT 'not_checked',
    PRIMARY KEY(case_id, component_id)
);

CREATE TABLE IF NOT EXISTS component_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    target_component_id INTEGER NOT NULL REFERENCES components(id) ON DELETE CASCADE,
    relationship_type TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    CHECK (source_component_id <> target_component_id),
    UNIQUE(source_component_id, target_component_id, relationship_type)
);

CREATE TABLE IF NOT EXISTS validation_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    status TEXT NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    reviewer TEXT NOT NULL DEFAULT '',
    source_id INTEGER REFERENCES sources(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_cases_created ON repair_cases(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cases_board ON repair_cases(board_name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_cases_status ON repair_cases(status, verification_status, is_archived);
CREATE INDEX IF NOT EXISTS idx_measurements_case ON measurements(case_id, created_at);
CREATE INDEX IF NOT EXISTS idx_components_category ON components(category, part_number);
CREATE INDEX IF NOT EXISTS idx_component_diag_profile_component ON component_diagnostic_profiles(component_id);
CREATE INDEX IF NOT EXISTS idx_rules_enabled ON diagnostic_rules(enabled, priority);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status, publisher);

INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '5');

-- BoardView (schema v5): interactive board layouts, parts/pins/nets and
-- per-pin measurements (diode-mode / voltage) optionally linked to a repair case.
CREATE TABLE IF NOT EXISTS boards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    source_file TEXT NOT NULL DEFAULT '',
    format TEXT NOT NULL DEFAULT 'circuit-ai-board/1',
    width_mm REAL NOT NULL DEFAULT 100,
    height_mm REAL NOT NULL DEFAULT 80,
    image_path TEXT NOT NULL DEFAULT '',
    is_sample INTEGER NOT NULL DEFAULT 0 CHECK (is_sample IN (0,1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS board_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    ref TEXT NOT NULL,
    part_number TEXT NOT NULL DEFAULT '',
    package TEXT NOT NULL DEFAULT '',
    side TEXT NOT NULL DEFAULT 'top' CHECK (side IN ('top','bottom')),
    x_mm REAL NOT NULL, y_mm REAL NOT NULL,
    rotation_deg REAL NOT NULL DEFAULT 0,
    w_mm REAL NOT NULL DEFAULT 5, h_mm REAL NOT NULL DEFAULT 3,
    UNIQUE(board_id, ref)
);

CREATE TABLE IF NOT EXISTS board_pins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES board_parts(id) ON DELETE CASCADE,
    pin_name TEXT NOT NULL,
    net TEXT NOT NULL DEFAULT '',
    x_mm REAL NOT NULL, y_mm REAL NOT NULL,
    side TEXT NOT NULL DEFAULT 'top' CHECK (side IN ('top','bottom')),
    UNIQUE(part_id, pin_name)
);

CREATE TABLE IF NOT EXISTS board_pin_measurements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pin_id INTEGER NOT NULL REFERENCES board_pins(id) ON DELETE CASCADE,
    case_id INTEGER REFERENCES repair_cases(id) ON DELETE SET NULL,
    kind TEXT NOT NULL CHECK (kind IN ('diode_mv','voltage_v','resistance_ohm','continuity')),
    value REAL,
    unit TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_board_parts_board ON board_parts(board_id, ref);
CREATE INDEX IF NOT EXISTS idx_board_pins_net ON board_pins(net);
CREATE INDEX IF NOT EXISTS idx_board_pin_meas_pin ON board_pin_measurements(pin_id, created_at);
