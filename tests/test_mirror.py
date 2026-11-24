from dataclasses import replace

from lake.audit.history import replay
from lake.book.queries import station_book
from lake.intake.provenance import Provenance
from lake.mirror.acceptance import accept
from lake.mirror.conflicts import DocumentConflict
from lake.mirror.evidence import read_received_part
from lake.release.formats import encode_document

from tests import LakeTestCase


class MirrorTests(LakeTestCase):
    def test_overlap_and_distinct_equal_value(self):
        source = self.source()
        frozen, p, q, r = self.issue_day(source)
        mirror = self.mirror('east')
        first = accept(mirror, encode_document(p.parts[0]))
        self.assertEqual(first.status, 'received')
        self.assertEqual(accept(mirror, p.parts[0]), first)
        second = accept(mirror, q.parts[0])
        self.assertEqual(second.receipt.details['added_fact_ids'], [])
        self.assertEqual(second.receipt.details['facts'][0]['fact_id'], frozen.facts[0].fact_id)
        self.assertEqual(replay(mirror, first.receipt.receipt_id).receipt, first.receipt)
        accept(mirror, r.parts[0])
        book = station_book(mirror, '北闸')
        self.assertEqual((book.row_count, book.litres), (2, 14))
        self.assertEqual([fact.fact_id for fact in book.facts],
                         [frozen.facts[0].fact_id, frozen.facts[2].fact_id])
        self.assertEqual([fact.provenance.line for fact in book.facts], ['1', '3'])
        evidence = read_received_part(mirror, q.parts[0].part_id)
        self.assertEqual(evidence.document, q.parts[0])
        self.assertEqual(evidence.receipt_id, second.receipt.receipt_id)

    def test_same_part_number_different_content(self):
        source = self.source()
        _, p, q, _ = self.issue_day(source)
        mirror = self.mirror('east')
        part = p.parts[0]
        original = accept(mirror, part)
        original_book = station_book(mirror, '北闸')
        original_history = replay(mirror, part.part_id)
        fact = part.facts[0]
        for changed in (replace(fact, litres=8), replace(fact, provenance=Provenance('另一本日报', '1'))):
            with self.subTest(changed=changed):
                with self.assertRaises(DocumentConflict):
                    accept(mirror, replace(part, facts=(changed,)))
        foreign_claim = replace(q.parts[0], facts=(replace(fact, provenance=Provenance('错报', '1')),))
        with self.assertRaises(DocumentConflict):
            accept(mirror, foreign_claim)
        self.assertIsNone(read_received_part(mirror, q.parts[0].part_id))
        self.assertEqual(replay(mirror, part.part_id), original_history)
        self.assertEqual(replay(mirror, part.part_id).origins[fact.fact_id],
                         {'record': '北闸/日报-01', 'line': '1'})
        self.assertEqual(accept(mirror, part), original)
        self.assertEqual(station_book(mirror, '北闸'), original_book)
