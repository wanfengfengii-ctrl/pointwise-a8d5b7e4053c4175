import re
from decimal import Decimal

from errors import InspectionError
from measurements.rows import ObservedRow, RawRow
from roster.units import require_unit


MISSING_VALUE = 'NA'
DECIMAL_LITERAL = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)')


def normalize_row(row: RawRow, unit: str) -> ObservedRow:
    unit_spec = require_unit(unit)
    if row.raw_value == MISSING_VALUE:
        return ObservedRow(row.point_id, row.raw_value, row.source_line, None)
    if DECIMAL_LITERAL.fullmatch(row.raw_value) is None:
        raise InspectionError('row_value', f'Invalid reading on line {row.source_line}: {row.raw_value!r}')

    numerator, denominator = Decimal(row.raw_value).as_integer_ratio()
    reading, remainder = divmod(numerator * unit_spec.pa_per_unit, denominator)
    if remainder:
        raise InspectionError('row_precision', f'Reading on line {row.source_line} is not an integer number of Pa')
    return ObservedRow(row.point_id, row.raw_value, row.source_line, reading)
