import sqlite3
from dataclasses import dataclass

from errors import InspectionError, require_identifier
from storage import write_transaction
from terminal.operator import load_selection


@dataclass(frozen=True)
class Overlay:
    order_id: str
    operator_revision: int
    opened: int


class OverlayState:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def open_overlay(self, order_id: str) -> Overlay:
        require_identifier(order_id, 'order number')
        with write_transaction(self.db):
            target = self.db.execute('''
                SELECT shift_id, sector_id FROM collection_orders WHERE order_id = ?
            ''', (order_id,)).fetchone()
            if target is None:
                raise InspectionError('unknown_order', f'Unknown order: {order_id}')
            current = load_selection(self.db)
            if current is None:
                raise InspectionError('no_selection', 'Choose an operator sector before opening an overlay')
            self.db.execute('DELETE FROM terminal_overlays WHERE order_id = ?', (order_id,))
            cursor = self.db.execute('''
                INSERT INTO terminal_overlays (order_id, previous_shift_id, previous_sector_id)
                VALUES (?, ?, ?)
            ''', (order_id, current.shift_id, current.sector_id))
            self.db.execute('''
                UPDATE operator_selection SET shift_id = ?, sector_id = ? WHERE singleton = 1
            ''', tuple(target))
            return Overlay(order_id, current.revision, cursor.lastrowid)

    def effective_sector(self) -> tuple[str, str] | None:
        current = load_selection(self.db)
        return None if current is None else (current.shift_id, current.sector_id)


def finish(db: sqlite3.Connection, order_id: str) -> tuple[str, str] | None:
    require_identifier(order_id, 'order number')
    with write_transaction(db):
        state = OverlayState(db)
        current = state.effective_sector()
        restore = db.execute('''
            SELECT orders.shift_id, orders.sector_id, overlays.previous_shift_id, overlays.previous_sector_id
            FROM terminal_overlays AS overlays JOIN collection_orders AS orders USING (order_id)
            WHERE overlays.order_id = ?
        ''', (order_id,)).fetchone()
        if restore is None:
            return current
        db.execute('DELETE FROM terminal_overlays WHERE order_id = ?', (order_id,))
        if current == (restore['shift_id'], restore['sector_id']):
            db.execute('''
                UPDATE operator_selection SET shift_id = ?, sector_id = ? WHERE singleton = 1
            ''', (restore['previous_shift_id'], restore['previous_sector_id']))
        return state.effective_sector()
