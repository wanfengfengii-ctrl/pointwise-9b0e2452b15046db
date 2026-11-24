from lake.book.queries import station_book, withdrawal_adjustment
from lake.book.stations import UnknownStation, register_station
from lake.mirror.acceptance import accept, initialize_mirror
from lake.mirror.transactions import mirror_write
from lake.release.formats import encode_document
from lake.release.issues import issue
from lake.release.withdrawals import withdraw_issue

from tests import LakeTestCase


class StationBookTests(LakeTestCase):
    def test_exact_litres_with_replay_and_overlap(self):
        source = self.source()
        large = 9223372036854775809
        frozen = self.freeze_day(source, (large, large))
        a, b = (fact.fact_id for fact in frozen.facts)
        p = issue(source, '大额-P', (a, b), ((a,), (b,)))
        q = issue(source, '大额-Q', (a,), ((a,),))
        db = self.mirror('east')
        first = accept(db, encode_document(p.parts[0]))
        self.assertEqual(accept(db, p.parts[0]), first)
        accept(db, p.parts[1])
        accept(db, q.parts[0])
        book = station_book(db, '北闸')
        self.assertEqual((book.row_count, book.litres), (2, 18446744073709551618))
        self.assertEqual([fact.litres for fact in book.facts], [large, large])
        self.assertEqual([fact.provenance.line for fact in book.facts], ['1', '2'])
        notice = withdraw_issue(source, '撤回大额-P', p.publication_id).notice
        accept(db, notice)
        self.assertEqual(withdrawal_adjustment(db, notice.notice_id).litres_delta, -9223372036854775809)
        self.assertEqual(station_book(db, '北闸').litres, large)

    def test_known_empty_station_and_reopen(self):
        db = self.mirror('west')
        empty = station_book(db, '南堤')
        self.assertEqual((empty.facts, empty.row_count, empty.litres), ((), 0, 0))
        with self.assertRaises(UnknownStation):
            station_book(db, '未知')
        with mirror_write(db):
            register_station(db, '次班新站')
        source = self.source()
        frozen = self.freeze_day(source, (7,))
        number = frozen.facts[0].fact_id
        part = issue(source, '站账重开', (number,), ((number,),)).parts[0]
        accept(db, part)
        db.close()
        db = self.connect('west')
        initialize_mirror(db, ('其他新清单',))
        initialize_mirror(db, ())
        self.assertEqual(station_book(db, '南堤'), empty)
        self.assertEqual((station_book(db, '次班新站').row_count, station_book(db, '次班新站').litres), (0, 0))
        self.assertEqual(station_book(db, '北闸').litres, 7)
        with self.assertRaises(UnknownStation):
            station_book(db, '其他新清单')

    def test_signed_and_zero_litres_by_station(self):
        source = self.source()
        north = self.freeze_day(source, (0, -8))
        south = self.freeze_day(source, (5,), station='新渠')
        ids = tuple(fact.fact_id for fact in north.facts + south.facts)
        released = issue(source, '联合站账', ids, (ids,))
        db = self.mirror('west')
        with self.assertRaises(UnknownStation):
            station_book(db, '新渠')
        accept(db, released.parts[0])
        north_book = station_book(db, '北闸')
        self.assertEqual((north_book.row_count, north_book.litres), (2, -8))
        self.assertEqual([fact.litres for fact in north_book.facts], [0, -8])
        self.assertEqual(station_book(db, '新渠').litres, 5)
        notice = withdraw_issue(source, '撤联合', released.publication_id).notice
        result = accept(db, notice)
        adjustment = result.adjustment
        self.assertEqual((adjustment.row_delta, adjustment.litres_delta), (-3, 3))
        self.assertEqual({d.station: (d.row_delta, d.litres_delta) for d in adjustment.by_station},
                         {'北闸': (-2, 8), '新渠': (-1, -5)})
        self.assertEqual({fact.fact_id for fact in adjustment.removed}, set(ids))
        self.assertEqual(station_book(db, '新渠').litres, 0)
