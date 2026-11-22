class InspectionError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def require_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in '\r\n\x00'):
        raise InspectionError('invalid_identifier', f'Invalid {label}: {value!r}')


def require_attempt_id(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise InspectionError('unknown_attempt', f'Invalid attempt number: {value!r}')
