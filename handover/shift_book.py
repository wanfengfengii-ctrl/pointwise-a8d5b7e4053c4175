from collections.abc import Iterable
from dataclasses import dataclass

from collection.orders import get_order
from errors import InspectionError, require_identifier
from handover.archive import Archive, FrozenRecord
from handover.receipts import FirstReceipt
from handover.sector_lists import SectorList, load_sector_list
from measurements.extrema import ReadingSummary, merge_summaries
from roster.shifts import get_shift
from storage import write_transaction


@dataclass(frozen=True)
class MissingSectors:
    shift_id: str
    sector_ids: tuple[str, ...]


@dataclass(frozen=True)
class ShiftBook:
    shift_id: str
    sectors: tuple[SectorList, ...]
    summary: ReadingSummary
    receipt: FirstReceipt


def load_shift_book(archive: Archive, record: FrozenRecord, receipt: FirstReceipt) -> ShiftBook:
    members = []
    for order_id in record.document['order_ids']:
        member = archive.read_output('sector', order_id)
        if member is None or member.shift_id != record.shift_id:
            raise InspectionError('archive_integrity', f'Missing sector list {order_id} for shift {record.shift_id}')
        members.append(load_sector_list(member, archive.require_receipt('sector', order_id)))
    return ShiftBook(record.shift_id, tuple(members), ReadingSummary.from_document(record.document['summary']), receipt)


def close_shift(archive: Archive, shift_id: str, order_ids: Iterable[str]) -> ShiftBook | MissingSectors:
    requested = tuple(order_ids)
    for order_id in requested:
        require_identifier(order_id, 'order number')
    if len(set(requested)) != len(requested):
        raise InspectionError('duplicate_order', 'Provide each sector list once')
    with write_transaction(archive.db):
        shift = get_shift(archive.db, shift_id)
        existing = archive.read_output('shift', shift_id)
        if existing is not None:
            if set(existing.document['order_ids']) != set(requested):
                raise InspectionError('output_conflict', f'Shift {shift_id} is frozen with different sector lists')
            return load_shift_book(archive, existing, archive.require_receipt('shift', shift_id))

        chosen = {}
        for order_id in requested:
            order = get_order(archive.db, order_id)
            if order.shift_id != shift_id:
                raise InspectionError('shift_membership', f'Order {order_id} belongs to another shift')
            if order.sector_id in chosen:
                raise InspectionError('duplicate_sector_list', f'More than one order selected for {order.sector_id}')
            chosen[order.sector_id] = order_id

        formal = {entry.output_id: entry for entry in archive.read_sector_lists(shift_id)}
        missing = tuple(sector.sector_id for sector in shift.sectors if chosen.get(sector.sector_id) not in formal)
        if missing:
            return MissingSectors(shift_id, missing)

        ordered = [chosen[sector.sector_id] for sector in shift.sectors]
        summary = merge_summaries(ReadingSummary.from_document(formal[order_id].document['summary'])
                                  for order_id in ordered)
        record = FrozenRecord('shift', shift_id, shift_id, None, {
            'order_ids': ordered,
            'summary': summary.to_document(),
        })
        return load_shift_book(archive, record, archive.commit_output(record))
