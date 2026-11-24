from lake.audit.history import HistoryNotFound, replay
from lake.audit.requests import RequestConflict
from lake.intake.batches import BatchInput, batch_identity
from lake.intake.freeze import freeze
from lake.intake.frozen_store import read_frozen_batch
from lake.intake.provenance import Provenance
from lake.intake.rows import SourceRow
from lake.release.formats import decode_document, encode_document
from lake.release.issues import issue

from tests import LakeTestCase


class PublicationTests(LakeTestCase):
    def test_freeze_and_reissue(self):
        source = self.source()
        frozen = self.freeze_day(source)
        a, b, c = frozen.facts
        self.assertEqual([fact.litres for fact in frozen.facts], [7, 11, 7])
        self.assertEqual([fact.row_id for fact in frozen.facts], ['row-1', 'row-2', 'row-3'])
        self.assertNotEqual(a.fact_id, c.fact_id)
        self.assertEqual(self.freeze_day(source), frozen)
        self.assertEqual(replay(source, frozen.batch_id).origins[c.fact_id],
                         {'record': '北闸/日报-01', 'line': '3'})
        order = (a.fact_id, b.fact_id, c.fact_id)
        layout = ((c.fact_id, a.fact_id), (b.fact_id,))
        published = issue(source, '逆序发行', order, layout)
        self.assertEqual([part.position for part in published.parts], [0, 1])
        self.assertEqual([[fact.fact_id for fact in part.facts] for part in published.parts],
                         [[c.fact_id, a.fact_id], [b.fact_id]])
        self.assertEqual([[fact.provenance.line for fact in part.facts] for part in published.parts],
                         [['3', '1'], ['2']])
        source.close()
        source = self.source()
        history = replay(source, published.publication_id)
        self.assertEqual(history.documents, published.parts)
        self.assertEqual(history.receipt, published.receipt)
        self.assertEqual(history.origins[a.fact_id], {'record': '北闸/日报-01', 'line': '1'})
        self.assertEqual(issue(source, '逆序发行', order, layout), published)
        self.assertEqual(decode_document(encode_document(history.documents[0])), published.parts[0])
        self.assertEqual(read_frozen_batch(source, frozen.batch_id), frozen.facts)
        with self.assertRaises(RequestConflict):
            issue(source, '逆序发行', order, ((a.fact_id, c.fact_id), (b.fact_id,)))

    def test_invalid_batch_is_atomic(self):
        source = self.source()
        first = SourceRow('row-1', 7, Provenance('原表', '1'))
        origin = Provenance('原表', '2')
        for invalid in (11.0, True, None, '11'):
            with self.subTest(invalid=invalid):
                batch = BatchInput('北闸', '拒批-01', (first, SourceRow('row-2', invalid, origin)))
                with self.assertRaises(ValueError):
                    freeze(source, batch)
        source.close()
        source = self.source()
        number = batch_identity('北闸', '拒批-01')
        self.assertEqual(read_frozen_batch(source, number), ())
        self.assertEqual(source.execute('SELECT COUNT(*) FROM frozen_facts').fetchone()[0], 0)
        self.assertEqual(source.execute('SELECT COUNT(*) FROM frozen_batches').fetchone()[0], 0)
        with self.assertRaises(HistoryNotFound):
            replay(source, number)
        corrected = freeze(source, BatchInput('北闸', '拒批-01', (first, SourceRow('row-2', 11, origin))))
        self.assertEqual((corrected.batch_id, len(corrected.facts)), (number, 2))
        with self.assertRaises(RequestConflict):
            freeze(source, BatchInput('北闸', '拒批-01', (first,)))

    def test_overlap_keeps_fact_identity(self):
        source = self.source()
        frozen, p, q, r = self.issue_day(source)
        self.assertEqual(len({p.publication_id, q.publication_id, r.publication_id}), 3)
        self.assertNotEqual(p.parts[0].part_id, q.parts[0].part_id)
        self.assertEqual(p.parts[0].facts, q.parts[0].facts)
        self.assertEqual(q.parts[0].facts[0].fact_id, frozen.facts[0].fact_id)
        self.assertEqual(q.parts[0].facts[0].provenance, Provenance('北闸/日报-01', '1'))
        self.assertNotEqual(r.parts[0].facts[0].fact_id, frozen.facts[0].fact_id)
