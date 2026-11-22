import hashlib
from dataclasses import dataclass

from errors import InspectionError, require_attempt_id, require_identifier


@dataclass(frozen=True)
class DownloadArtifact:
    attempt_id: int
    generation_id: str
    file_id: str
    original: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.original).hexdigest()


def read_download(attempt_id: int, generation_id: str, file_id: str, raw: bytes) -> DownloadArtifact:
    require_attempt_id(attempt_id)
    require_identifier(generation_id, 'generation number')
    require_identifier(file_id, 'file number')
    if not isinstance(raw, bytes):
        raise InspectionError('invalid_file', 'A download must contain the original bytes')
    return DownloadArtifact(attempt_id, generation_id, file_id, raw)
