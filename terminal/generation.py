import hashlib
import sqlite3
from dataclasses import dataclass

from errors import InspectionError, require_identifier
from storage import write_transaction
from terminal.exports import ExportQueue
from terminal.overlays import OverlayState
from terminal.recording import RecordedTerminal


@dataclass(frozen=True)
class GeneratedExport:
    file_id: str
    generation_id: str
    attempt_id: int
    order_id: str
    shift_id: str
    sector_id: str
    sha256: str


class GenerationLedger:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    def get_export(self, file_id: str) -> GeneratedExport | None:
        require_identifier(file_id, 'file number')
        row = self.db.execute('''
            SELECT generated.file_id, generated.generation_id, generated.attempt_id,
                   request.order_id, request.shift_id, request.sector_id, generated.sha256
            FROM generated_exports AS generated JOIN export_queue AS request USING (attempt_id)
            WHERE generated.file_id = ?
        ''', (file_id,)).fetchone()
        return None if row is None else GeneratedExport(**dict(row))

    def read_payload(self, file_id: str) -> bytes:
        require_identifier(file_id, 'file number')
        row = self.db.execute('SELECT original FROM generated_exports WHERE file_id = ?', (file_id,)).fetchone()
        if row is None:
            raise InspectionError('unknown_file', f'No generated file: {file_id}')
        return row['original']

    def existing_generation(self, attempt_id: int, generation_id: str, file_id: str) -> GeneratedExport | None:
        row = self.db.execute('''
            SELECT generated.file_id, generated.generation_id, generated.attempt_id,
                   request.order_id, request.shift_id, request.sector_id, generated.sha256
            FROM generated_exports AS generated JOIN export_queue AS request USING (attempt_id)
            WHERE generated.attempt_id = ? OR generated.generation_id = ? OR generated.file_id = ?
        ''', (attempt_id, generation_id, file_id)).fetchone()
        if row is None:
            return None
        old = GeneratedExport(**dict(row))
        if (old.attempt_id, old.generation_id, old.file_id) != (attempt_id, generation_id, file_id):
            raise InspectionError('generation_conflict', 'Generation or file identity is already bound')
        return old

    def record(self, export: GeneratedExport, original: bytes) -> None:
        self.db.execute('''
            INSERT INTO generated_exports
                (file_id, generation_id, attempt_id, sha256, original)
            VALUES (?, ?, ?, ?, ?)
        ''', (export.file_id, export.generation_id, export.attempt_id, export.sha256, original))


def generate(
    db: sqlite3.Connection,
    source: RecordedTerminal,
    attempt_id: int,
    generation_id: str,
    file_id: str,
) -> GeneratedExport:
    require_identifier(generation_id, 'generation number')
    require_identifier(file_id, 'file number')
    with write_transaction(db):
        request = ExportQueue(db).get_request(attempt_id)
        ledger = GenerationLedger(db)
        existing = ledger.existing_generation(attempt_id, generation_id, file_id)
        if existing is not None:
            return existing
        selected = OverlayState(db).effective_sector()
        if selected is None:
            raise InspectionError('no_selection', 'The terminal has no effective sector')
        shift_id, sector_id = selected
        original = source.read_source(shift_id, sector_id)
        export = GeneratedExport(file_id, generation_id, attempt_id, request.order_id,
                                 request.shift_id, request.sector_id,
                                 hashlib.sha256(original).hexdigest())
        ledger.record(export, original)
        return export
