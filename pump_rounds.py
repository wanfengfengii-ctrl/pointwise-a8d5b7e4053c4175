import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from collection.artifacts import read_download
from collection.downloads import receive
from collection.eligibility import Eligibility
from collection.orders import resume_order, start
from handover.archive import Archive
from handover.retrieve import retrieve
from handover.sector_lists import publish
from handover.shift_book import ShiftBook, close_shift
from roster.bootstrap import initialize
from storage import open_database
from terminal.generation import GenerationLedger, generate
from terminal.operator import select
from terminal.overlays import OverlayState, finish
from terminal.recording import RecordedEvent, RecordedTerminal


def replay(db: sqlite3.Connection, source: RecordedTerminal) -> dict:
    attempts = {}
    generated = {}
    replies = {}
    archive = Archive(db)
    ledger = GenerationLedger(db)

    def take_order(order_id, shift_id, sector_id):
        _, attempts[order_id] = start(db, order_id, shift_id, sector_id)

    def retry(order_id):
        _, attempts[order_id] = resume_order(db, order_id)

    def generate_file(order_id, generation_id, file_id):
        generated[generation_id] = generate(db, source, attempts[order_id].attempt_id, generation_id, file_id)

    def receive_file(generation_id):
        evidence = generated[generation_id]
        original = ledger.read_payload(evidence.file_id)
        replies[generation_id] = receive(db, read_download(evidence.attempt_id, generation_id, evidence.file_id, original))

    actions = {
        'start': take_order,
        'resume': retry,
        'select': lambda shift_id, sector_id: select(db, shift_id, sector_id),
        'generate': generate_file,
        'receive': receive_file,
        'publish': lambda order_id: publish(archive, order_id),
        'finish': lambda order_id: finish(db, order_id),
    }
    for event in source.iter_events():
        actions[event.action](*event.arguments)
    return replies


def demo() -> None:
    sample = Path(__file__).with_name('samples') / 'recording.json'
    document = json.loads(sample.read_text(encoding='utf-8'))
    source = RecordedTerminal(
        {(shift, sector): text.encode('utf-8') for shift, sector, text in document['sources']},
        (RecordedEvent(sequence, action, tuple(arguments)) for sequence, action, arguments in document['events']),
    )
    with TemporaryDirectory(prefix='pump-rounds-') as directory:
        path = Path(directory) / 'inspection.sqlite'
        with closing(open_database(path)) as db:
            initialize(db, document['rosters'], tuple(document['initial']))
            replies = replay(db, source)
            assert replies['g-a-west'] is Eligibility.WRONG_SECTOR, 'Expected A first download to be wrong-sector'
            assert OverlayState(db).effective_sector() == ('day', 'north'), 'Expected operator north after finish'
            book = close_shift(Archive(db), 'day', ['B', 'A'])
            assert isinstance(book, ShiftBook), book
        source.close()
        with closing(open_database(path)) as db:
            received = retrieve(Archive(db), 'day', kind='shift')

        actual = {
            'sectors': [sector.sector_id for sector in book.sectors],
            'valid': book.summary.valid_count,
            'missing': book.summary.missing_count,
            'min_pa': book.summary.min_pa,
            'max_pa': book.summary.max_pa,
        }
        expected = {'sectors': ['north', 'west'], 'valid': 2, 'missing': 1, 'min_pa': 7, 'max_pa': 11}
        downstream_actual = {
            'files': [sector.origin.file_id for sector in received.output.sectors],
            'rows': [[(row.point_id, row.source_line, row.reading_pa) for row in sector.rows]
                     for sector in received.output.sectors],
            'receipt': received.receipt.receipt_id,
        }
        downstream_expected = {
            'files': ['file-a-north', 'file-b-west'],
            'rows': [[('N1', 2, 7), ('N2', 3, None)], [('W1', 2, 11)]],
            'receipt': 'shift:day',
        }
        assert actual == expected, actual
        assert downstream_actual == downstream_expected, downstream_actual
        assert received.output == book
        scenario = {
            'case_id': 'v6',
            'input': {'shift': 'day', 'sector_orders': ['B', 'A'], 'sources': document['sources']},
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': ['terminal/generation.py', 'collection/downloads.py', 'measurements/normalize.py',
                           'handover/shift_book.py', 'handover/retrieve.py'],
            'oracle': 'Read the sample physical CSV lines directly. 0.007 kPa equals 7 Pa, NA is missing, '
                      'and 11 Pa is the second valid reading. Roster order is north then west.',
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description='Recorded pump inspection and shift handover')
    parser.add_argument('command', choices=['demo'])
    parser.parse_args()
    demo()


if __name__ == '__main__':
    main()
