import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA = '''
CREATE TABLE IF NOT EXISTS shift_rosters (
    shift_id TEXT PRIMARY KEY,
    roster_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operator_selection (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    shift_id TEXT NOT NULL REFERENCES shift_rosters(shift_id),
    sector_id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision > 0)
);
CREATE TABLE IF NOT EXISTS collection_orders (
    order_id TEXT PRIMARY KEY,
    shift_id TEXT NOT NULL REFERENCES shift_rosters(shift_id),
    sector_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS terminal_overlays (
    opened INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE REFERENCES collection_orders(order_id),
    operator_revision INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS collection_attempts (
    attempt_id INTEGER PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES collection_orders(order_id),
    status TEXT NOT NULL CHECK (status IN ('waiting', 'wrong_sector', 'received'))
);
CREATE INDEX IF NOT EXISTS attempts_by_order
    ON collection_attempts(order_id, attempt_id);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_attempt_per_order
    ON collection_attempts(order_id) WHERE status <> 'wrong_sector';
CREATE TABLE IF NOT EXISTS export_queue (
    attempt_id INTEGER PRIMARY KEY REFERENCES collection_attempts(attempt_id),
    order_id TEXT NOT NULL REFERENCES collection_orders(order_id),
    shift_id TEXT NOT NULL REFERENCES shift_rosters(shift_id),
    sector_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS generated_exports (
    file_id TEXT PRIMARY KEY,
    generation_id TEXT NOT NULL UNIQUE,
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES export_queue(attempt_id),
    shift_id TEXT NOT NULL REFERENCES shift_rosters(shift_id),
    sector_id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    original BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS accepted_downloads (
    order_id TEXT PRIMARY KEY REFERENCES collection_orders(order_id),
    attempt_id INTEGER NOT NULL UNIQUE REFERENCES collection_attempts(attempt_id),
    file_id TEXT NOT NULL UNIQUE REFERENCES generated_exports(file_id),
    original BLOB NOT NULL,
    rows_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS frozen_outputs (
    kind TEXT NOT NULL CHECK (kind IN ('sector', 'shift')),
    output_id TEXT NOT NULL,
    shift_id TEXT NOT NULL REFERENCES shift_rosters(shift_id),
    sector_id TEXT,
    document_json TEXT NOT NULL,
    original BLOB,
    PRIMARY KEY (kind, output_id),
    CHECK ((kind = 'sector' AND sector_id IS NOT NULL AND original IS NOT NULL)
        OR (kind = 'shift' AND sector_id IS NULL AND original IS NULL))
);
CREATE INDEX IF NOT EXISTS official_sectors_by_shift
    ON frozen_outputs(shift_id, output_id) WHERE kind = 'sector';
CREATE TABLE IF NOT EXISTS first_receipts (
    kind TEXT NOT NULL,
    output_id TEXT NOT NULL,
    receipt_id TEXT NOT NULL UNIQUE,
    PRIMARY KEY (kind, output_id),
    FOREIGN KEY (kind, output_id) REFERENCES frozen_outputs(kind, output_id)
);
'''


def open_database(path: str | Path) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA foreign_keys = ON')
        db.executescript(SCHEMA)
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def write_transaction(db: sqlite3.Connection):
    if db.in_transaction:
        db.execute('SAVEPOINT inspection_operation')
        try:
            yield
            db.execute('RELEASE SAVEPOINT inspection_operation')
        except BaseException:
            db.execute('ROLLBACK TO SAVEPOINT inspection_operation')
            db.execute('RELEASE SAVEPOINT inspection_operation')
            raise
        return

    db.execute('BEGIN IMMEDIATE')
    try:
        yield
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise
