from collection.artifacts import read_download
from collection.attempts import get_attempt
from collection.downloads import AcceptedDownload, get_accepted, receive
from collection.eligibility import Eligibility
from collection.orders import resume_order, start
from handover.retrieve import retrieve
from handover.sector_lists import publish
from terminal.generation import GenerationLedger, generate
from terminal.operator import load_selection, select
from terminal.overlays import finish
from tests.support import InspectionCase


class HandoffCase(InspectionCase):
    def arrange_delayed_reply(self, *, early=False):
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'day', 'north')
        if early:
            a_export = self.generated(a, 'A-1')
        _, b = start(self.db, 'B', 'day', 'west')
        self.assertEqual(self.displayed(), ('day', 'west'), 'PUMP_SELECTION_OWNERSHIP')
        if not early:
            a_export = self.generated(a, 'A-1')
        b_export = self.generated(b, 'B-1')
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'), 'PUMP_SELECTION_OWNERSHIP')
        return a, a_export, b_export


class SharedTerminalTests(HandoffCase):
    def test_generated_range_beats_reply_time(self):
        a, a_export, b_export = self.arrange_delayed_reply()
        self.assertEqual(a_export.sector_id, 'west', 'PUMP_HANDOFF_WRONG_ORIGIN')
        self.assertIs(receive(self.db, self.artifact(a_export)), Eligibility.WRONG_SECTOR,
                      'PUMP_HANDOFF_WRONG_RECEIPT')
        self.assertEqual(get_attempt(self.db, a.attempt_id).status, 'wrong_sector')
        self.assertIsNone(get_accepted(self.db, 'A'))
        self.assert_unpublished('A')
        self.assert_domain_error('no_accepted_download', publish, self.archive, 'A')
        self.assertIsInstance(receive(self.db, self.artifact(b_export)), AcceptedDownload)
        b = publish(self.archive, 'B')
        self.assertEqual([(r.point_id, r.reading_pa) for r in b.rows], [('W1', 11)])
        self.assertEqual(b.origin, b_export)

        original, retry = resume_order(self.db, 'A')
        self.assertEqual((original.shift_id, original.sector_id), ('day', 'north'))
        self.assertNotEqual(retry.attempt_id, a.attempt_id)
        self.assertIs(receive(self.db, self.artifact(a_export)), Eligibility.WRONG_SECTOR)
        self.assertEqual(get_attempt(self.db, retry.attempt_id).status, 'waiting')
        correct = self.generated(retry, 'A-2')
        receive(self.db, self.artifact(correct))
        published = publish(self.archive, 'A')
        self.assertEqual([(r.point_id, r.reading_pa) for r in published.rows], [('N1', 7), ('N2', None)])
        self.assertEqual(published.origin, correct)
        self.assertEqual(finish(self.db, 'A'), ('day', 'north'), 'PUMP_SELECTION_OWNERSHIP')
        self.assertEqual(retrieve(self.archive, 'A').receipt.receipt_id, 'sector:A')
        self.assert_domain_error('not_retriable', resume_order, self.db, 'A')

    def test_same_value_operator_selection(self):
        for first, second, middle in [('A', 'B', 'west'), ('B', 'A', 'north')]:
            with self.subTest(first=first):
                before = select(self.db, 'desk', 'east')
                _, a = start(self.db, first + '-a', 'day', 'north')
                self.assertEqual(self.displayed(), ('day', 'north'))
                chosen = select(self.db, 'day', 'north')
                self.assertEqual(chosen.revision, before.revision + 1, 'PUMP_SELECTION_OWNERSHIP')
                _, b = start(self.db, first + '-b', 'day', 'west')
                self.assertEqual(self.displayed(), ('day', 'west'))
                west_file = self.generated(b, first + '-west')
                attempts = {'A': a, 'B': b}
                self.assertEqual(finish(self.db, attempts[first].order_id), ('day', middle),
                                 'PUMP_SELECTION_OWNERSHIP')
                if first == 'A':
                    receive(self.db, self.artifact(west_file))
                    west_list = publish(self.archive, b.order_id)
                    self.assertEqual(west_list.rows[0].reading_pa, 11)
                    self.assertEqual(self.displayed(), ('day', 'west'))
                self.assertEqual(finish(self.db, attempts[second].order_id), ('day', 'north'),
                                 'PUMP_SELECTION_OWNERSHIP')
                self.assertEqual(load_selection(self.db), chosen)

    def test_no_operator_older_first(self):
        start(self.db, 'A', 'day', 'north')
        start(self.db, 'B', 'day', 'west')
        self.assertEqual(finish(self.db, 'unknown'), ('day', 'west'))
        self.assertEqual(finish(self.db, 'A'), ('day', 'west'), 'PUMP_SELECTION_OWNERSHIP')
        self.assertEqual(finish(self.db, 'B'), ('desk', 'east'))

    def test_no_operator_newer_first(self):
        start(self.db, 'A', 'day', 'north')
        start(self.db, 'B', 'day', 'west')
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'))
        self.assertEqual(finish(self.db, 'A'), ('desk', 'east'))

    def test_file_binding(self):
        _, a = start(self.db, 'A', 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'north')
        first = self.generated(a, 'A-1')
        second = self.generated(b, 'B-1')
        genuine = self.artifact(first)
        self.assertEqual(genuine.original, self.artifact(second).original)
        swapped = read_download(a.attempt_id, first.generation_id, second.file_id, genuine.original)
        self.assert_domain_error('file_binding', receive, self.db, swapped)
        bad_generation = read_download(a.attempt_id, second.generation_id, first.file_id, genuine.original)
        self.assert_domain_error('file_binding', receive, self.db, bad_generation)
        changed = read_download(a.attempt_id, first.generation_id, first.file_id,
                                b'point,value\nN1,0.011\nN2,NA\n')
        self.assert_domain_error('file_digest', receive, self.db, changed)
        self.assertIsNone(get_accepted(self.db, 'A'))
        self.assert_unpublished('A')
        accepted = receive(self.db, genuine)
        self.assertEqual(receive(self.db, genuine), accepted)
        self.assertEqual(publish(self.archive, 'A').origin, first)

    def test_generation_retry_and_conflict_after_filter_changes(self):
        _, a = start(self.db, 'A', 'day', 'north')
        self.assert_domain_error('unknown_attempt', generate, self.db, self.source, 999, 'unknown-g', 'unknown-f')
        self.assertIsNone(GenerationLedger(self.db).get_export('unknown-f'))
        previous = self.generated(a, 'A-1')
        select(self.db, 'day', 'west')
        self.reopen()
        self.source.close()
        self.assertEqual(self.generated(a, 'A-1'), previous)
        self.assert_domain_error('generation_conflict', generate, self.db, self.source,
                                 a.attempt_id, 'other-g', 'other-f')
        self.assertIsNone(GenerationLedger(self.db).get_export('other-f'))
        self.assertEqual(publish_after_receive(self, previous).rows[0].reading_pa, 7)


