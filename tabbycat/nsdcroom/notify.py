"""Tell both speakers of a pair their side, motion and prep deadline.

Preferred route: one POST per released pair to an n8n webhook
(NSDC_N8N_WEBHOOK_URL + shared secret NSDC_N8N_SECRET). The n8n workflow sends
WhatsApp through AiSensy and email through its Gmail connection, then answers
with a status per student and channel.

Fallback when no webhook is configured: send directly, each channel skipped
until its variables exist:

    AISENSY_API_KEY, NSDC_AISENSY_CAMPAIGN      WhatsApp
    NSDC_SMTP_USER, NSDC_SMTP_PASSWORD          email (NSDC_SMTP_FROM optional)
    NSDC_PUBLIC_URL                             link in the message (optional)

Every attempt is stored as a Notification so the judge sees who was reached.
"""
import json
import logging
import os
import re
import urllib.request
from zoneinfo import ZoneInfo

from django.core.mail import EmailMessage, get_connection

from . import logic
from .models import Notification

logger = logging.getLogger(__name__)
IST = ZoneInfo('Asia/Kolkata')
AISENSY_URL = 'https://backend.aisensy.com/campaign/t1/api/v2'


def ist_time(dt):
    return dt.astimezone(IST).strftime('%-I:%M %p') if dt else ''


def whatsapp_number(raw):
    digits = re.sub(r'\D', '', raw or '')
    if len(digits) == 10:
        digits = '91' + digits
    if len(digits) == 12 and digits.startswith('91'):
        return digits
    return ''


def judge_contact(room):
    from participants.models import Adjudicator
    judge = Adjudicator.objects.filter(institution=room).exclude(name='').order_by('id').first()
    if not judge:
        return ''
    return f"{judge.name} {judge.phone}".strip()


def build_message(pairing, member, others, public_url):
    round, room = pairing.round, pairing.room
    opponent = ' & '.join(logic.team_name(o.team) for o in others) if others else 'No opponent (solo speech, scored as usual)'
    return {
        'name': logic.team_name(member.team),
        'round': round.name,
        'pair': f"Pair {pairing.seq} · Batch {room.code}",
        'side': member.side_label.upper(),
        'opponent': opponent,
        'motion': pairing.motion.text if pairing.motion else '',
        'prep_end': ist_time(pairing.prep_ends_at),
        'judge': judge_contact(room) or 'your batch judge',
        'link': public_url,
    }


def email_body(m, poc):
    lines = [
        f"Hi {m['name']},",
        "",
        f"Your NSDC Online Qualifiers {m['round']} debate is ready.",
        "",
        f"{m['pair']}",
        f"Your side: {m['side']}",
        f"Opponent: {m['opponent']}",
        f"Motion: {m['motion']}",
        "",
        f"Prep time ends at {m['prep_end']} IST. Please be ready in your breakout room.",
        "",
        f"Judge: {m['judge']}",
    ]
    if poc:
        lines.append(f"Point of contact: {poc}")
    if m['link']:
        lines += ["", f"Live draw and results: {m['link']}"]
    lines += ["", "All the best!", "Team NSDC · Taivas Debate Club × IIT Bombay Debate Society"]
    return "\n".join(lines)


