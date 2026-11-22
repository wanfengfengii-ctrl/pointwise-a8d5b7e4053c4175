import json
import sqlite3
from dataclasses import dataclass

from collection.artifacts import DownloadArtifact
from collection.attempts import get_attempt, mark_received, mark_wrong_sector
from collection.eligibility import Eligibility, check_eligibility
from collection.orders import get_order
from errors import InspectionError
from measurements.coverage import ValidatedRows, validate_rows
from measurements.rows import ObservedRow
from storage import write_transaction
from terminal.generation import GeneratedExport, GenerationLedger


@dataclass(frozen=True)
class AcceptedDownload:
    order_id: str
    origin: GeneratedExport
    original: bytes
    validated: ValidatedRows


def get_accepted(db: sqlite3.Connection, order_id: str) -> AcceptedDownload | None:
    row = db.execute('SELECT * FROM accepted_downloads WHERE order_id = ?', (order_id,)).fetchone()
    if row is None:
        return None
    origin = GenerationLedger(db).get_export(row['file_id'])
    if origin is None:
        raise InspectionError('missing_origin', f'No origin for accepted order {order_id}')
    validated = ValidatedRows(tuple(ObservedRow.from_document(item) for item in json.loads(row['rows_json'])))
    return AcceptedDownload(order_id, origin, row['original'], validated)


def receive(db: sqlite3.Connection, artifact: DownloadArtifact) -> AcceptedDownload | Eligibility:
    with write_transaction(db):
        attempt = get_attempt(db, artifact.attempt_id)
        order = get_order(db, attempt.order_id)
        verdict, origin = check_eligibility(order, attempt, artifact, GenerationLedger(db))
        if verdict is Eligibility.WRONG_SECTOR:
            mark_wrong_sector(db, attempt.attempt_id)
            return verdict
        existing = get_accepted(db, order.order_id)
        if existing is not None:
            if existing.origin != origin:
                raise InspectionError('already_received', f'Order {order.order_id} already has a different receipt')
            return existing
        if attempt.status != 'waiting':
            raise InspectionError('attempt_settled', f'Attempt {attempt.attempt_id} cannot be accepted')
        validated = validate_rows(order.roster, artifact.original)
        db.execute('''
            INSERT INTO accepted_downloads (order_id, attempt_id, file_id, original, rows_json)
            VALUES (?, ?, ?, ?, ?)
        ''', (order.order_id, attempt.attempt_id, origin.file_id, artifact.original,
              json.dumps([row.to_document() for row in validated.rows])))
        mark_received(db, attempt.attempt_id)
        return AcceptedDownload(order.order_id, origin, artifact.original, validated)
