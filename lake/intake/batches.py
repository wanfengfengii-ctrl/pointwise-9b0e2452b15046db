from dataclasses import dataclass

from lake.audit.requests import fixed_number
from lake.intake.provenance import provenance_fields, require_identifier
from lake.intake.rows import SourceRow, litres_text, validate_rows


@dataclass(frozen=True)
class BatchInput:
    station: str
    name: str
    rows: tuple[SourceRow, ...]


def validate_batch(batch: BatchInput) -> BatchInput:
    if not isinstance(batch, BatchInput):
        raise ValueError('expected a source batch')
    station = require_identifier(batch.station, 'station')
    name = require_identifier(batch.name, 'batch name')
    return BatchInput(station, name, validate_rows(batch.rows))


def batch_content(batch: BatchInput) -> dict:
    return {
        'station': batch.station,
        'name': batch.name,
        'rows': [
            {
                'row_id': row.row_id,
                'litres': litres_text(row.litres),
                'origin': provenance_fields(row.provenance),
            }
            for row in batch.rows
        ],
    }


def batch_identity(station: str, name: str) -> str:
    return fixed_number('batch', [station, name])
