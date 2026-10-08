"""Load motions per round and track from a workbook (any sheet).

Needs a header row with a Round column (1 / "Round 1"), a Track column
(A/B/C, Primary/Junior/Senior, or "A (Grade 3-5)") and a Motion column; an
optional Info/Info slide column fills the motion's info slide. Alternatively a
sheet per track/round works as long as each row still says its round and track.
Re-running updates, never duplicates.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from motions.models import Motion, RoundMotion
from tournaments.models import Tournament

from nsdcroom.models import MotionTrack

TRACKS = {'a': 'A', 'primary': 'A', 'b': 'B', 'junior': 'B', 'c': 'C', 'senior': 'C'}


def tidy(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


def parse_track(v):
    v = tidy(v).lower()
    for key, letter in TRACKS.items():
        if v == key or v.startswith(key + ' ') or v.startswith(key + '(') or v.startswith(key + ' ('):
            return letter
    m = re.match(r'(?:track\s*)?([abc])\b', v)
    return m.group(1).upper() if m else ''


def parse_round(v):
    m = re.search(r'\d+', tidy(v))
    return int(m.group()) if m else None


class Command(BaseCommand):
    help = "Import NSDC motions (round x track)"

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--tournament', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        import openpyxl
        t = Tournament.objects.get(slug=opts['tournament'])
        rounds = {r.seq: r for r in t.round_set.all()}
        wb = openpyxl.load_workbook(opts['workbook'], read_only=True, data_only=True)
        found = []
        for ws in wb.worksheets:
            rows = list(ws.iter_rows(values_only=True))
            hi = next((i for i, r in enumerate(rows[:10]) if r and any('motion' == tidy(c).lower() or tidy(c).lower().startswith('motion') for c in r)), None)
            if hi is None:
                continue
            head = [tidy(c).lower() for c in rows[hi]]
            def col(*names):
                return next((i for i, h in enumerate(head) if any(h == n or h.startswith(n) for n in names)), None)
            ri, ti, mi, ii = col('round'), col('track', 'grade track', 'category'), col('motion'), col('info')
            if mi is None or ri is None or ti is None:
                raise CommandError(f"Sheet {ws.title!r}: need Round, Track and Motion columns, got {rows[hi]}")
            for r in rows[hi + 1:]:
                if not r or not tidy(r[mi]):
                    continue
                rnd, trk = parse_round(r[ri]), parse_track(r[ti])
                if rnd not in rounds or not trk:
                    raise CommandError(f"Sheet {ws.title!r}: can't read round/track in {r}")
                found.append((rnd, trk, tidy(r[mi]), tidy(r[ii]) if ii is not None else ''))
        if not found:
            raise CommandError("No motions found")
        counts = {}
        for rnd, trk, _, _ in found:
            counts[(rnd, trk)] = counts.get((rnd, trk), 0) + 1
        for k in sorted(counts):
            self.stdout.write(f"  Round {k[0]} · Track {k[1]}: {counts[k]} motions")
        if opts['dry_run']:
            return
        with transaction.atomic():
            seq = {}
            for rnd, trk, text, info in found:
                seq[(rnd, trk)] = seq.get((rnd, trk), 0) + 1
                ref = f"{trk}{rnd}.{seq[(rnd, trk)]:02d}"
                motion = Motion.objects.filter(tournament=t, reference=ref).first() or Motion(tournament=t, reference=ref)
                motion.text, motion.info_slide = text, info
                motion.save()
                MotionTrack.objects.update_or_create(motion=motion, defaults={'track': trk})
                # RoundMotion.seq is unique per round, so each track gets its own range (A 1001+, B 2001+, C 3001+)
                order = 1000 * ('ABC'.index(trk) + 1) + seq[(rnd, trk)]
                RoundMotion.objects.filter(round=rounds[rnd], seq=order).exclude(motion=motion).delete()
                RoundMotion.objects.update_or_create(motion=motion, round=rounds[rnd], defaults={'seq': order})
        self.stdout.write(self.style.SUCCESS(f"{len(found)} motions loaded"))
