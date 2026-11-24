from contextlib import closing
from dataclasses import replace
import hmac
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from lake.audit.history import replay
from lake.book.queries import station_book
from lake.intake.batches import BatchInput
from lake.intake.freeze import freeze, initialize_freeze
from lake.intake.provenance import Provenance
from lake.intake.rows import SourceRow
from lake.mirror.acceptance import accept, initialize_mirror
from lake.release.formats import encode_document
from lake.release.issues import initialize_release, issue
from lake.release.withdrawals import initialize_withdrawals, withdraw_issue


STATIONS = ("北闸", "南堤")


def make_trust(secret: bytes = b"example-binti-station-proof"):
    def attest(payload: bytes) -> str:
        return hmac.digest(secret, payload, "sha256").hex()

    def verify(payload: bytes, token: str) -> bool:
        return isinstance(token, str) and token.isascii() and hmac.compare_digest(attest(payload), token)

    return attest, verify


def build_source(db, *, extra_north=False):
    initialize_freeze(db)
    initialize_release(db)
    initialize_withdrawals(db)
    north_rows = [SourceRow("A", 7, Provenance("北闸日报", "1"))]
    if extra_north:
        north_rows.append(SourceRow("C", 7, Provenance("北闸日报", "2")))
    north = freeze(db, BatchInput(STATIONS[0], "北闸交班", tuple(north_rows)))
    south = freeze(db, BatchInput(STATIONS[1], "南堤交班", (
        SourceRow("B", 11, Provenance("南堤日报", "1")),
    )))
    a, *other_north = north.facts
    b, = south.facts
    members = tuple(fact.fact_id for fact in (a, b, *other_north))
    original = issue(db, "P", members, (members,)).parts[0]
    overlap = issue(db, "Q", (a.fact_id,), ((a.fact_id,),)).parts[0]
    withdrawal = withdraw_issue(db, "撤P", original.publication_id).notice
    return original, overlap, withdrawal


def changed_origin(part, ordinal):
    facts = list(part.facts)
    facts[ordinal] = replace(facts[ordinal], provenance=Provenance("别册", "99"))
    return replace(part, facts=tuple(facts))


def run_v1_control(connect):
    with closing(connect("source")) as source:
        part, _, notice = build_source(source)
        wire = encode_document(part)
    with closing(connect("mirror")) as mirror:
        initialize_mirror(mirror, STATIONS)
        first = accept(mirror, wire)
        before = [station_book(mirror, station).litres for station in STATIONS]
    with closing(connect("mirror")) as reopened:
        if replay(reopened, part.part_id).receipt != first.receipt:
            raise AssertionError("first receipt changed after reopening")
        adjustment = accept(reopened, notice).adjustment
        after = [station_book(reopened, station).litres for station in STATIONS]
    actual = {"received": first.status, "before": before, "delta": adjustment.litres_delta, "after": after}
    expected = {"received": "received", "before": [7, 11], "delta": -18, "after": [0, 0]}
    if actual != expected:
        raise AssertionError({"expected": expected, "actual": actual})
    return actual


def main():
    with TemporaryDirectory(prefix="binti-stations-") as directory:
        root = Path(directory)
        result = run_v1_control(lambda name: sqlite3.connect(root / f"{name}.sqlite"))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
