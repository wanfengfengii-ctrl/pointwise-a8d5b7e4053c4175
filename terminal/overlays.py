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
            # Re-opening an overlay (e.g. a wrong-sector retry) only refreshes that
            # order's temporary claim; every other order keeps its place in the stack.
            self.db.execute('DELETE FROM terminal_overlays WHERE order_id = ?', (order_id,))
            cursor = self.db.execute('''
                INSERT INTO terminal_overlays (order_id, operator_revision) VALUES (?, ?)
            ''', (order_id, current.revision))
            return Overlay(order_id, current.revision, cursor.lastrowid)

    def effective_sector(self) -> tuple[str, str] | None:
        current = load_selection(self.db)
        if current is None:
            return None
        active = self.db.execute('''
            SELECT orders.shift_id AS shift_id, orders.sector_id AS sector_id
            FROM terminal_overlays AS overlays
            JOIN collection_orders AS orders USING (order_id)
            WHERE overlays.operator_revision >= ?
            ORDER BY overlays.opened DESC
            LIMIT 1
        ''', (current.revision,)).fetchone()
        if active is None:
            # No live temporary claim: the last manual operator choice remains on display.
            return current.shift_id, current.sector_id
        return active['shift_id'], active['sector_id']


def finish(db: sqlite3.Connection, order_id: str) -> tuple[str, str] | None:
    require_identifier(order_id, 'order number')
    with write_transaction(db):
        state = OverlayState(db)
        # Taking an order down releases only that order's overlay; an unknown order
        # matches no row, so the effective filter is preserved.
        db.execute('DELETE FROM terminal_overlays WHERE order_id = ?', (order_id,))
        return state.effective_sector()
