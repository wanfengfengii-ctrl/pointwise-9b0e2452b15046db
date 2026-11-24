import json

from examples.station_case import STATIONS, build_source, changed_origin, make_trust
from lake.audit.history import HistoryNotFound, replay
from lake.book.queries import station_book
from lake.mirror.acceptance import accept
from lake.mirror.conflicts import DocumentConflict
from lake.mirror.evidence import read_received_part
from lake.mirror.transactions import CommitInterrupted
from lake.release.formats import encode_document
from lake.release.parts import export_station_part
from lake.release.withdrawals import withdraw_issue

from tests import LakeTestCase


class StationDeliveryTests(LakeTestCase):
    def setUp(self):
        super().setUp()
        self.attest, self.verify = make_trust()

    def build(self, **kwargs):
        source = self.source()
        part, overlap, notice = build_source(source, **kwargs)
        return source, part, overlap, notice

    def test_export_station_part_shape_and_determinism(self):
        source, part, _, _ = self.build()
        a, b = part.facts
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        self.assertEqual(north['kind'], 'station_part')
        self.assertEqual(north['part_id'], part.part_id)
        self.assertEqual(north['publication_id'], part.publication_id)
        self.assertEqual(north['position'], part.position)
        self.assertEqual(north['station'], '北闸')
        self.assertEqual(north['rows'], [{
            'ordinal': 0,
            'fact': {'fact_id': a.fact_id, 'station': '北闸', 'litres': '7',
                     'origin': {'record': '北闸日报', 'line': '1'}},
        }])
        self.assertEqual(south['rows'], [{
            'ordinal': 1,
            'fact': {'fact_id': b.fact_id, 'station': '南堤', 'litres': '11',
                     'origin': {'record': '南堤日报', 'line': '1'}},
        }])
        self.assertEqual(len({north['station_part_id'], south['station_part_id'], part.part_id}), 3)
        self.assertEqual(json.loads(json.dumps(north)), north)
        self.assertEqual(export_station_part(source, part.part_id, '北闸', attest=self.attest), north)
        self.assertEqual(export_station_part(source, part.part_id, '南堤', attest=self.attest), south)
        with self.assertRaises(HistoryNotFound):
            export_station_part(source, 'part:missing', '北闸', attest=self.attest)
        with self.assertRaises(ValueError):
            export_station_part(source, part.part_id, '西渠', attest=self.attest)
        with self.assertRaises(ValueError):
            export_station_part(source, part.part_id, '', attest=self.attest)
        with self.assertRaises(ValueError):
            export_station_part(source, part.part_id, '北闸', attest=None)

    def test_extra_north_rows_keep_original_positions(self):
        source, part, _, _ = self.build(extra_north=True)
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        self.assertEqual([row['ordinal'] for row in north['rows']], [0, 2])
        self.assertEqual([row['fact']['litres'] for row in north['rows']], ['7', '7'])
        self.assertEqual([row['ordinal'] for row in south['rows']], [1])
        source.close()
        mirror = self.mirror('east')
        result = accept(mirror, north, verify=self.verify)
        self.assertEqual(result.status, 'received')
        self.assertEqual(result.receipt.details['ordinals'], [0, 2])
        self.assertEqual(len(result.receipt.details['added_fact_ids']), 2)
        self.assertEqual(station_book(mirror, '北闸').litres, 14)
        self.assertEqual(station_book(mirror, '南堤').litres, 0)

    def test_offline_station_parts_then_whole_completion(self):
        source, part, _, _ = self.build()
        a, b = part.facts
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        first = accept(mirror, north, verify=self.verify)
        self.assertEqual(first.status, 'received')
        self.assertEqual(first.receipt.receipt_id, north['station_part_id'])
        self.assertEqual(first.receipt.details, {
            'part_id': part.part_id, 'station': '北闸', 'ordinals': [0],
            'facts': [{'fact_id': a.fact_id, 'station': '北闸', 'litres': '7'}],
            'added_fact_ids': [a.fact_id],
        })
        self.assertEqual(first.receipt.origins, {a.fact_id: {'record': '北闸日报', 'line': '1'}})
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 0)
        second = accept(mirror, json.dumps(south, ensure_ascii=False), verify=self.verify)
        self.assertEqual(second.receipt.receipt_id, south['station_part_id'])
        self.assertEqual(second.receipt.details['ordinals'], [1])
        self.assertEqual(second.receipt.details['added_fact_ids'], [b.fact_id])
        self.assertEqual(station_book(mirror, '南堤').litres, 11)
        whole = accept(mirror, encode_document(part))
        self.assertEqual(whole.status, 'received')
        self.assertEqual(whole.receipt.receipt_id, part.part_id)
        self.assertEqual(whole.receipt.details['added_fact_ids'], [])
        self.assertEqual([fact['fact_id'] for fact in whole.receipt.details['facts']],
                         [a.fact_id, b.fact_id])
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 11)

    def test_whole_part_first_then_station_parts(self):
        source, part, _, _ = self.build()
        a, b = part.facts
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        whole = accept(mirror, encode_document(part))
        self.assertEqual(whole.receipt.details['added_fact_ids'], [a.fact_id, b.fact_id])
        first_north = accept(mirror, north, verify=self.verify)
        self.assertEqual(first_north.status, 'received')
        self.assertEqual(first_north.receipt.receipt_id, north['station_part_id'])
        self.assertEqual(first_north.receipt.details['added_fact_ids'], [])
        first_south = accept(mirror, south, verify=self.verify)
        self.assertEqual(first_south.receipt.details['added_fact_ids'], [])
        self.assertEqual(replay(mirror, part.part_id).receipt, whole.receipt)
        self.assertEqual(replay(mirror, north['station_part_id']).receipt, first_north.receipt)
        self.assertEqual(replay(mirror, south['station_part_id']).receipt, first_south.receipt)
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 11)

    def test_whole_part_must_match_verified_original(self):
        source, part, _, _ = self.build()
        _, b = part.facts
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        accept(mirror, north, verify=self.verify)
        forged = changed_origin(part, 1)
        with self.assertRaises(DocumentConflict):
            accept(mirror, encode_document(forged))
        self.assertIsNone(read_received_part(mirror, part.part_id))
        with self.assertRaises(HistoryNotFound):
            replay(mirror, part.part_id)
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 0)
        whole = accept(mirror, encode_document(part))
        self.assertEqual(whole.status, 'received')
        self.assertEqual(whole.receipt.details['added_fact_ids'], [b.fact_id])
        self.assertEqual(station_book(mirror, '南堤').litres, 11)

    def test_tampered_station_part_rejected(self):
        source, part, _, _ = self.build()
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('east')

        def tampered():
            return json.loads(json.dumps(north))

        bad_token = tampered()
        bad_token['proof']['token'] = '0' * 64
        bad_digest = tampered()
        bad_digest['proof']['original_sha256'] = '1' * 64
        changed_litres = tampered()
        changed_litres['rows'][0]['fact']['litres'] = '8'
        changed_ordinal = tampered()
        changed_ordinal['rows'][0]['ordinal'] = 1
        missing_proof = tampered()
        del missing_proof['proof']
        foreign_row = tampered()
        foreign_row['rows'].append({
            'ordinal': 1,
            'fact': {'fact_id': 'fact:foreign', 'station': '南堤', 'litres': '11',
                     'origin': {'record': '南堤日报', 'line': '1'}},
        })
        for document in (bad_token, bad_digest, changed_litres, changed_ordinal,
                         missing_proof, foreign_row):
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    accept(mirror, document, verify=self.verify)
        with self.assertRaises(ValueError):
            accept(mirror, north)
        self.assertEqual(station_book(mirror, '北闸').litres, 0)
        with self.assertRaises(HistoryNotFound):
            replay(mirror, north['station_part_id'])
        accepted = accept(mirror, north, verify=self.verify)
        self.assertEqual(accepted.status, 'received')
        self.assertEqual(station_book(mirror, '北闸').litres, 7)

    def test_same_station_part_number_different_content(self):
        source, part, _, _ = self.build()
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        original = accept(mirror, north, verify=self.verify)
        original_book = station_book(mirror, '北闸')
        altered = json.loads(json.dumps(north))
        altered['proof']['token'] = '0' * 64
        with self.assertRaises(DocumentConflict):
            accept(mirror, altered, verify=self.verify)
        self.assertEqual(accept(mirror, north, verify=self.verify), original)
        self.assertEqual(station_book(mirror, '北闸'), original_book)

    def test_redelivery_and_reopen_replay(self):
        source, part, _, _ = self.build()
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        first = accept(mirror, north, verify=self.verify)
        self.assertEqual(accept(mirror, north, verify=self.verify), first)
        self.assertEqual(accept(mirror, json.dumps(north, ensure_ascii=False), verify=self.verify), first)
        accept(mirror, south, verify=self.verify)
        mirror.close()
        mirror = self.mirror('east')
        history = replay(mirror, north['station_part_id'])
        self.assertEqual(history.receipt, first.receipt)
        self.assertEqual(history.origins, first.receipt.origins)
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 11)
        self.assertEqual(accept(mirror, north, verify=self.verify), first)

    def test_withdrawal_settles_only_facts_without_evidence(self):
        source, part, overlap, notice = self.build()
        _, b = part.facts
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        south = export_station_part(source, part.part_id, '南堤', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        accept(mirror, north, verify=self.verify)
        accept(mirror, south, verify=self.verify)
        accept(mirror, encode_document(overlap))
        result = accept(mirror, encode_document(notice))
        self.assertEqual(result.status, 'withdrawn')
        self.assertEqual([fact.fact_id for fact in result.adjustment.removed], [b.fact_id])
        self.assertEqual(result.adjustment.litres_delta, -11)
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(station_book(mirror, '南堤').litres, 0)
        self.assertEqual(replay(mirror, north['station_part_id']).receipt.receipt_id,
                         north['station_part_id'])
        reclaimed = accept(mirror, north, verify=self.verify)
        self.assertEqual(reclaimed.status, 'received')
        self.assertEqual(reclaimed.receipt.receipt_id, north['station_part_id'])
        late = accept(mirror, encode_document(part))
        self.assertEqual((late.status, late.receipt), ('late', None))
        with self.assertRaises(HistoryNotFound):
            replay(mirror, part.part_id)
        self.assertEqual(station_book(mirror, '北闸').litres, 7)

    def test_station_part_after_withdrawal_is_late(self):
        source, part, overlap, notice = self.build()
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('west')
        accept(mirror, encode_document(notice))
        late = accept(mirror, north, verify=self.verify)
        self.assertEqual((late.status, late.receipt), ('late', None))
        self.assertEqual(station_book(mirror, '北闸').litres, 0)
        with self.assertRaises(HistoryNotFound):
            replay(mirror, north['station_part_id'])
        self.assertEqual(accept(mirror, encode_document(overlap)).status, 'received')
        self.assertEqual(station_book(mirror, '北闸').litres, 7)

    def test_station_evidence_registered_under_original_publication(self):
        source, part, overlap, _ = self.build()
        notice_q = withdraw_issue(source, '撤Q', overlap.publication_id).notice
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('east')
        accept(mirror, encode_document(overlap))
        second = accept(mirror, north, verify=self.verify)
        self.assertEqual(second.receipt.details['added_fact_ids'], [])
        result = accept(mirror, encode_document(notice_q))
        self.assertEqual(result.adjustment.removed, ())
        self.assertEqual(station_book(mirror, '北闸').litres, 7)

    def test_commit_interruption_rolls_back_then_retry(self):
        source, part, _, _ = self.build()
        north = export_station_part(source, part.part_id, '北闸', attest=self.attest)
        source.close()
        mirror = self.mirror('west')
        with self.assertRaises(CommitInterrupted):
            accept(mirror, north, verify=self.verify, fail_before_commit=True)
        reader = self.connect('west')
        self.assertEqual(station_book(reader, '北闸').litres, 0)
        with self.assertRaises(HistoryNotFound):
            replay(reader, north['station_part_id'])
        mirror.close()
        mirror = self.mirror('west')
        result = accept(mirror, north, verify=self.verify)
        self.assertEqual(result.status, 'received')
        self.assertEqual(station_book(mirror, '北闸').litres, 7)
        self.assertEqual(replay(mirror, north['station_part_id']).receipt, result.receipt)
