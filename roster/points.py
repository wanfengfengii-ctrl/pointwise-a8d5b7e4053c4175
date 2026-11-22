from collections.abc import Iterable
from dataclasses import dataclass

from errors import InspectionError, require_identifier
from roster.units import require_unit


@dataclass(frozen=True)
class PointSpec:
    point_id: str
    unit: str


def build_points(points: Iterable[tuple[str, str]]) -> tuple[PointSpec, ...]:
    ordered = []
    seen = set()
    for point_id, unit in points:
        require_identifier(point_id, 'point number')
        if point_id in seen:
            raise InspectionError('duplicate_point', f'Duplicate roster point: {point_id}')
        require_unit(unit)
        seen.add(point_id)
        ordered.append(PointSpec(point_id, unit))
    if not ordered:
        raise InspectionError('empty_sector', 'A sector must have at least one point')
    return tuple(ordered)
