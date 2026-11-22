from collections.abc import Iterable
from dataclasses import dataclass

from errors import require_identifier
from roster.points import PointSpec, build_points


@dataclass(frozen=True)
class SectorRoster:
    sector_id: str
    points: tuple[PointSpec, ...]


def build_sector(sector_id: str, points: Iterable[tuple[str, str]]) -> SectorRoster:
    require_identifier(sector_id, 'sector number')
    return SectorRoster(sector_id, build_points(points))


def point_ids(sector: SectorRoster) -> tuple[str, ...]:
    return tuple(point.point_id for point in sector.points)
