import sqlite3
from dataclasses import dataclass

from roster.shifts import get_shift, require_sector
from storage import write_transaction


@dataclass(frozen=True)
class OperatorSelection:
    shift_id: str
    sector_id: str
    revision: int


def load_selection(db: sqlite3.Connection) -> OperatorSelection | None:
    row = db.execute('''
        SELECT shift_id, sector_id, revision FROM operator_selection WHERE singleton = 1
    ''').fetchone()
    return None if row is None else OperatorSelection(**dict(row))


def select(db: sqlite3.Connection, shift_id: str, sector_id: str) -> OperatorSelection:
    with write_transaction(db):
        require_sector(get_shift(db, shift_id), sector_id)
        db.execute('''
            INSERT INTO operator_selection VALUES (1, ?, ?, 1)
            ON CONFLICT(singleton) DO UPDATE SET
                shift_id = excluded.shift_id,
                sector_id = excluded.sector_id,
                revision = operator_selection.revision + 1
        ''', (shift_id, sector_id))
        row = db.execute('SELECT revision FROM operator_selection WHERE singleton = 1').fetchone()
        return OperatorSelection(shift_id, sector_id, row['revision'])


def ensure_initial_selection(db: sqlite3.Connection, shift_id: str, sector_id: str) -> OperatorSelection:
    with write_transaction(db):
        current = load_selection(db)
        if current is not None:
            return current
        return select(db, shift_id, sector_id)
