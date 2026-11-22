from dataclasses import dataclass

from errors import InspectionError, require_identifier
from handover.archive import Archive
from handover.receipts import FirstReceipt
from handover.sector_lists import SectorList, load_sector_list
from handover.shift_book import ShiftBook, load_shift_book


@dataclass(frozen=True)
class RetrievedOutput:
    output: SectorList | ShiftBook
    receipt: FirstReceipt


def retrieve(archive: Archive, output_id: str, *, kind: str = 'sector') -> RetrievedOutput:
    require_identifier(output_id, 'output number')
    if kind not in ('sector', 'shift'):
        raise InspectionError('output_kind', f'Unknown output kind: {kind}')
    record = archive.read_output(kind, output_id)
    if record is None:
        raise InspectionError('no_output', f'No published {kind} output for {output_id}')
    receipt = archive.require_receipt(kind, output_id)
    if kind == 'sector':
        output = load_sector_list(record, receipt)
    else:
        output = load_shift_book(archive, record, receipt)
    return RetrievedOutput(output, receipt)
