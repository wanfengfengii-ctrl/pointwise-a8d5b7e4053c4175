from dataclasses import dataclass

from errors import InspectionError, require_identifier


@dataclass(frozen=True)
class FirstReceipt:
    kind: str
    output_id: str
    receipt_id: str


def make_receipt(kind: str, output_id: str) -> FirstReceipt:
    if kind not in ('sector', 'shift'):
        raise InspectionError('output_kind', f'Unknown output kind: {kind}')
    require_identifier(output_id, 'output number')
    return FirstReceipt(kind, output_id, f'{kind}:{output_id}')
