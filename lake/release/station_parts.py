import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal

from lake.audit.requests import canonical_content, fixed_number
from lake.intake.provenance import require_identifier
from lake.release.formats import (
    PartFact,
    PublicationPart,
    _decode_fact,
    _fact_fields,
    _fields,
    _unique_object,
    encode_document,
    part_number,
)


STATION_PART_KIND = 'station_part'
_DIGEST_PATTERN = re.compile(r'[0-9a-f]{64}')


@dataclass(frozen=True)
class StationPartRow:
    ordinal: int
    fact: PartFact


@dataclass(frozen=True)
class StationPart:
    station_part_id: str
    part_id: str
    publication_id: str
    position: int
    station: str
    rows: tuple[StationPartRow, ...]
    original_sha256: str
    token: str

    @property
    def number(self) -> str:
        return self.station_part_id

    @property
    def facts(self) -> tuple[PartFact, ...]:
        return tuple(row.fact for row in self.rows)


def station_part_number(part_id: str, station: str) -> str:
    return fixed_number('station_part', [part_id, station])


def original_digest(part: PublicationPart) -> str:
    return hashlib.sha256(encode_document(part).encode('utf-8')).hexdigest()


def _row_fields(row: StationPartRow) -> dict:
    return {'ordinal': row.ordinal, 'fact': _fact_fields(row.fact)}


def station_part_payload(part: StationPart) -> bytes:
    return canonical_content({
        'kind': STATION_PART_KIND,
        'station_part_id': part.station_part_id,
        'part_id': part.part_id,
        'publication_id': part.publication_id,
        'position': part.position,
        'station': part.station,
        'rows': [_row_fields(row) for row in part.rows],
        'original_sha256': part.original_sha256,
    }).encode('utf-8')


def station_part_fields(part: StationPart) -> dict:
    return {
        'kind': STATION_PART_KIND,
        'station_part_id': part.station_part_id,
        'part_id': part.part_id,
        'publication_id': part.publication_id,
        'position': part.position,
        'station': part.station,
        'rows': [_row_fields(row) for row in part.rows],
        'proof': {'original_sha256': part.original_sha256, 'token': part.token},
    }


def _check_position(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise ValueError(f'invalid {field}')
    return value


def validate_station_part(value: object) -> StationPart:
    fields = _fields(value, {
        'kind', 'station_part_id', 'part_id', 'publication_id', 'position', 'station', 'rows', 'proof',
    })
    if fields['kind'] != STATION_PART_KIND:
        raise ValueError('unexpected station part kind')
    station_part_id = require_identifier(fields['station_part_id'], 'station part number')
    part_id = require_identifier(fields['part_id'], 'part number')
    publication_id = require_identifier(fields['publication_id'], 'publication number')
    position = _check_position(fields['position'], 'part position')
    station = require_identifier(fields['station'], 'station')
    if part_id != part_number(publication_id, position):
        raise ValueError('part number does not match its publication and position')
    if station_part_id != station_part_number(part_id, station):
        raise ValueError('station part number does not match its part and station')
    row_values = fields['rows']
    if type(row_values) is not list or not row_values:
        raise ValueError('expected nonempty ordered station rows')
    rows = []
    known_facts = set()
    previous = -1
    for item in row_values:
        item = _fields(item, {'ordinal', 'fact'})
        ordinal = _check_position(item['ordinal'], 'row ordinal')
        if ordinal <= previous:
            raise ValueError('station rows must follow the original row order')
        previous = ordinal
        fact = _decode_fact(item['fact'])
        _fact_fields(fact)
        if fact.station != station:
            raise ValueError('station part carries a row of another station')
        if fact.fact_id in known_facts:
            raise ValueError('duplicate fact within station part')
        known_facts.add(fact.fact_id)
        rows.append(StationPartRow(ordinal, fact))
    proof = _fields(fields['proof'], {'original_sha256', 'token'})
    digest = proof['original_sha256']
    if type(digest) is not str or _DIGEST_PATTERN.fullmatch(digest) is None:
        raise ValueError('invalid original digest')
    token = proof['token']
    if type(token) is not str or not token:
        raise ValueError('invalid proof token')
    return StationPart(
        station_part_id, part_id, publication_id, position, station,
        tuple(rows), digest, token,
    )


def decode_station_part(payload: object) -> StationPart:
    if isinstance(payload, (str, bytes)):
        payload = json.loads(
            payload, object_pairs_hook=_unique_object, parse_int=lambda raw: int(Decimal(raw)),
        )
    return validate_station_part(payload)
