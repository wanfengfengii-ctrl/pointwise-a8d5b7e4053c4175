import sqlite3
from collections.abc import Iterable

from roster.shifts import SectorInput, ShiftRoster, find_shift, register
from storage import write_transaction
from terminal.operator import ensure_initial_selection


def initialize(
    db: sqlite3.Connection,
    rosters: Iterable[tuple[str, SectorInput]],
    initial: tuple[str, str],
) -> tuple[ShiftRoster, ...]:
    with write_transaction(db):
        installed = []
        for shift_id, sectors in rosters:
            existing = find_shift(db, shift_id)
            installed.append(existing if existing is not None else register(db, shift_id, sectors))
        ensure_initial_selection(db, *initial)
    return tuple(installed)
