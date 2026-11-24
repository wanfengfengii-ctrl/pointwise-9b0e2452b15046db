from dataclasses import dataclass


@dataclass(frozen=True)
class Provenance:
    record: str
    line: str


def require_identifier(value: object, field: str) -> str:
    if type(value) is not str or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f'invalid {field}')
    return value


def validate_provenance(provenance: Provenance) -> None:
    if not isinstance(provenance, Provenance):
        raise ValueError('invalid provenance')
    require_identifier(provenance.record, 'origin record')
    require_identifier(provenance.line, 'origin line')


def provenance_fields(provenance: Provenance) -> dict[str, str]:
    validate_provenance(provenance)
    return {'record': provenance.record, 'line': provenance.line}
