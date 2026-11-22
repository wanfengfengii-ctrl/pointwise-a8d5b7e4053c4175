import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from collection.artifacts import read_download
from collection.downloads import AcceptedDownload, receive
from collection.orders import start
from errors import InspectionError
from handover.archive import Archive
from handover.retrieve import retrieve
from handover.sector_lists import publish
from roster.bootstrap import initialize
from storage import open_database
from terminal.generation import GenerationLedger, generate
from terminal.overlays import OverlayState, finish
from terminal.recording import RecordedTerminal


NORTH = b'point,value\nN1,0.007\nN2,NA\n'
WEST = b'point,value\nW1,11\n'
EAST = b'point,value\nE1,3\n'


def fixture(shared_points=False):
    if shared_points:
        north_points = west_points = [('N1', 'Pa')]
        north_raw = b'point,value\nN1,7\n'
        west_raw = b'point,value\nN1,11\n'
    else:
        north_points = [('N1', 'kPa'), ('N2', 'Pa')]
        west_points = [('W1', 'Pa')]
        north_raw, west_raw = NORTH, WEST
    rosters = [('desk', [('east', [('E1', 'Pa')])]),
               ('day', [('north', north_points), ('west', west_points)])]
    raw = {('desk', 'east'): EAST, ('day', 'north'): north_raw, ('day', 'west'): west_raw}
    return rosters, raw


class InspectionCase(unittest.TestCase):
    shared_points = False

    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='pump-test-'))
        self.path = Path(directory) / 'shift.sqlite'
        self.connect()
        self.rosters, self.originals = fixture(self.shared_points)
        self.source = RecordedTerminal(self.originals)
        self.addCleanup(self.source.close)
        initialize(self.db, self.rosters, ('desk', 'east'))

    def connect(self):
        self.db = open_database(self.path)
        self.addCleanup(self.db.close)
        self.archive = Archive(self.db)

    def reopen(self):
        self.db.close()
        self.connect()

    def displayed(self):
        return OverlayState(self.db).effective_sector()

    def generated(self, attempt, tag, source=None):
        if source is None:
            source = self.source
        return generate(self.db, source, attempt.attempt_id, f'g-{tag}', f'f-{tag}')

    def artifact(self, evidence):
        original = GenerationLedger(self.db).read_payload(evidence.file_id)
        return read_download(evidence.attempt_id, evidence.generation_id, evidence.file_id, original)

    def capture(self, order_id, sector, *, sign=True):
        _, attempt = start(self.db, order_id, 'day', sector)
        evidence = self.generated(attempt, order_id)
        accepted = receive(self.db, self.artifact(evidence))
        self.assertIsInstance(accepted, AcceptedDownload)
        finish(self.db, order_id)
        return publish(self.archive, order_id) if sign else accepted

    def assert_domain_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(InspectionError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def assert_unpublished(self, output_id, *, kind='sector'):
        self.assertIsNone(self.archive.read_output(kind, output_id), 'Unpublished output left a formal record')
        self.assertIsNone(self.archive.read_receipt(kind, output_id), 'Unpublished output left a first receipt')
        self.assert_domain_error('no_output', retrieve, self.archive, output_id, kind=kind)
