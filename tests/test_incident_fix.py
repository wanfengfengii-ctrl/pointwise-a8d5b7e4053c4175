"""Regression tests for the shared export terminal incident.

Covers the two repaired mechanisms:
* the operator selection stays authoritative and temporary overlays are judged by
  the operator revision they were opened at (manual re-selection invalidates older
  overlays, even when the displayed value is unchanged);
* a generated file is attributed to the sector actually in effect at generation
  time, so wrong-sector files never reach a sector list or a first receipt.
"""
from collection.artifacts import read_download
from collection.attempts import get_attempt
from collection.downloads import get_accepted, receive
from collection.eligibility import Eligibility
from collection.orders import resume_order, start
from handover.archive import Archive
from handover.retrieve import retrieve
from handover.sector_lists import publish
from handover.shift_book import close_shift
from terminal.generation import GenerationLedger, generate
from terminal.operator import select
from terminal.overlays import finish
from terminal.recording import RecordedTerminal
from tests.support import InspectionCase


class OverlayOwnershipTests(InspectionCase):
    def test_manual_reselect_invalidates_pending_overlay_even_at_same_value(self):
        _, a = start(self.db, 'A', 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        self.assertEqual(self.displayed(), ('day', 'west'))
        # Manual choice of the value already displayed must still open a new
        # revision and strip restoration rights from both earlier overlays.
        chosen = select(self.db, 'day', 'west')
        self.assertEqual(self.displayed(), ('day', 'west'))
        self.assertEqual(finish(self.db, 'B'), ('day', 'west'), 'PUMP_SELECTION_OWNERSHIP')
        # A's overlay predates the manual revision: it must never restore anything.
        self.assertEqual(finish(self.db, 'A'), ('day', 'west'), 'PUMP_SELECTION_OWNERSHIP')
        self.assertEqual(self.displayed(), ('day', 'west'))
        self.assertEqual(select(self.db, 'desk', 'east').revision, chosen.revision + 1)

    def test_finish_unknown_order_keeps_filter_and_finish_is_isolated(self):
        _, a = start(self.db, 'A', 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        self.assertEqual(finish(self.db, 'unknown'), ('day', 'west'))
        # Taking B down leaves A's overlay as the newest still-valid claim.
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'), 'PUMP_SELECTION_OWNERSHIP')
        # Re-finishing an order changes nothing.
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'))
        self.assertEqual(finish(self.db, 'A'), ('desk', 'east'))

    def test_effective_selection_survives_close_and_reopen(self):
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'))
        self.reopen()
        self.assertEqual(self.displayed(), ('day', 'north'))
        self.reopen()
        self.assertEqual(finish(self.db, 'A'), ('day', 'north'), 'PUMP_SELECTION_OWNERSHIP')
        self.reopen()
        self.assertEqual(self.displayed(), ('day', 'north'))

    def test_retry_overlay_coexists_with_other_order_overlay(self):
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        a_wrong = self.generated(a, 'A-1')
        self.assertEqual((a_wrong.shift_id, a_wrong.sector_id), ('day', 'west'))
        self.assertIs(receive(self.db, self.artifact(a_wrong)), Eligibility.WRONG_SECTOR)
        # B stays live while A's wrong-sector order is renewed; resuming A must
        # not disturb B's overlay or the manual selection underneath.
        _, retry = resume_order(self.db, 'A')
        self.assertEqual(self.displayed(), ('day', 'north'))
        self.assertEqual(finish(self.db, 'B'), ('day', 'north'))
        correct = self.generated(retry, 'A-2')
        self.assertEqual((correct.shift_id, correct.sector_id), ('day', 'north'))
        receive(self.db, self.artifact(correct))
        self.assertEqual(finish(self.db, 'A'), ('day', 'north'), 'PUMP_SELECTION_OWNERSHIP')


class WrongSectorOriginTests(InspectionCase):
    shared_points = True

    def test_wrong_sector_origin_blocks_list_and_receipt_but_order_continues(self):
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        a_wrong = self.generated(a, 'A-1')
        b_export = self.generated(b, 'B-1')
        finish(self.db, 'B')

        proof = GenerationLedger(self.db).get_export(a_wrong.file_id)
        self.assertEqual((proof.shift_id, proof.sector_id), ('day', 'west'), 'PUMP_HANDOFF_WRONG_ORIGIN')
        self.assertIs(receive(self.db, self.artifact(a_wrong)), Eligibility.WRONG_SECTOR,
                      'PUMP_HANDOFF_WRONG_RECEIPT')
        self.assertEqual(get_attempt(self.db, a.attempt_id).status, 'wrong_sector')
        self.assertIsNone(get_accepted(self.db, 'A'))
        self.assert_unpublished('A')
        # The old wrong-sector artifact keeps being judged as wrong-sector later.
        self.assertIs(receive(self.db, self.artifact(a_wrong)), Eligibility.WRONG_SECTOR)
        self.assertEqual(get_attempt(self.db, a.attempt_id).status, 'wrong_sector')

        _, retry = resume_order(self.db, 'A')
        correct = self.generated(retry, 'A-2')
        self.assertEqual((correct.shift_id, correct.sector_id), ('day', 'north'))
        accepted = receive(self.db, self.artifact(correct))
        self.assertEqual(accepted.origin, correct)
        north_list = publish(self.archive, 'A')
        self.assertEqual(north_list.origin.file_id, 'f-A-2')
        self.assertEqual(north_list.receipt.receipt_id, 'sector:A')

        receive(self.db, self.artifact(b_export))
        west_list = publish(self.archive, 'B')
        self.assertEqual(west_list.origin, b_export)
        book = close_shift(self.archive, 'day', ['A', 'B'])
        self.assertEqual([sector.order_id for sector in book.sectors], ['A', 'B'])
        self.assertEqual(book.summary.min_pa, 7)
        self.assertEqual(book.summary.max_pa, 11)

    def test_identical_bytes_still_distinguish_origins(self):
        # Two sectors carrying byte-identical recordings: origin is decided by the
        # recorded shift/sector, never by a digest comparison.
        originals = dict(self.originals)
        originals['day', 'west'] = originals['day', 'north']
        source = RecordedTerminal(originals)
        self.addCleanup(source.close)
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'day', 'north')
        _, b = start(self.db, 'B', 'day', 'west')
        a_wrong = generate(self.db, source, a.attempt_id, 'g-A-1', 'f-A-1')
        b_export = generate(self.db, source, b.attempt_id, 'g-B-1', 'f-B-1')
        north_bytes = GenerationLedger(self.db).read_payload('f-A-1')
        west_bytes = GenerationLedger(self.db).read_payload('f-B-1')
        self.assertEqual(north_bytes, west_bytes)
        self.assertEqual((a_wrong.shift_id, a_wrong.sector_id), ('day', 'west'))
        self.assertIs(receive(self.db, self.artifact(a_wrong)), Eligibility.WRONG_SECTOR,
                      'PUMP_HANDOFF_WRONG_RECEIPT')
        self.assert_unpublished('A')
        # B's own west file is legitimate despite identical bytes.
        self.assertIsNot(receive(self.db, self.artifact(b_export)), Eligibility.WRONG_SECTOR)

    def test_wrong_shift_is_wrong_sector_and_bad_rows_never_mark_attempt(self):
        _, a = start(self.db, 'A', 'day', 'north')
        select(self.db, 'desk', 'east')
        wrong = self.generated(a, 'A-1')
        self.assertEqual((wrong.shift_id, wrong.sector_id), ('desk', 'east'))
        self.assertIs(receive(self.db, self.artifact(wrong)), Eligibility.WRONG_SECTOR)
        _, retry = resume_order(self.db, 'A')
        select(self.db, 'day', 'north')
        correct = self.generated(retry, 'A-2')
        receive(self.db, self.artifact(correct))
        published = publish(self.archive, 'A')
        self.assertEqual(published.origin.file_id, 'f-A-2')
        # A digest-valid, in-sector file whose rows fail validation must not be
        # mistaken for wrong-sector: the attempt stays waiting and can be retried
        # with a corrected file under the same attempt.
        _, c = start(self.db, 'C', 'day', 'north')
        select(self.db, 'day', 'north')
        broken = read_download(c.attempt_id, 'g-C-1', 'f-C-1', b'point,value\nW1,11\n')
        with self.assertRaises(Exception):
            receive(self.db, broken)
        self.assertEqual(get_attempt(self.db, c.attempt_id).status, 'waiting')
        self.assertIsNone(get_accepted(self.db, 'C'))


class OfflineRetrievalTests(InspectionCase):
    def test_frozen_results_and_receipts_remain_claimable_after_source_reopens(self):
        _, a = start(self.db, 'A', 'day', 'north')
        north = self.generated(a, 'A')
        receive(self.db, self.artifact(north))
        north_list = publish(self.archive, 'A')
        self.source.close()
        self.reopen()
        retrieved = retrieve(Archive(self.db), 'A')
        self.assertEqual(retrieved.output, north_list)
        self.assertEqual(retrieved.receipt, north_list.receipt)
        self.assertEqual(retrieved.output.original, north_list.original)
        # Re-publishing an already frozen order returns the same fixed result.
        self.assertEqual(publish(self.archive, 'A'), north_list)
