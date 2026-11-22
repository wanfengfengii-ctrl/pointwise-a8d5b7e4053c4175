import sqlite3
from dataclasses import dataclass

from errors import InspectionError, require_attempt_id
from storage import write_transaction
from terminal.exports import ExportQueue, ExportRequest


@dataclass(frozen=True)
class Attempt:
    attempt_id: int
    order_id: str
    status: str


def get_attempt(db: sqlite3.Connection, attempt_id: int) -> Attempt:
    require_attempt_id(attempt_id)
    row = db.execute('SELECT * FROM collection_attempts WHERE attempt_id = ?', (attempt_id,)).fetchone()
    if row is None:
        raise InspectionError('unknown_attempt', f'Unknown attempt: {attempt_id}')
    return Attempt(**dict(row))


def latest_attempt(db: sqlite3.Connection, order_id: str) -> Attempt:
    row = db.execute('''
        SELECT * FROM collection_attempts WHERE order_id = ? ORDER BY attempt_id DESC LIMIT 1
    ''', (order_id,)).fetchone()
    if row is None:
        raise InspectionError('no_attempt', f'Order {order_id} has no queued attempt')
    return Attempt(**dict(row))


def queue_attempt(db: sqlite3.Connection, order_id: str) -> Attempt:
    with write_transaction(db):
        binding = db.execute('SELECT * FROM collection_orders WHERE order_id = ?', (order_id,)).fetchone()
        if binding is None:
            raise InspectionError('unknown_order', f'Unknown order: {order_id}')
        live = db.execute('''
            SELECT 1 FROM collection_attempts WHERE order_id = ? AND status <> 'wrong_sector'
        ''', (order_id,)).fetchone()
        if live is not None:
            raise InspectionError('attempt_active', f'Order {order_id} already has a live attempt')
        cursor = db.execute('''
            INSERT INTO collection_attempts (order_id, status) VALUES (?, 'waiting')
        ''', (order_id,))
        attempt = Attempt(cursor.lastrowid, order_id, 'waiting')
        ExportQueue(db).enqueue(ExportRequest(attempt.attempt_id, order_id, binding['shift_id'], binding['sector_id']))
        return attempt


def _set_outcome(db: sqlite3.Connection, attempt_id: int, outcome: str) -> Attempt:
    with write_transaction(db):
        current = get_attempt(db, attempt_id)
        if current.status == outcome:
            return current
        if current.status != 'waiting':
            raise InspectionError('attempt_settled', f'Attempt {attempt_id} is already {current.status}')
        db.execute('UPDATE collection_attempts SET status = ? WHERE attempt_id = ?', (outcome, attempt_id))
        return Attempt(attempt_id, current.order_id, outcome)


def mark_wrong_sector(db: sqlite3.Connection, attempt_id: int) -> Attempt:
    return _set_outcome(db, attempt_id, 'wrong_sector')


def mark_received(db: sqlite3.Connection, attempt_id: int) -> Attempt:
    return _set_outcome(db, attempt_id, 'received')
