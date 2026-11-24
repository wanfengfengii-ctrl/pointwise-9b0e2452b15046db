import json

from lake.audit.history import HistoryNotFound, replay
from lake.audit.requests import RequestConflict
from lake.book.queries import station_book, withdrawal_adjustment
from lake.mirror.acceptance import accept
from lake.release.formats import encode_document
from lake.release.issues import issue
from lake.release.membership import MemberSelectionError
from lake.release.withdrawals import withdraw_issue

from tests import LakeTestCase


class WorkdayTests(LakeTestCase):
    def test_source_issuance_rejection_reopen_and_original_withdrawal(self):
        db = self.source()
        frozen = self.freeze_day(db)
        a, b, _ = (fact.fact_id for fact in frozen.facts)
        with self.assertRaises(MemberSelectionError):
            issue(db, '发行', (a, b), ((a,),))
        with self.assertRaises(MemberSelectionError):
            issue(db, '发行', ('未冻结',), (('未冻结',),))
        with self.assertRaises(HistoryNotFound):
            withdraw_issue(db, '撤', '未知发布')
        db.close()
        db = self.source()
        p = issue(db, '发行', (a, b), ((b,), (a,)))
        q = issue(db, '发行-Q', (a,), ((a,),))
        original = withdraw_issue(db, '撤', p.publication_id)
        db.close()
        db = self.source()
        self.assertEqual(withdraw_issue(db, '撤', p.publication_id), original)
        self.assertEqual(withdraw_issue(db, '再次办理', p.publication_id), original)
        with self.assertRaises(RequestConflict):
            withdraw_issue(db, '再次办理', q.publication_id)
        self.assertEqual(replay(db, original.notice.notice_id).documents, (original.notice,))
        self.assertEqual(replay(db, p.publication_id).documents, p.parts)

    def test_repeated_loss_and_reacquisition_preserves_original_adjustments(self):
        source = self.source()
        frozen, p, q, _ = self.issue_day(source)
        a, b, _ = frozen.facts
        s = issue(source, 'S', (a.fact_id,), ((a.fact_id,),))
        notice_p = withdraw_issue(source, '撤-P', p.publication_id).notice
        notice_q = withdraw_issue(source, '撤-Q', q.publication_id).notice
        source.close()
        db = self.mirror('east')
        accept(db, q.parts[0])
        accept(db, p.parts[1])
        accept(db, p.parts[0])
        first = accept(db, notice_p).adjustment
        self.assertEqual([fact.fact_id for fact in first.removed], [b.fact_id])
        second = accept(db, notice_q).adjustment
        self.assertEqual([fact.fact_id for fact in second.removed], [a.fact_id])
        self.assertEqual(station_book(db, '北闸').litres, 0)
        db.close()
        db = self.mirror('east')
        accept(db, s.parts[0])
        self.assertEqual(station_book(db, '北闸').litres, 7)
        self.assertEqual(accept(db, notice_p).adjustment, first)
        self.assertEqual(withdrawal_adjustment(db, notice_q.notice_id), second)
        self.assertEqual(station_book(db, '北闸').litres, 7)

    def test_invalid_wire_document_never_creates_receipt(self):
        source = self.source()
        _, p, _, _ = self.issue_day(source)
        document = p.parts[0]
        db = self.mirror('west')
        fields = json.loads(encode_document(document))
        fields['facts'][0]['litres'] = '07'
        with self.assertRaises(ValueError):
            accept(db, json.dumps(fields))
        fields = json.loads(encode_document(document))
        fields['position'] = 2
        with self.assertRaises(ValueError):
            accept(db, json.dumps(fields))
        with self.assertRaises(ValueError):
            accept(db, '{"version":1,"version":1}')
        with self.assertRaises(HistoryNotFound):
            replay(db, document.part_id)
        self.assertEqual(station_book(db, '北闸').litres, 0)
        self.assertEqual(accept(db, document).status, 'received')
