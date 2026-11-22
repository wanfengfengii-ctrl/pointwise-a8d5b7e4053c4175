from dataclasses import asdict, dataclass

from collection.downloads import get_accepted
from collection.orders import get_order
from errors import InspectionError, require_identifier
from handover.archive import Archive, FrozenRecord
from handover.receipts import FirstReceipt
from measurements.extrema import ReadingSummary, summarize_rows
from measurements.rows import ObservedRow
from storage import write_transaction
from terminal.generation import GeneratedExport


@dataclass(frozen=True)
class SectorList:
    order_id: str
    shift_id: str
    sector_id: str
    rows: tuple[ObservedRow, ...]
    summary: ReadingSummary
    origin: GeneratedExport
    original: bytes
    receipt: FirstReceipt


def load_sector_list(record: FrozenRecord, receipt: FirstReceipt) -> SectorList:
    if record.kind != 'sector' or record.sector_id is None or record.original is None:
        raise InspectionError('archive_integrity', f'Invalid sector record {record.output_id}')
    document = record.document
    return SectorList(
        record.output_id, record.shift_id, record.sector_id,
        tuple(ObservedRow.from_document(row) for row in document['rows']),
        ReadingSummary.from_document(document['summary']),
        GeneratedExport(**document['origin']), record.original, receipt,
    )


def publish(archive: Archive, order_id: str) -> SectorList:
    require_identifier(order_id, 'order number')
    with write_transaction(archive.db):
        existing = archive.read_output('sector', order_id)
        if existing is not None:
            return load_sector_list(existing, archive.require_receipt('sector', order_id))
        order = get_order(archive.db, order_id)
        accepted = get_accepted(archive.db, order_id)
        if accepted is None:
            raise InspectionError('no_accepted_download', f'Order {order_id} has no eligible download')
        rows = accepted.validated.rows
        record = FrozenRecord('sector', order_id, order.shift_id, order.sector_id, {
            'rows': [row.to_document() for row in rows],
            'origin': asdict(accepted.origin),
            'summary': summarize_rows(rows).to_document(),
        }, accepted.original)
        return load_sector_list(record, archive.commit_output(record))
