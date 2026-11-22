import sqlite3

from handover.retrieve import retrieve
from handover.sector_lists import publish
from handover.shift_book import MissingSectors, close_shift
from measurements.extrema import ReadingSummary
from tests.support import NORTH, WEST, InspectionCase


class HandoverTests(InspectionCase):
    def test_close_and_reopen(self):
        west = self.capture('B', 'west')
        north = self.capture('A', 'north')
        book = close_shift(self.archive, 'day', ['B', 'A'])
        self.assertEqual([sector.sector_id for sector in book.sectors], ['north', 'west'])
        self.assertEqual([sector.order_id for sector in book.sectors], ['A', 'B'])
        self.assertEqual(book.summary, ReadingSummary(2, 1, 7, 11))
        self.assertEqual(book.receipt.receipt_id, 'shift:day')
        self.source.close()
        self.assert_domain_error('source_closed', self.source.read_source, 'day', 'north')
        self.reopen()
        offline = retrieve(self.archive, 'day', kind='shift')
        self.assertEqual(offline.output, book)
        self.assertEqual(offline.receipt, book.receipt)
        self.assertEqual([sector.original for sector in offline.output.sectors], [NORTH, WEST])
        self.assertEqual([sector.origin.file_id for sector in offline.output.sectors], ['f-A', 'f-B'])
        self.assertEqual([[row.source_line for row in sector.rows] for sector in offline.output.sectors], [[2, 3], [2]])
        for frozen in (north, west):
            output = retrieve(self.archive, frozen.order_id)
            self.assertEqual(output.output, frozen)
            self.assertEqual(output.receipt, frozen.receipt)
        self.assertEqual(close_shift(self.archive, 'day', ['A', 'B']), book)

    def test_missing_sector(self):
        self.capture('A', 'north')
        self.assertEqual(close_shift(self.archive, 'day', ['A']), MissingSectors('day', ('west',)))
        self.assert_unpublished('day', kind='shift')

    def test_received_unpublished(self):
        self.capture('A', 'north')
        self.capture('B', 'west', sign=False)
        self.assertEqual(close_shift(self.archive, 'day', ['B', 'A']), MissingSectors('day', ('west',)))
        self.assert_unpublished('B')
        self.assert_unpublished('day', kind='shift')
        publish(self.archive, 'B')
        self.assertEqual(close_shift(self.archive, 'day', ['B', 'A']).summary, ReadingSummary(2, 1, 7, 11))

    def test_receipt_failure(self):
        north = self.capture('A', 'north')
        self.capture('B', 'west', sign=False)
        self.db.execute('''
            CREATE TRIGGER deny_b_receipt BEFORE INSERT ON first_receipts
            WHEN NEW.kind = 'sector' AND NEW.output_id = 'B'
            BEGIN SELECT RAISE(ABORT, 'test failure at receipt insert'); END
        ''')
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'test failure at receipt insert'):
            publish(self.archive, 'B')
        self.assert_unpublished('B')
        self.reopen()
        self.assert_unpublished('B')
        self.assertEqual(retrieve(self.archive, 'A').output, north)
        self.db.execute('DROP TRIGGER deny_b_receipt')
        west = publish(self.archive, 'B')
        self.assertEqual(west.original, WEST)
        self.assertEqual(west.rows[0].reading_pa, 11)
        self.assertEqual(publish(self.archive, 'B').receipt, west.receipt)
        for table in ('frozen_outputs', 'first_receipts'):
            count = self.db.execute(f'SELECT COUNT(*) FROM {table} WHERE kind = ? AND output_id = ?',
                                    ('sector', 'B')).fetchone()[0]
            self.assertEqual(count, 1)

    def test_shift_membership_and_frozen_choice(self):
        self.capture('A', 'north')
        self.capture('A2', 'north')
        self.capture('B', 'west')
        self.assert_domain_error('duplicate_sector_list', close_shift, self.archive, 'day', ['A', 'A2', 'B'])
        book = close_shift(self.archive, 'day', ['A2', 'B'])
        self.assertEqual([item.order_id for item in book.sectors], ['A2', 'B'])
        self.assert_domain_error('output_conflict', close_shift, self.archive, 'day', ['A', 'B'])
        self.assertEqual(retrieve(self.archive, 'day', kind='shift').output, book)
        self.assert_unpublished('does-not-exist')
