import json
import sqlite3
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.audit.history import replay
from lake.book.queries import station_book, withdrawal_adjustment
from lake.intake.batches import BatchInput
from lake.intake.freeze import freeze, initialize_freeze
from lake.intake.provenance import Provenance
from lake.intake.rows import SourceRow
from lake.mirror.acceptance import accept, initialize_mirror
from lake.release.formats import encode_document
from lake.release.issues import initialize_release, issue
from lake.release.withdrawals import initialize_withdrawals, withdraw_issue


def _book(db, station):
    book = station_book(db, station)
    return {'rows': book.row_count, 'litres': book.litres}


def _prepare_source(path, data):
    with closing(sqlite3.connect(path)) as source:
        initialize_freeze(source)
        initialize_release(source)
        initialize_withdrawals(source)
        rows = tuple(
            SourceRow(row['row'], row['litres'], Provenance(data['origin_record'], row['line']))
            for row in data['rows']
        )
        frozen = freeze(source, BatchInput(data['station'], data['batch'], rows))
        numbers = {fact.row_id: fact.fact_id for fact in frozen.facts}
        publications = {}
        for label, layout in data['releases'].items():
            parts = tuple(tuple(numbers[row] for row in group) for group in layout)
            selected = tuple(number for group in parts for number in group)
            publication = issue(source, label, selected, parts)
            original = replay(source, publication.publication_id)
            publications[label] = original.documents
        target_part = publications[data['withdraw']][0]
        withdrawn = withdraw_issue(source, '日报撤回', target_part.publication_id)
        return publications, withdrawn.notice


def _part(publications, delivery):
    label, position = delivery
    return publications[label][position]


def _workday(directory, data):
    publications, notice = _prepare_source(directory / 'source.sqlite', data)
    wire = encode_document(notice)
    station = data['station']
    actual = {}
    with ExitStack() as stack:
        mirrors = {}
        for name, deliveries in data['delivery'].items():
            db = stack.enter_context(closing(sqlite3.connect(directory / f'{name}.sqlite')))
            mirrors[name] = db
            initialize_mirror(db, data['stations'])
            for delivery in deliveries:
                accept(db, encode_document(_part(publications, delivery)))
            before = _book(db, station)
            accepted = accept(db, wire)
            if accepted.status != 'withdrawn':
                raise AssertionError(f'{name} did not settle the notice')
            adjustment = withdrawal_adjustment(db, notice.notice_id)
            actual[name] = {
                'before': before,
                'removed_origin_lines': [fact.provenance.line for fact in adjustment.removed],
                'row_delta': adjustment.row_delta,
                'litres_delta': adjustment.litres_delta,
                'after': _book(db, station),
            }
        mirrors['west'].close()
        west = stack.enter_context(closing(sqlite3.connect(directory / 'west.sqlite')))
        late_part = _part(publications, data['late_west'])
        late = accept(west, encode_document(late_part))
        east = mirrors['east']
        old_part = _part(publications, data['audit_east'])
        original = replay(east, old_part.part_id)
        downstream = {
            'west_late_status': late.status,
            'west_late_has_receipt': late.receipt is not None,
            'west_after_late': _book(west, station),
            'east_old_origins': list(original.origins.values()),
            'east_after_audit': _book(east, station),
        }
    return actual, downstream


def main():
    example = Path(__file__).parent
    data = json.loads((example / 'day.json').read_text(encoding='utf-8'))
    expected = json.loads((example / 'expected.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='binti-demo-') as directory:
        actual, downstream = _workday(Path(directory), data)
    if actual != expected['expected'] or downstream != expected['downstream_expected']:
        raise AssertionError({'expected': expected, 'actual': actual, 'downstream_actual': downstream})
    evidence = {
        'case_id': 'n6', 'input': data, 'expected': expected['expected'], 'actual': actual,
        'downstream_expected': expected['downstream_expected'], 'downstream_actual': downstream,
        'code_paths': ['lake/release/withdrawals.py', 'lake/mirror/acceptance.py', 'lake/mirror/evidence.py',
                       'lake/book/adjustments.py', 'lake/book/queries.py', 'lake/audit/history.py'],
        'oracle': '按输入送件单展开手算。东区 A 同时有 P 和 Q，撤 P 只退出 B 的 11 L。西区 A 仅有 P，退出 7 L，未收 B 无冲销量且随后仍不得入账。',
    }
    print('POINTWISE_SCENARIO ' + json.dumps(evidence, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