def send_whatsapp(number, m):
    key, campaign = os.environ.get('AISENSY_API_KEY'), os.environ.get('NSDC_AISENSY_CAMPAIGN')
    if not (key and campaign):
        return 'skipped', 'WhatsApp not configured'
    if not number:
        return 'skipped', 'no valid mobile number'
    payload = {
        'apiKey': key, 'campaignName': campaign, 'destination': number, 'userName': m['name'],
        'templateParams': [m['name'], m['round'], m['pair'], m['side'], m['opponent'], m['motion'],
                           m['prep_end'], m['judge'], m['link'] or '-'],
        'source': 'nsdc-tab',
    }
    req = urllib.request.Request(AISENSY_URL, data=json.dumps(payload).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 'sent', resp.read(300).decode('utf-8', 'replace')
    except Exception as e:  # noqa: BLE001 - any failure is logged, never breaks the judge's click
        body = getattr(e, 'read', lambda: b'')()
        return 'failed', f"{e} {body[:300]!r}"


def send_email(address, m, poc, connection):
    if connection is None:
        return 'skipped', 'email not configured'
    if not address or '@' not in address:
        return 'skipped', 'no email address'
    sender = os.environ.get('NSDC_SMTP_FROM') or f"NSDC Qualifiers <{os.environ['NSDC_SMTP_USER']}>"
    msg = EmailMessage(subject=f"NSDC {m['round']}: your side and motion ({m['pair']})",
                       body=email_body(m, poc), from_email=sender, to=[address], connection=connection)
    try:
        msg.send()
        return 'sent', ''
    except Exception as e:  # noqa: BLE001
        return 'failed', str(e)[:300]


def smtp_connection():
    user, password = os.environ.get('NSDC_SMTP_USER'), os.environ.get('NSDC_SMTP_PASSWORD')
    if not (user and password):
        return None
    return get_connection('django.core.mail.backends.smtp.EmailBackend', host='smtp.gmail.com', port=587,
                          username=user, password=password, use_tls=True, timeout=10)


def notify_via_n8n(pairing, members, poc, public_url, webhook):
    """One webhook call for the whole pair; n8n replies {"results": [{team_id, channel, status, detail}]}."""
    students = []
    for member in members:
        others = [o for o in members if o.team_id != member.team_id]
        speaker = member.team.speaker_set.first()
        email = (speaker.email or '').strip() if speaker else ''
        students.append({
            'team_id': member.team_id,
            'phone': whatsapp_number(speaker.phone if speaker else ''),
            'email': email if '@' in email else '',
            **build_message(pairing, member, others, public_url),
        })
    payload = {
        'secret': os.environ.get('NSDC_N8N_SECRET', ''),
        'tournament': pairing.round.tournament.slug, 'round': pairing.round.name,
        'batch_code': pairing.room.code, 'batch_name': pairing.room.name, 'pair': pairing.seq,
        'motion': pairing.motion.text if pairing.motion else '', 'prep_end': ist_time(pairing.prep_ends_at),
        'poc': poc, 'link': public_url, 'students': students,
    }
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode(), method='POST',
                                 headers={'Content-Type': 'application/json'})
    results = []
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            body = json.loads(resp.read().decode('utf-8', 'replace') or '{}')
        results = body.get('results', []) if isinstance(body, dict) else []
    except Exception as e:  # noqa: BLE001
        error = f"n8n unreachable: {e}"[:300]
        results = [{'team_id': s['team_id'], 'channel': ch, 'status': 'failed', 'detail': error}
                   for s in students for ch in ('whatsapp', 'email')]
    by_student = {s['team_id']: s for s in students}
    rows = []
    for r in results:
        team_id = r.get('team_id')
        if team_id not in by_student or r.get('channel') not in ('whatsapp', 'email'):
            continue
        s = by_student[team_id]
        rows.append(Notification.objects.create(
            pairing=pairing, team_id=team_id, channel=r['channel'],
            destination=s['phone'] if r['channel'] == 'whatsapp' else s['email'],
            status=r.get('status') if r.get('status') in ('sent', 'failed', 'skipped') else 'failed',
            detail=str(r.get('detail', ''))[:500]))
    return rows


def notify_pairing(pairing, public_url=''):
    """Message every speaker in the pair. Returns the Notification rows created."""
    members = pairing.members
    profile = getattr(pairing.room, 'nsdc_batch', None)
    poc = f"{profile.poc_name} {profile.poc_phone}".strip() if profile else ''
    public_url = os.environ.get('NSDC_PUBLIC_URL') or public_url
    webhook = os.environ.get('NSDC_N8N_WEBHOOK_URL')
    if webhook:
        return notify_via_n8n(pairing, members, poc, public_url, webhook)
    connection = smtp_connection()
    rows = []
    for member in members:
        others = [o for o in members if o.team_id != member.team_id]
        m = build_message(pairing, member, others, public_url)
        speaker = member.team.speaker_set.first()
        number = whatsapp_number(speaker.phone if speaker else '')
        email = (speaker.email or '') if speaker else ''
        for channel, (status, detail), dest in (
            ('whatsapp', send_whatsapp(number, m), number),
            ('email', send_email(email, m, poc, connection), email),
        ):
            rows.append(Notification.objects.create(pairing=pairing, team=member.team, channel=channel,
                                                    destination=dest, status=status, detail=detail))
    return rows
