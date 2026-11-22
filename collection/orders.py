import sqlite3
from dataclasses import dataclass

from collection.attempts import Attempt, latest_attempt, queue_attempt
from errors import InspectionError, require_identifier
from roster.sectors import SectorRoster
from roster.shifts import get_shift, require_sector
from storage import write_transaction
from terminal.overlays import OverlayState


@dataclass(frozen=True)
class CollectionOrder:
    order_id: str
    shift_id: str
    sector_id: str
    roster: SectorRoster


def find_order(db: sqlite3.Connection, order_id: str) -> CollectionOrder | None:
    require_identifier(order_id, 'order number')
    row = db.execute('SELECT * FROM collection_orders WHERE order_id = ?', (order_id,)).fetchone()
    if row is None:
        return None
    roster = require_sector(get_shift(db, row['shift_id']), row['sector_id'])
    return CollectionOrder(order_id, row['shift_id'], row['sector_id'], roster)


def get_order(db: sqlite3.Connection, order_id: str) -> CollectionOrder:
    order = find_order(db, order_id)
    if order is None:
        raise InspectionError('unknown_order', f'Unknown order: {order_id}')
    return order


def start(db: sqlite3.Connection, order_id: str, shift_id: str, sector_id: str) -> tuple[CollectionOrder, Attempt]:
    with write_transaction(db):
        existing = find_order(db, order_id)
        if existing is not None:
            if (existing.shift_id, existing.sector_id) != (shift_id, sector_id):
                raise InspectionError('order_conflict', f'Order {order_id} already has a different binding')
            return existing, latest_attempt(db, order_id)
        roster = require_sector(get_shift(db, shift_id), sector_id)
        db.execute('INSERT INTO collection_orders VALUES (?, ?, ?)', (order_id, shift_id, sector_id))
        OverlayState(db).open_overlay(order_id)
        return CollectionOrder(order_id, shift_id, sector_id, roster), queue_attempt(db, order_id)


def resume_order(db: sqlite3.Connection, order_id: str) -> tuple[CollectionOrder, Attempt]:
    with write_transaction(db):
        order = get_order(db, order_id)
        previous = latest_attempt(db, order_id)
        if previous.status != 'wrong_sector':
            raise InspectionError('not_retriable', f'Order {order_id} is not awaiting a wrong-sector retry')
        OverlayState(db).open_overlay(order_id)
        return order, queue_attempt(db, order_id)
