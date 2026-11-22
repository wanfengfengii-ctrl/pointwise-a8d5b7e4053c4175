from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass

from errors import InspectionError


@dataclass(frozen=True)
class RecordedEvent:
    sequence: int
    action: str
    arguments: tuple[str, ...]


class RecordedTerminal:
    def __init__(
        self,
        sources: Mapping[tuple[str, str], bytes],
        events: Iterable[RecordedEvent] = (),
    ):
        self._sources: dict[tuple[str, str], bytes] | None = dict(sources)
        self._events = tuple(events)
        last_sequence = 0
        for event in self._events:
            if type(event.sequence) is not int or event.sequence <= last_sequence:
                raise InspectionError('recording_order', 'Recording event numbers must increase strictly')
            last_sequence = event.sequence
        if any(not isinstance(raw, bytes) for raw in self._sources.values()):
            raise InspectionError('source_type', 'Recorded source files must be bytes')

    def iter_events(self) -> Iterator[RecordedEvent]:
        return iter(self._events)

    def read_source(self, shift_id: str, sector_id: str) -> bytes:
        if self._sources is None:
            raise InspectionError('source_closed', 'The recorded terminal is closed')
        try:
            return self._sources[shift_id, sector_id]
        except KeyError:
            raise InspectionError('source_missing', f'No recording for {shift_id}/{sector_id}') from None

    def close(self) -> None:
        self._sources = None
