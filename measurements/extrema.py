from collections.abc import Iterable
from dataclasses import dataclass

from measurements.rows import ObservedRow
from roster.units import decode_pa, encode_pa


@dataclass(frozen=True)
class ReadingSummary:
    valid_count: int
    missing_count: int
    min_pa: int | None
    max_pa: int | None

    def to_document(self) -> dict:
        return {
            'valid_count': self.valid_count,
            'missing_count': self.missing_count,
            'min_pa': encode_pa(self.min_pa),
            'max_pa': encode_pa(self.max_pa),
        }

    @classmethod
    def from_document(cls, document: dict) -> 'ReadingSummary':
        return cls(document['valid_count'], document['missing_count'],
                   decode_pa(document['min_pa']), decode_pa(document['max_pa']))


def summarize_rows(rows: Iterable[ObservedRow]) -> ReadingSummary:
    valid = []
    missing = 0
    for row in rows:
        if row.reading_pa is None:
            missing += 1
        else:
            valid.append(row.reading_pa)
    return ReadingSummary(len(valid), missing, min(valid, default=None), max(valid, default=None))


def merge_summaries(summaries: Iterable[ReadingSummary]) -> ReadingSummary:
    valid = missing = 0
    lower = []
    upper = []
    for summary in summaries:
        valid += summary.valid_count
        missing += summary.missing_count
        if summary.min_pa is not None:
            lower.append(summary.min_pa)
        if summary.max_pa is not None:
            upper.append(summary.max_pa)
    return ReadingSummary(valid, missing, min(lower, default=None), max(upper, default=None))
