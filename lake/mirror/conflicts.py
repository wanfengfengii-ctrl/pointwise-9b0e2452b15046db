import sqlite3

from lake.audit.requests import RequestConflict, check_request
from lake.mirror.evidence import read_known_fact
from lake.release.formats import Document, PublicationPart, encode_document


class DocumentConflict(RequestConflict):
    pass


def classify_document(db: sqlite3.Connection, document: Document) -> tuple[str, str | None]:
    content = encode_document(document)
    try:
        previous = check_request(db, 'delivery', document.number, content)
    except RequestConflict as exc:
        raise DocumentConflict(f'different content for document {document.number}') from exc
    return content, previous


def validate_fact_consistency(db: sqlite3.Connection, part: PublicationPart) -> None:
    for fact in part.facts:
        known = read_known_fact(db, fact.fact_id)
        if known is not None and known != fact:
            raise DocumentConflict(f'conflicting fields for frozen fact {fact.fact_id}')