def publish_after_receive(case, export):
    receive(case.db, case.artifact(export))
    return publish(case.archive, export.order_id)


class SharedPointTests(HandoffCase):
    shared_points = True

    def test_late_west_file_is_rejected(self):
        _, wrong, west = self.arrange_delayed_reply()
        proof = GenerationLedger(self.db).get_export(wrong.file_id)
        self.assertIsNotNone(proof, 'PUMP_HANDOFF_WRONG_ORIGIN')
        self.assertEqual((proof.shift_id, proof.sector_id), ('day', 'west'), 'PUMP_HANDOFF_WRONG_ORIGIN')
        self.assertEqual(self.artifact(wrong).original, b'point,value\nN1,11\n')
        self.assertIs(receive(self.db, self.artifact(wrong)), Eligibility.WRONG_SECTOR,
                      'PUMP_HANDOFF_WRONG_RECEIPT')
        self.assert_unpublished('A')
        self.assertIsNone(get_accepted(self.db, 'A'), 'PUMP_HANDOFF_WRONG_RECEIPT')
        b = publish_after_receive(self, west)
        _, renewal = resume_order(self.db, 'A')
        correct = self.generated(renewal, 'A-2')
        a = publish_after_receive(self, correct)
        self.assertEqual((a.rows[0].point_id, a.rows[0].reading_pa, a.origin.file_id), ('N1', 7, 'f-A-2'))
        self.assertEqual((b.rows[0].point_id, b.rows[0].reading_pa, b.origin.file_id), ('N1', 11, 'f-B-1'))
        self.assertEqual(finish(self.db, 'A'), ('day', 'north'))

    def test_early_north_file_is_accepted(self):
        _, correct, west = self.arrange_delayed_reply(early=True)
        self.assertEqual(correct.sector_id, 'north', 'PUMP_HANDOFF_WRONG_ORIGIN')
        self.assertEqual(self.artifact(correct).original, b'point,value\nN1,7\n')
        a = publish_after_receive(self, correct)
        b = publish_after_receive(self, west)
        self.assertEqual((a.rows[0].reading_pa, a.origin.file_id), (7, 'f-A-1'))
        self.assertEqual((b.rows[0].reading_pa, b.origin.file_id), (11, 'f-B-1'))
        self.assertEqual(finish(self.db, 'A'), ('day', 'north'))
