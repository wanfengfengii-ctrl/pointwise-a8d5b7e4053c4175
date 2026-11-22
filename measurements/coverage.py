from dataclasses import dataclass

from errors import InspectionError
from measurements.normalize import normalize_row
from measurements.rows import ObservedRow, parse_rows
from roster.sectors import SectorRoster, point_ids


@dataclass(frozen=True)
class ValidatedRows:
    rows: tuple[ObservedRow, ...]


def validate_rows(roster: SectorRoster, original: bytes) -> ValidatedRows:
    units = {point.point_id: point.unit for point in roster.points}
    received = {}
    for row in parse_rows(original):
        if row.point_id not in units:
            raise InspectionError('row_unexpected', f'Point {row.point_id} on line {row.source_line} is outside the roster')
        if row.point_id in received:
            raise InspectionError('row_duplicate', f'Point {row.point_id} occurs again on line {row.source_line}')
        received[row.point_id] = normalize_row(row, units[row.point_id])

    ordered = point_ids(roster)
    missing = [point_id for point_id in ordered if point_id not in received]
    if missing:
        raise InspectionError('row_missing', 'Missing raw rows for ' + ', '.join(missing))
    return ValidatedRows(tuple(received[point_id] for point_id in ordered))
