import sqlite3
import unittest
from contextlib import ExitStack, closing
from pathlib import Path
from tempfile import TemporaryDirectory

from lake.intake.batches import BatchInput
from lake.intake.freeze import freeze, initialize_freeze
from lake.intake.provenance import Provenance
from lake.intake.rows import SourceRow
from lake.mirror.acceptance import initialize_mirror
from lake.release.issues import initialize_release, issue
from lake.release.withdrawals import initialize_withdrawals


class LakeTestCase(unittest.TestCase):
    def setUp(self):
        self.resources = ExitStack()
        self.addCleanup(self.resources.close)
        self.directory = Path(self.resources.enter_context(TemporaryDirectory(prefix='binti-test-')))

    def connect(self, name):
        return self.resources.enter_context(closing(sqlite3.connect(self.directory / f'{name}.sqlite')))

    def source(self):
        db = self.connect('source')
        initialize_freeze(db)
        initialize_release(db)
        initialize_withdrawals(db)
        return db

    def mirror(self, name, stations=('北闸', '南堤')):
        db = self.connect(name)
        initialize_mirror(db, stations)
        return db

    def freeze_day(self, source, values=(7, 11, 7), *, station='北闸', batch='日报-01'):
        rows = tuple(
            SourceRow(f'row-{position}', value, Provenance(f'{station}/{batch}', str(position)))
            for position, value in enumerate(values, 1)
        )
        return freeze(source, BatchInput(station, batch, rows))

    def issue_day(self, source):
        frozen = self.freeze_day(source)
        a, b, c = (fact.fact_id for fact in frozen.facts)
        p = issue(source, 'P', (a, b), ((a,), (b,)))
        q = issue(source, 'Q', (a,), ((a,),))
        r = issue(source, 'R', (c,), ((c,),))
        return frozen, p, q, r
