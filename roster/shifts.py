import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from errors import InspectionError, require_identifier
from roster.sectors import SectorRoster, build_sector
from storage import write_transaction


SectorInput = Iterable[tuple[str, Iterable[tuple[str, str]]]]


@dataclass(frozen=True)
class ShiftRoster:
    shift_id: str
    sectors: tuple[SectorRoster, ...]


def find_shift(db: sqlite3.Connection, shift_id: str) -> ShiftRoster | None:
    require_identifier(shift_id, 'shift number')
    row = db.execute('SELECT roster_json FROM shift_rosters WHERE shift_id = ?', (shift_id,)).fetchone()
    if row is None:
        return None
    sectors = tuple(build_sector(sector_id, points) for sector_id, points in json.loads(row['roster_json']))
    return ShiftRoster(shift_id, sectors)


def get_shift(db: sqlite3.Connection, shift_id: str) -> ShiftRoster:
    shift = find_shift(db, shift_id)
    if shift is None:
        raise InspectionError('unknown_shift', f'Unknown shift: {shift_id}')
    return shift


def require_sector(shift: ShiftRoster, sector_id: str) -> SectorRoster:
    for sector in shift.sectors:
        if sector.sector_id == sector_id:
            return sector
    raise InspectionError('unknown_sector', f'Sector {sector_id!r} is outside shift {shift.shift_id}')


def register(db: sqlite3.Connection, shift_id: str, sectors: SectorInput) -> ShiftRoster:
    require_identifier(shift_id, 'shift number')
    ordered = tuple(build_sector(sector_id, points) for sector_id, points in sectors)
    sector_ids = {sector.sector_id for sector in ordered}
    if not ordered or len(sector_ids) != len(ordered):
        raise InspectionError('invalid_shift', 'A shift must contain distinct sectors')
    roster = ShiftRoster(shift_id, ordered)
    document = [(sector.sector_id, [(p.point_id, p.unit) for p in sector.points]) for sector in ordered]
    with write_transaction(db):
        current = find_shift(db, shift_id)
        if current is None:
            db.execute('INSERT INTO shift_rosters VALUES (?, ?)', (shift_id, json.dumps(document)))
        elif current != roster:
            raise InspectionError('roster_conflict', f'Shift {shift_id} already has a different roster')
    return roster
