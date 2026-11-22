import sqlite3
from dataclasses import dataclass

from errors import InspectionError, require_attempt_id
from storage import write_transaction


@dataclass(frozen=True)
class ExportRequest:
    attempt_id: int
    order_id: str
    shift_id: str
    sector_id: str


class ExportQueue:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def enqueue(self, request: ExportRequest) -> ExportRequest:
        require_attempt_id(request.attempt_id)
        with write_transaction(self.db):
            row = self.db.execute('''
                SELECT orders.order_id, orders.shift_id, orders.sector_id
                FROM collection_attempts AS attempts JOIN collection_orders AS orders USING (order_id)
                WHERE attempts.attempt_id = ?
            ''', (request.attempt_id,)).fetchone()
            if row is None:
                raise InspectionError('unknown_attempt', f'Unknown attempt: {request.attempt_id}')
            if tuple(row) != (request.order_id, request.shift_id, request.sector_id):
                raise InspectionError('queue_binding', 'Export request does not match its attempt')
            self.db.execute('''
                INSERT INTO export_queue (attempt_id, order_id, shift_id, sector_id) VALUES (?, ?, ?, ?)
                ON CONFLICT(attempt_id) DO NOTHING
            ''', (request.attempt_id, request.order_id, request.shift_id, request.sector_id))
        return request

    def get_request(self, attempt_id: int) -> ExportRequest:
        require_attempt_id(attempt_id)
        row = self.db.execute('SELECT * FROM export_queue WHERE attempt_id = ?', (attempt_id,)).fetchone()
        if row is None:
            raise InspectionError('unknown_attempt', f'No queued export for attempt {attempt_id}')
        return ExportRequest(**dict(row))
