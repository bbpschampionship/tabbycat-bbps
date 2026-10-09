"""Motion-release emails through Mailchimp (account info@taivas.co.in).

The account has no Transactional add-on, so each student gets a one-person
regular campaign: upsert the member, static segment of that one address,
campaign with the HTML, send. Needs MAILCHIMP_API_KEY (…-us3) and NSDC_MC_LIST.
"""
import base64
import hashlib
import html as H
import json
import os
import urllib.error
import urllib.request

FROM_NAME = 'NSDC · Taivas Debate Club'
REPLY_TO = 'info@taivas.co.in'


def enabled():
    return bool(os.environ.get('MAILCHIMP_API_KEY') and os.environ.get('NSDC_MC_LIST'))


def _mc(method, path, body=None):
    key = os.environ['MAILCHIMP_API_KEY']
    req = urllib.request.Request(f"https://{key.rsplit('-', 1)[-1]}.api.mailchimp.com/3.0{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={'Content-Type': 'application/json',
                                          'Authorization': 'Basic ' + base64.b64encode(f"x:{key}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode('utf-8', 'replace')
        try:
            detail = json.loads(detail).get('detail', detail)
        except ValueError:
            pass
        raise RuntimeError(f"Mailchimp {e.code}: {detail}"[:300]) from None


def email_html(m, poc):
    e = lambda s: H.escape(str(s or ''))  # noqa: E731

    def row(k, v):
        return (f'<tr><td style="padding:6px 0;color:#9E7F26;font:700 11px Arial,sans-serif;letter-spacing:.12em;'
                f'text-transform:uppercase;width:130px;vertical-align:top">{k}</td>'
                f'<td style="padding:6px 0;color:#5A4413;font:600 15px Arial,sans-serif">{v}</td></tr>')
    link = (f'<tr><td style="padding:10px 26px 22px;text-align:center"><a href="{e(m["link"])}" '
            f'style="color:#7A5E18;font:700 13px Arial,sans-serif">See the live draw and results →</a></td></tr>') if m['link'] else ''
    return f"""<!doctype html><html><body style="margin:0;background:#FBF7EA">
<div style="background:#FBF7EA;padding:24px 12px"><table cellpadding="0" cellspacing="0" style="max-width:560px;width:100%;margin:0 auto;background:#fff;border:2px solid #C9A227">
<tr><td style="padding:22px 26px 6px;text-align:center"><div style="font:700 11px Arial,sans-serif;letter-spacing:.2em;color:#9E7F26;text-transform:uppercase">NSDC 2026 · Online Qualifiers</div>
<div style="font:900 24px Arial,sans-serif;color:#C29A26;margin-top:6px">{e(m['round'])}: your debate</div></td></tr>
<tr><td style="padding:10px 26px 4px;font:500 15px Arial,sans-serif;color:#5A4413">Hi {e(m['name'])}, your motion has been released.</td></tr>
<tr><td style="padding:6px 26px"><table cellpadding="0" cellspacing="0" style="width:100%">{row('Batch &amp; pair', e(m['pair']))}{row('Your side', '<b>' + e(m['side']) + '</b>')}{row('Opponent', e(m['opponent']))}</table></td></tr>
<tr><td style="padding:8px 26px"><div style="background:#FBF7EA;border-left:4px solid #C9A227;padding:12px 14px;font:600 18px Georgia,serif;color:#5A4413"><div style="font:700 10px Arial,sans-serif;letter-spacing:.18em;color:#9E7F26;text-transform:uppercase;margin-bottom:4px">Motion</div>{e(m['motion'])}</div></td></tr>
<tr><td style="padding:10px 26px"><div style="background:#C9A227;color:#3d2e0b;text-align:center;padding:12px;font:900 17px Arial,sans-serif">Prep time ends at {e(m['prep_end'])} IST</div>
<div style="font:500 13px Arial,sans-serif;color:#6E541A;text-align:center;margin-top:8px">Please be ready in your breakout room on time.</div></td></tr>
<tr><td style="padding:8px 26px 4px"><table cellpadding="0" cellspacing="0" style="width:100%">{row('Judge', e(m['judge']))}{row('Batch POC', e(poc)) if poc else ''}</table></td></tr>
{link}
<tr><td style="padding:12px 26px;border-top:1px solid #EBD9A3;text-align:center;font:600 11px Arial,sans-serif;color:#9E7F26">National Speech &amp; Debate Championship · Taivas Debate Club × IIT Bombay Debate Society
<div style="font:400 10px Arial,sans-serif;color:#B5A27A;margin-top:8px">*|LIST_ADDRESSLINE_TEXT|* · <a href="*|UNSUB|*" style="color:#B5A27A">Unsubscribe</a></div></td></tr>
</table></div></body></html>"""


def send(address, m, poc, tag):
    """Returns (status, detail)."""
    address = (address or '').strip().lower()
    if '@' not in address:
        return 'skipped', 'no email address'
    if not enabled():
        return 'skipped', 'Mailchimp not configured'
    lst = os.environ['NSDC_MC_LIST']
    try:
        h = hashlib.md5(address.encode()).hexdigest()
        member = _mc('PUT', f"/lists/{lst}/members/{h}", {'email_address': address, 'status_if_new': 'subscribed'})
        if member.get('status') == 'archived':
            member = _mc('PATCH', f"/lists/{lst}/members/{h}", {'status': 'subscribed'})
        if member.get('status') != 'subscribed':
            return 'skipped', f"address is {member.get('status')} in Mailchimp"
        seg = _mc('POST', f"/lists/{lst}/segments", {'name': tag[:100], 'static_segment': [address]})
        subject = f"NSDC {m['round']}: your side and motion ({m['pair']})"
        camp = _mc('POST', '/campaigns', {
            'type': 'regular',
            'recipients': {'list_id': lst, 'segment_opts': {'saved_segment_id': seg['id']}},
            'settings': {'subject_line': subject, 'title': tag[:100], 'from_name': FROM_NAME,
                         'reply_to': REPLY_TO, 'auto_footer': False}})
        _mc('PUT', f"/campaigns/{camp['id']}/content", {'html': email_html(m, poc)})
        _mc('POST', f"/campaigns/{camp['id']}/actions/send")
        return 'sent', f"Mailchimp campaign {camp['id']}"
    except Exception as e:  # noqa: BLE001
        return 'failed', str(e)[:300]
