import json
import sys
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from collection.artifacts import read_download
from collection.downloads import receive
from collection.eligibility import Eligibility
from collection.orders import resume_order, start
from errors import InspectionError
from handover.archive import Archive
from handover.retrieve import retrieve
from handover.sector_lists import publish
from roster.bootstrap import initialize
from storage import open_database
from terminal.generation import GenerationLedger, generate
from terminal.operator import select
from terminal.overlays import finish
from terminal.recording import RecordedTerminal
from tests.support import fixture


def reply(db, export):
    raw = GenerationLedger(db).read_payload(export.file_id)
    return receive(db, read_download(export.attempt_id, export.generation_id, export.file_id, raw))


def try_sign(archive, order_id):
    try:
        publish(archive, order_id)
    except InspectionError as error:
        if error.code != 'no_accepted_download':
            raise
    receipt = archive.read_receipt('sector', order_id)
    return [archive.read_output('sector', order_id) is not None, receipt.receipt_id if receipt else None]


def offline_row(archive, order_id):
    received = retrieve(archive, order_id)
    result = received.output
    row, = result.rows
    return [row.point_id, row.reading_pa, row.source_line, result.origin.shift_id,
            result.origin.sector_id, result.origin.file_id, received.receipt.receipt_id,
            result.original.decode('utf-8')]


def observe(path, *, early, same_bytes):
    rosters, originals = fixture(shared_points=True)
    if same_bytes:
        originals['day', 'west'] = originals['day', 'north']
    source = RecordedTerminal(originals)
    with closing(open_database(path)) as db:
        initialize(db, rosters, ('desk', 'east'))
        _, a = start(db, 'A', 'day', 'north')
        select(db, 'day', 'north')
        if early:
            first = generate(db, source, a.attempt_id, 'g-A-1', 'f-A-1')
        _, b = start(db, 'B', 'day', 'west')
        if not early:
            first = generate(db, source, a.attempt_id, 'g-A-1', 'f-A-1')
        west = generate(db, source, b.attempt_id, 'g-B-1', 'f-B-1')
        before_reply = finish(db, 'B')
    with closing(open_database(path)) as db:
        archive = Archive(db)
        proof = GenerationLedger(db).get_export(first.file_id)
        outcome = reply(db, first)
        first_signed = try_sign(archive, 'A')
        reply(db, west)
        publish(archive, 'B')
        if outcome is Eligibility.WRONG_SECTOR:
            _, retry = resume_order(db, 'A')
            north = generate(db, source, retry.attempt_id, 'g-A-2', 'f-A-2')
            reply(db, north)
            publish(archive, 'A')
        after_finish = finish(db, 'A')
    source.close()
    with closing(open_database(path)) as db:
        archive = Archive(db)
        return {
            'before_reply': before_reply,
            'first_origin': (proof.shift_id, proof.sector_id) if proof else None,
            'first_outcome': 'wrong_sector' if outcome is Eligibility.WRONG_SECTOR else 'accepted',
            'first_signed': first_signed,
            'after_finish': after_finish,
            'A': offline_row(archive, 'A'),
            'B': offline_row(archive, 'B'),
        }


def expected(early, same_bytes):
    west_value = 7 if same_bytes else 11
    return {
        'before_reply': ('day', 'north'), 'after_finish': ('day', 'north'),
        'first_origin': ('day', 'north' if early else 'west'),
        'first_outcome': 'accepted' if early else 'wrong_sector',
        'first_signed': [True, 'sector:A'] if early else [False, None],
        'A': ['N1', 7, 2, 'day', 'north', 'f-A-1' if early else 'f-A-2', 'sector:A', 'point,value\nN1,7\n'],
        'B': ['N1', west_value, 2, 'day', 'west', 'f-B-1', 'sector:B', f'point,value\nN1,{west_value}\n'],
    }


def main():
    mismatches = []
    with TemporaryDirectory(prefix='pump-incident-') as temporary:
        for label, early, same_bytes in (('late', False, False), ('identical-early', True, True),
                                         ('identical-late', False, True)):
            observed = observe(Path(temporary) / (label + '.sqlite'), early=early, same_bytes=same_bytes)
            wanted = expected(early, same_bytes)
            print(json.dumps({'case': label, 'expected': wanted, 'observed': observed}, sort_keys=True))
            if observed != wanted:
                mismatches.append(label)
    if mismatches:
        print('PUMP_EXPORT_HANDOFF_MISMATCH: ' + ', '.join(mismatches), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
