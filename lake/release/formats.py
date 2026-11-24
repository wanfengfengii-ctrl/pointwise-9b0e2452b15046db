import json
from dataclasses import dataclass
from decimal import Decimal

from lake.audit.requests import canonical_content, fixed_number
from lake.intake.provenance import Provenance, provenance_fields, require_identifier
from lake.intake.rows import litres_text, parse_litres


@dataclass(frozen=True)
class PartFact:
    fact_id: str
    station: str
    litres: int
    provenance: Provenance


@dataclass(frozen=True)
class PublicationPart:
    part_id: str
    publication_id: str
    position: int
    facts: tuple[PartFact, ...]

    @property
    def number(self) -> str:
        return self.part_id


@dataclass(frozen=True)
class WithdrawalNotice:
    notice_id: str
    publication_id: str
    scope: str = 'publication'

    @property
    def number(self) -> str:
        return self.notice_id


Document = PublicationPart | WithdrawalNotice


def part_number(publication_id: str, position: int) -> str:
    return fixed_number('part', [publication_id, position])


def _fact_fields(fact: PartFact) -> dict:
    if not isinstance(fact, PartFact):
        raise ValueError('invalid publication fact')
    return {
        'fact_id': require_identifier(fact.fact_id, 'fact number'),
        'station': require_identifier(fact.station, 'station'),
        'litres': litres_text(fact.litres),
        'origin': provenance_fields(fact.provenance),
    }


def _part_fields(part: PublicationPart) -> dict:
    publication_id = require_identifier(part.publication_id, 'publication number')
    part_id = require_identifier(part.part_id, 'part number')
    if type(part.position) is not int or not 0 <= part.position <= 2**63 - 1:
        raise ValueError('invalid part position')
    if part_id != part_number(publication_id, part.position):
        raise ValueError('part number does not match its publication and position')
    if not isinstance(part.facts, tuple) or not part.facts:
        raise ValueError('expected nonempty ordered part facts')
    facts = [_fact_fields(fact) for fact in part.facts]
    if len({fact['fact_id'] for fact in facts}) != len(facts):
        raise ValueError('duplicate fact within part')
    return {
        'version': 1, 'kind': 'part', 'part_id': part_id,
        'publication_id': publication_id, 'position': part.position, 'facts': facts,
    }


def _notice_fields(notice: WithdrawalNotice) -> dict:
    notice_id = require_identifier(notice.notice_id, 'withdrawal number')
    publication_id = require_identifier(notice.publication_id, 'publication number')
    if notice.scope != 'publication':
        raise ValueError('invalid withdrawal scope')
    return {
        'version': 1, 'kind': 'withdrawal', 'notice_id': notice_id,
        'publication_id': publication_id, 'scope': notice.scope,
    }


def encode_document(document: Document) -> str:
    if isinstance(document, PublicationPart):
        return canonical_content(_part_fields(document))
    if isinstance(document, WithdrawalNotice):
        return canonical_content(_notice_fields(document))
    raise ValueError('unsupported publication document')


def _unique_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'duplicate document field {key}')
        result[key] = value
    return result


def _fields(value: object, names: set[str]) -> dict:
    if type(value) is not dict or value.keys() != names:
        raise ValueError('unexpected document fields')
    return value


def _decode_fact(value: object) -> PartFact:
    fields = _fields(value, {'fact_id', 'station', 'litres', 'origin'})
    origin = _fields(fields['origin'], {'record', 'line'})
    return PartFact(fields['fact_id'], fields['station'], parse_litres(fields['litres']), Provenance(**origin))


def decode_document(payload: str | bytes) -> Document:
    if not isinstance(payload, (str, bytes)):
        raise ValueError('expected JSON text or bytes')
    fields = json.loads(payload, object_pairs_hook=_unique_object, parse_int=lambda raw: int(Decimal(raw)))
    if type(fields) is not dict or type(fields.get('version')) is not int or fields['version'] != 1:
        raise ValueError('unsupported document version')
    if fields.get('kind') == 'part':
        _fields(fields, {'version', 'kind', 'part_id', 'publication_id', 'position', 'facts'})
        if type(fields['facts']) is not list:
            raise ValueError('invalid fact list')
        part = PublicationPart(
            fields['part_id'], fields['publication_id'], fields['position'],
            tuple(_decode_fact(value) for value in fields['facts']),
        )
        _part_fields(part)
        return part
    if fields.get('kind') == 'withdrawal':
        _fields(fields, {'version', 'kind', 'notice_id', 'publication_id', 'scope'})
        notice = WithdrawalNotice(fields['notice_id'], fields['publication_id'], fields['scope'])
        _notice_fields(notice)
        return notice
    raise ValueError('unknown document kind')
