import json
import sqlite3
from dataclasses import dataclass

from errors import InspectionError
from handover.receipts import FirstReceipt, make_receipt
from storage import write_transaction


@dataclass(frozen=True)
class FrozenRecord:
    kind: str
    output_id: str
    shift_id: str
    sector_id: str | None
    document: dict
    original: bytes | None = None


class Archive:
    def __init__(self, db: sqlite3.Connection):
        self.db = db

    @staticmethod
    def _decode(row: sqlite3.Row) -> FrozenRecord:
        return FrozenRecord(row['kind'], row['output_id'], row['shift_id'], row['sector_id'],
                            json.loads(row['document_json']), row['original'])

    def read_output(self, kind: str, output_id: str) -> FrozenRecord | None:
        row = self.db.execute('''
            SELECT * FROM frozen_outputs WHERE kind = ? AND output_id = ?
        ''', (kind, output_id)).fetchone()
        return None if row is None else self._decode(row)

    def read_receipt(self, kind: str, output_id: str) -> FirstReceipt | None:
        row = self.db.execute('''
            SELECT kind, output_id, receipt_id FROM first_receipts WHERE kind = ? AND output_id = ?
        ''', (kind, output_id)).fetchone()
        return None if row is None else FirstReceipt(**dict(row))

    def require_receipt(self, kind: str, output_id: str) -> FirstReceipt:
        receipt = self.read_receipt(kind, output_id)
        if receipt is None:
            raise InspectionError('archive_integrity', f'Published output {kind}/{output_id} has no receipt')
        return receipt

    def read_sector_lists(self, shift_id: str) -> tuple[FrozenRecord, ...]:
        rows = self.db.execute('''
            SELECT outputs.* FROM frozen_outputs AS outputs
            JOIN first_receipts USING (kind, output_id)
            WHERE outputs.kind = 'sector' AND outputs.shift_id = ? ORDER BY outputs.output_id
        ''', (shift_id,))
        return tuple(self._decode(row) for row in rows)

    def commit_output(self, record: FrozenRecord) -> FirstReceipt:
        receipt = make_receipt(record.kind, record.output_id)
        with write_transaction(self.db):
            existing = self.read_output(record.kind, record.output_id)
            if existing is not None:
                if existing != record:
                    raise InspectionError('output_conflict', f'Output {record.output_id} has already been frozen')
                return self.require_receipt(record.kind, record.output_id)
            self.db.execute('''
                INSERT INTO frozen_outputs (kind, output_id, shift_id, sector_id, document_json, original)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (record.kind, record.output_id, record.shift_id, record.sector_id,
                  json.dumps(record.document, sort_keys=True), record.original))
            self.db.execute('''
                INSERT INTO first_receipts (kind, output_id, receipt_id) VALUES (?, ?, ?)
            ''', (receipt.kind, receipt.output_id, receipt.receipt_id))
        return receipt
