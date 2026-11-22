import csv
import io
from dataclasses import dataclass

from errors import InspectionError
from roster.units import decode_pa, encode_pa


@dataclass(frozen=True)
class RawRow:
    point_id: str
    raw_value: str
    source_line: int


@dataclass(frozen=True)
class ObservedRow:
    point_id: str
    raw_value: str
    source_line: int
    reading_pa: int | None

    def to_document(self) -> dict:
        return {
            'point_id': self.point_id,
            'raw_value': self.raw_value,
            'source_line': self.source_line,
            'reading_pa': encode_pa(self.reading_pa),
        }

    @classmethod
    def from_document(cls, document: dict) -> 'ObservedRow':
        return cls(document['point_id'], document['raw_value'], document['source_line'],
                   decode_pa(document['reading_pa']))


def parse_rows(original: bytes) -> tuple[RawRow, ...]:
    try:
        text = original.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise InspectionError('row_encoding', 'Original file must be UTF-8') from exc

    reader = csv.reader(io.StringIO(text, newline=''), strict=True)
    try:
        if next(reader, None) != ['point', 'value'] or reader.line_num != 1:
            raise InspectionError('row_header', 'Expected the header point,value on line 1')
        rows = []
        previous_line = 1
        for fields in reader:
            line = reader.line_num
            if line != previous_line + 1 or len(fields) != 2 or not fields[0]:
                raise InspectionError('row_shape', f'Expected one point and value on physical line {previous_line + 1}')
            rows.append(RawRow(fields[0], fields[1], line))
            previous_line = line
    except csv.Error as exc:
        raise InspectionError('row_csv', f'Malformed CSV near physical line {reader.line_num}') from exc
    return tuple(rows)
