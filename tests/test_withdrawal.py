from dataclasses import replace

from lake.audit.history import HistoryNotFound, replay
from lake.book.queries import station_book, withdrawal_adjustment
from lake.mirror.acceptance import accept
from lake.mirror.conflicts import DocumentConflict
from lake.mirror.evidence import read_received_part
from lake.mirror.transactions import CommitInterrupted
from lake.release.formats import encode_document
from lake.release.withdrawals import withdraw_issue

from tests import LakeTestCase


class WithdrawalTests(LakeTestCase):
    def test_offline_two_mirrors_settle_differently(self):
        source = self.source()
        frozen, p, q, _ = self.issue_day(source)
        a, b, _ = frozen.facts
        east = self.mirror('east')
        west = self.mirror('west')
        accept(east, p.parts[0])
        old_b = accept(east, p.parts[1])
        accept(east, q.parts[0])
        accept(west, p.parts[0])
        self.assertEqual(station_book(east, '北闸').litres, 18)
        self.assertEqual(station_book(west, '北闸').litres, 7)
        issued = withdraw_issue(source, '撤回-P', p.publication_id)
        wire = encode_document(issued.notice)
        source.close()
        east_result = accept(east, wire)
        west_result = accept(west, wire)
        actual = []
        for db, result in ((east, east_result), (west, west_result)):
            self.assertEqual(result.status, 'withdrawn', 'POINTWISE_N6_SETTLEMENT')
            adjustment = result.adjustment
            book = station_book(db, '北闸')
            actual.append((tuple(fact.fact_id for fact in adjustment.removed),
                           tuple(fact.provenance.line for fact in adjustment.removed),
                           adjustment.row_delta, adjustment.litres_delta, book.row_count, book.litres))
            self.assertEqual(withdrawal_adjustment(db, issued.notice.notice_id), adjustment)
            self.assertEqual(replay(db, issued.notice.notice_id).adjustment, adjustment)
        self.assertEqual(actual, [((b.fact_id,), ('2',), -1, -11, 1, 7),
                                  ((a.fact_id,), ('1',), -1, -7, 0, 0)], 'POINTWISE_N6_SETTLEMENT')
        self.assertEqual([fact.fact_id for fact in station_book(east, '北闸').facts], [a.fact_id])
        history = replay(east, old_b.receipt.receipt_id)
        self.assertEqual(history.receipt, old_b.receipt)
        self.assertEqual(history.receipt.details['facts'],
                         [{'fact_id': b.fact_id, 'station': '北闸', 'litres': '11'}])
        self.assertEqual(history.origins[b.fact_id], {'record': '北闸/日报-01', 'line': '2'})
        self.assertEqual(replay(east, issued.notice.notice_id).origins, history.origins)
        self.assertEqual(accept(east, p.parts[1]), old_b)
        self.assertEqual(station_book(east, '北闸').litres, 7)
        west.close()
        west = self.mirror('west')
        self.assertEqual(accept(west, p.parts[1]).status, 'late', 'POINTWISE_N7_LATE_PART')
        self.assertEqual(station_book(west, '北闸').litres, 0)

    def test_withdrawal_before_parts(self):
        source = self.source()
        frozen, p, q, r = self.issue_day(source)
        issued = withdraw_issue(source, '撤回-P', p.publication_id)
        source.close()
        mirror = self.mirror('east')
        result = accept(mirror, encode_document(issued.notice))
        self.assertEqual(result.status, 'withdrawn')
        self.assertEqual((result.adjustment.removed, result.adjustment.row_delta,
                          result.adjustment.litres_delta, result.adjustment.by_station), ((), 0, 0, ()))
        mirror.close()
        mirror = self.mirror('east')
        self.assertEqual(replay(mirror, issued.notice.notice_id).receipt, result.receipt)
        for part in reversed(p.parts):
            late = accept(mirror, part)
            self.assertEqual((late.status, late.receipt), ('late', None), 'POINTWISE_N7_LATE_PART')
            self.assertIsNone(read_received_part(mirror, part.part_id))
            with self.assertRaises(HistoryNotFound):
                replay(mirror, part.part_id)
        self.assertEqual(station_book(mirror, '北闸').litres, 0)
        accept(mirror, q.parts[0])
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        accept(mirror, r.parts[0])
        book = station_book(mirror, '北闸')
        self.assertEqual((book.row_count, book.litres), (2, 14))
        self.assertEqual([fact.fact_id for fact in book.facts],
                         [frozen.facts[0].fact_id, frozen.facts[2].fact_id])
        self.assertEqual(accept(mirror, issued.notice), result)
        self.assertEqual(station_book(mirror, '北闸'), book)

    def test_commit_failure_then_reopen(self):
        source = self.source()
        _, p, q, _ = self.issue_day(source)
        notice = withdraw_issue(source, '撤回-P', p.publication_id).notice
        source.close()
        mirror = self.mirror('west')
        original = accept(mirror, p.parts[0])
        original_book = station_book(mirror, '北闸')
        with self.assertRaises(CommitInterrupted):
            accept(mirror, notice, fail_before_commit=True)
        reader = self.connect('west')
        self.assertEqual(station_book(reader, '北闸'), original_book)
        self.assertEqual(original_book.litres, 7)
        self.assertEqual(replay(reader, original.receipt.receipt_id).receipt, original.receipt)
        with self.assertRaises(HistoryNotFound):
            replay(reader, notice.notice_id)
        with self.assertRaises(HistoryNotFound):
            withdrawal_adjustment(reader, notice.notice_id)
        mirror.close()
        mirror = self.mirror('west')
        finished = accept(mirror, notice)
        self.assertEqual(finished.status, 'withdrawn')
        self.assertEqual(finished.adjustment.litres_delta, -7)
        self.assertEqual(accept(mirror, notice), finished)
        self.assertEqual(accept(mirror, p.parts[0]), original)
        self.assertEqual(accept(mirror, p.parts[1]).status, 'late')
        with self.assertRaises(DocumentConflict):
            accept(mirror, replace(notice, publication_id=q.publication_id))
        self.assertEqual(withdrawal_adjustment(reader, notice.notice_id), finished.adjustment)
        self.assertEqual((station_book(reader, '北闸').row_count, station_book(reader, '北闸').litres), (0, 0))
