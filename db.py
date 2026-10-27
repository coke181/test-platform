# -*- coding: utf-8 -*-
SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    project TEXT NOT NULL DEFAULT '默认项目',
    started_at TEXT,
    total INTEGER DEFAULT 0,
    passed INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    skipped INTEGER DEFAULT 0,
    duration REAL DEFAULT 0,
    imported_at TEXT
);

CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    name TEXT,
    classname TEXT,
    file TEXT,
    line INTEGER,
    time REAL,
    status TEXT,
    message TEXT,
    traceback TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS test_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    module TEXT,
    priority TEXT DEFAULT 'P2',
    precondition TEXT,
    steps TEXT,
    expected TEXT,
    project TEXT DEFAULT '默认项目',
    automation_id TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER,
    case_id INTEGER,
    kind TEXT,
    filename TEXT,
    stored_name TEXT,
    created_at TEXT,
    FOREIGN KEY(run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    project TEXT DEFAULT '',
    metric TEXT NOT NULL,
    threshold REAL NOT NULL DEFAULT 0,
    webhook_url TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS alert_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER,
    run_id INTEGER,
    status TEXT,
    message TEXT,
    created_at TEXT,
    FOREIGN KEY(rule_id) REFERENCES alert_rules(id) ON DELETE SET NULL
);
"""