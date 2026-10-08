"""Set each batch's point of contact (shown to parents) from a workbook.

Needs a header row with a Batch Code column, a POC name column (header containing
"poc" or "point of contact") and optionally a contact/phone column after it.
"""
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from participants.models import Institution
from tournaments.models import Tournament

from nsdcroom.models import BatchProfile


def tidy(v):
    return re.sub(r'\s+', ' ', str(v or '')).strip()


class Command(BaseCommand):
    help = "Import NSDC batch POCs"

    def add_arguments(self, parser):
        parser.add_argument('workbook')
        parser.add_argument('--tournament', required=True)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **opts):
        import openpyxl
        t = Tournament.objects.get(slug=opts['tournament'])
        rooms = {i.code: i for i in Institution.objects.filter(team__tournament=t).distinct()}
        rows = list(openpyxl.load_workbook(opts['workbook'], read_only=True, data_only=True).worksheets[0].iter_rows(values_only=True))
        head = [tidy(c).lower() for c in rows[0]]
        ci = next((i for i, h in enumerate(head) if 'batch code' in h or h == 'code'), None)
        ni = next((i for i, h in enumerate(head) if ('poc' in h or 'point of contact' in h)
                   and not any(w in h for w in ('contact no', 'phone', 'number', 'mobile'))), None)
        pi = next((i for i, h in enumerate(head) if i != ni and ('poc' in h or 'contact' in h)
                   and any(w in h for w in ('contact', 'phone', 'number', 'mobile'))), None)
        if ci is None or ni is None:
            raise CommandError(f"Need Batch Code and POC columns, got {rows[0]}")
        data = {}
        for r in rows[1:]:
            if r and r[ci] and tidy(r[ni]):
                data[str(r[ci]).strip().zfill(2)] = (tidy(r[ni]), tidy(r[pi]) if pi is not None else '')
        missing = sorted(set(data) - set(rooms))
        if missing:
            raise CommandError(f"Unknown batch codes: {missing}")
        for code, (name, phone) in sorted(data.items()):
            self.stdout.write(f"  {code}: {name} {phone}")
        if opts['dry_run']:
            return
        with transaction.atomic():
            for code, (name, phone) in data.items():
                BatchProfile.objects.update_or_create(institution=rooms[code], defaults={'poc_name': name, 'poc_phone': phone})
        self.stdout.write(self.style.SUCCESS(f"{len(data)} batch POCs set"))
