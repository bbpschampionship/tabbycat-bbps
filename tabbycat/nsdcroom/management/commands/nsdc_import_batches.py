"""Load the NSDC batch-allotment workbook into a tournament.

The workbook's first sheet lists batches (code, track, time slot, batch name,
grades); every other sheet is one batch with a "Batch Code: NN" line and a
student table (No., Student Name, Grade, School Name, ...). Each student
becomes a one-speaker team whose institution is the batch; each batch gets
one judge slot with a blank name and a private URL.

Contact details in the workbook are not imported. Re-running is safe: existing
batches, students and judges are matched and updated, never duplicated.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from participants.models import Adjudicator, Institution, Speaker, Team
from privateurls.utils import populate_url_keys
from tournaments.models import Round, Tournament

from nsdcroom.models import BatchProfile, StudentProfile


def tidy_name(name):
    name = re.sub(r'\s+', ' ', str(name or '')).strip()
    # fix names typed in all caps / all lower case, leave mixed case alone
    return ' '.join(w.capitalize() if (w.isupper() or w.islower()) else w for w in name.split(' '))


def tidy(value):
    return re.sub(r'\s+', ' ', str(value or '')).strip()


class Command(BaseCommand):
    help = "Import NSDC batches and students from the allotment workbook"

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--tournament', required=True, help="Tournament slug (created if missing)")
        parser.add_argument('--name', default="NSDC 2026 Online Qualifiers")
        parser.add_argument('--short-name', default="NSDC Qualifiers")
        parser.add_argument('--rounds', type=int, default=3)
        parser.add_argument('--dry-run', action='store_true')

    def read(self, path):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheets = wb.worksheets
        batches = {}
        for row in list(sheets[0].iter_rows(values_only=True))[1:]:
            if not row[0] or not str(row[0]).strip().isdigit():
                continue
            code = str(row[0]).strip().zfill(2)
            batches[code] = {'track': tidy(row[1]), 'time_slot': tidy(row[2]), 'name': tidy(row[3]),
                             'grades': tidy(row[4]), 'expected': row[5], 'students': []}
        for ws in sheets[1:]:
            rows = list(ws.iter_rows(values_only=True))
            code = None
            for row in rows[:6]:
                m = re.match(r'Batch Code:\s*(\d+)', str(row[0] or ''))
                if m:
                    code = m.group(1).zfill(2)
            if code not in batches:
                raise CommandError(f"Sheet {ws.title!r}: batch code {code!r} not in the summary sheet")
            header = next(i for i, r in enumerate(rows) if r and r[1] == 'Student Name')
            for r in rows[header + 1:]:
                if r[0] is None or not r[1]:
                    continue
                batches[code]['students'].append({'name': tidy_name(r[1]), 'grade': tidy(r[2]), 'school': tidy(r[3])})
        for code, b in batches.items():
            if b['expected'] is not None and len(b['students']) != b['expected']:
                raise CommandError(f"Batch {code}: {len(b['students'])} students but summary says {b['expected']}")
        return batches

    def handle(self, *args, **opts):
        batches = self.read(opts['workbook'])
        total = sum(len(b['students']) for b in batches.values())
        self.stdout.write(f"{len(batches)} batches, {total} students")
        if opts['dry_run']:
            for code, b in sorted(batches.items()):
                self.stdout.write(f"  {code} {b['name']} [{b['track']}] {len(b['students'])}")
            return

        with transaction.atomic():
            t, created = Tournament.objects.get_or_create(slug=opts['tournament'], defaults={
                'name': opts['name'], 'short_name': opts['short_name'], 'seq': 1})
            for i in range(1, opts['rounds'] + 1):
                Round.objects.get_or_create(tournament=t, seq=i, defaults={
                    'name': f"Round {i}", 'abbreviation': f"R{i}",
                    'draw_type': Round.DrawType.RANDOM if i == 1 else Round.DrawType.POWERPAIRED})

            for code, b in sorted(batches.items()):
                inst = Institution.objects.filter(code=code, name=b['name']).first() \
                    or Institution.objects.create(code=code, name=b['name'])
                BatchProfile.objects.update_or_create(institution=inst, defaults={
                    'track': b['track'], 'time_slot': b['time_slot'], 'grades': b['grades']})

                seen = {}
                for s in b['students']:
                    reference = s['name']
                    seen[reference] = seen.get(reference, 0) + 1
                    if seen[reference] > 1:  # same name twice in one batch
                        reference = f"{s['name']} ({seen[reference]})"
                    team, _ = Team.objects.get_or_create(tournament=t, institution=inst, reference=reference,
                                                         defaults={'use_institution_prefix': False})
                    if not team.speaker_set.exists():
                        Speaker.objects.create(team=team, name=s['name'])
                    StudentProfile.objects.update_or_create(team=team, defaults={
                        'school': s['school'], 'grade': s['grade']})

                if not Adjudicator.objects.filter(tournament=t, institution=inst).exists():
                    Adjudicator.objects.create(tournament=t, institution=inst, name="")

            populate_url_keys(Adjudicator.objects.filter(tournament=t, url_key__isnull=True))

        self.stdout.write(self.style.SUCCESS(
            f"{'Created' if created else 'Updated'} tournament /{t.slug}/: "
            f"{Team.objects.filter(tournament=t).count()} students, "
            f"{Adjudicator.objects.filter(tournament=t).count()} judge slots"))
