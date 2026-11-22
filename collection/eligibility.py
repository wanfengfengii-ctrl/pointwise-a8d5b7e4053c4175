from enum import Enum

from collection.artifacts import DownloadArtifact
from collection.attempts import Attempt
from collection.orders import CollectionOrder
from errors import InspectionError
from terminal.generation import GeneratedExport, GenerationLedger


class Eligibility(str, Enum):
    ELIGIBLE = 'eligible'
    WRONG_SECTOR = 'wrong_sector'


def check_eligibility(
    order: CollectionOrder,
    attempt: Attempt,
    artifact: DownloadArtifact,
    ledger: GenerationLedger,
) -> tuple[Eligibility, GeneratedExport]:
    export = ledger.get_export(artifact.file_id)
    if export is None or (
        (export.generation_id, export.attempt_id, export.order_id)
        != (artifact.generation_id, artifact.attempt_id, order.order_id)
        or attempt.attempt_id != artifact.attempt_id
        or attempt.order_id != order.order_id
    ):
        raise InspectionError('file_binding', f'File {artifact.file_id} does not belong to this generation and attempt')
    if artifact.sha256 != export.sha256:
        raise InspectionError('file_digest', f'Bytes differ from the generated file {artifact.file_id}')
    return Eligibility.ELIGIBLE, export
