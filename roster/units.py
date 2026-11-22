from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from errors import InspectionError


@dataclass(frozen=True)
class UnitSpec:
    name: str
    pa_per_unit: int


SUPPORTED_UNITS = MappingProxyType({'Pa': UnitSpec('Pa', 1), 'kPa': UnitSpec('kPa', 1000)})


def require_unit(name: str) -> UnitSpec:
    if not isinstance(name, str) or name not in SUPPORTED_UNITS:
        raise InspectionError('unknown_unit', f'Unknown pressure unit: {name!r}')
    return SUPPORTED_UNITS[name]


def encode_pa(value: int | None) -> str | None:
    # SQLite documents store exact pressure values as decimal strings.
    return None if value is None else format(Decimal(value), 'f')


def decode_pa(value: str | None) -> int | None:
    return None if value is None else int(Decimal(value))
