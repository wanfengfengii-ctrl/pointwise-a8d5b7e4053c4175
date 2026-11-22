from collection.attempts import get_attempt
from collection.downloads import get_accepted, receive
from collection.orders import get_order, start
from handover.retrieve import retrieve
from handover.sector_lists import publish
from measurements.extrema import ReadingSummary
from roster.bootstrap import initialize
from roster.shifts import get_shift, register
from terminal.operator import load_selection, select
from terminal.recording import RecordedTerminal
from tests.support import NORTH, InspectionCase


class CaptureTests(InspectionCase):
    def receive_raw(self, order_id, raw):
        source = RecordedTerminal({('day', 'north'): raw})
        self.addCleanup(source.close)
        _, attempt = start(self.db, order_id, 'day', 'north')
        return attempt, self.artifact(self.generated(attempt, order_id, source))

    def assert_bad_rows(self, order_id, raw, code):
        attempt, artifact = self.receive_raw(order_id, raw)
        self.assert_domain_error(code, receive, self.db, artifact)
        self.assertEqual(get_attempt(self.db, attempt.attempt_id).status, 'waiting')
        self.assertIsNone(get_accepted(self.db, order_id))
        self.assert_domain_error('no_accepted_download', publish, self.archive, order_id)
        self.assert_unpublished(order_id)

    def test_single_capture(self):
        published = self.capture('A', 'north')
        self.assertEqual([(r.point_id, r.raw_value, r.source_line, r.reading_pa) for r in published.rows],
                         [('N1', '0.007', 2, 7), ('N2', 'NA', 3, None)])
        self.assertEqual(published.summary, ReadingSummary(1, 1, 7, 7))
        self.assertEqual((published.origin.generation_id, published.origin.file_id), ('g-A', 'f-A'))
        self.assertEqual(published.original, NORTH)
        output = retrieve(self.archive, 'A')
        self.assertEqual(output.output, published)
        self.assertEqual(output.receipt.receipt_id, 'sector:A')
        self.assertEqual(publish(self.archive, 'A'), published)

    def test_duplicate_point(self):
        self.assert_bad_rows('D', b'point,value\nN1,0.007\nN1,0.009\nN2,NA\n', 'row_duplicate')

    def test_out_of_roster(self):
        self.assert_bad_rows('X', b'point,value\nN1,0.007\nNX,NA\n', 'row_unexpected')

    def test_incomplete_rows(self):
        self.assert_bad_rows('X', b'point,value\nN1,0.007\n', 'row_missing')

    def test_invalid_value(self):
        for order_id, raw, code in (
            ('empty', b'point,value\nN1,\nN2,NA\n', 'row_value'),
            ('fraction', b'point,value\nN1,0.0007\nN2,NA\n', 'row_precision'),
            ('nonfinite', b'point,value\nN1,NaN\nN2,NA\n', 'row_value'),
        ):
            with self.subTest(order=order_id):
                self.assert_bad_rows(order_id, raw, code)

    def test_units_and_physical_source_line_order(self):
        raw = b'point,value\r\nN2,0\r\nN1,0.007\r\n'
        _, artifact = self.receive_raw('A', raw)
        receive(self.db, artifact)
        published = publish(self.archive, 'A')
        self.assertEqual([(r.point_id, r.source_line, r.reading_pa) for r in published.rows],
                         [('N1', 3, 7), ('N2', 2, 0)])
        self.assertEqual(published.summary, ReadingSummary(2, 0, 0, 7))
        self.assertEqual(published.original, raw)

    def test_multiline_csv_record_rejected(self):
        raw = b'point,value\nN1,"0.\n007"\nN2,NA\n'
        self.assert_bad_rows('A', raw, 'row_shape')

    def test_all_missing(self):
        _, artifact = self.receive_raw('A', b'point,value\nN1,NA\nN2,NA\n')
        receive(self.db, artifact)
        published = publish(self.archive, 'A')
        self.assertEqual(published.summary, ReadingSummary(0, 2, None, None))
        self.assertEqual([(r.source_line, r.reading_pa) for r in published.rows], [(2, None), (3, None)])

    def test_init_preserves_selection(self):
        original = get_shift(self.db, 'day')
        selected = select(self.db, 'day', 'north')
        self.reopen()
        defaults = [('day', [('north', [('OTHER', 'Pa')]), ('west', [('W1', 'Pa')])]),
                    ('relief', [('east', [('E1', 'Pa')])])]
        initialize(self.db, defaults, ('desk', 'east'))
        self.assertEqual(get_shift(self.db, 'day'), original)
        self.assertEqual([s.sector_id for s in original.sectors], ['north', 'west'])
        self.assertEqual([p.point_id for p in original.sectors[0].points], ['N1', 'N2'])
        self.assertEqual(load_selection(self.db), selected)
        self.assertEqual(self.displayed(), ('day', 'north'))
        self.assertEqual(get_shift(self.db, 'relief').sectors[0].sector_id, 'east')

    def test_roster_and_order_rejections_preserve_state(self):
        self.assert_domain_error('duplicate_point', register, self.db, 'bad',
                                 [('east', [('E1', 'Pa'), ('E1', 'kPa')])])
        self.assert_domain_error('unknown_unit', register, self.db, 'bad',
                                 [('east', [('E1', 'Pa')]), ('west', [('W1', 'bar')])])
        self.assert_domain_error('unknown_shift', get_shift, self.db, 'bad')
        self.assert_domain_error('unknown_sector', start, self.db, 'A', 'day', 'east')
        self.assert_domain_error('unknown_order', get_order, self.db, 'A')
        self.assert_domain_error('unknown_sector', select, self.db, 'day', 'east')
        self.assertEqual(self.displayed(), ('desk', 'east'))
        order, attempt = start(self.db, 'A', 'day', 'north')
        self.assertEqual(start(self.db, 'A', 'day', 'north'), (order, attempt))
        self.assert_domain_error('order_conflict', start, self.db, 'A', 'day', 'west')
        self.assert_domain_error('roster_conflict', register, self.db, 'day', [('west', [('W1', 'Pa')])])
        self.assertEqual(get_order(self.db, 'A').roster, order.roster)
        self.assertEqual(self.displayed(), ('day', 'north'))
