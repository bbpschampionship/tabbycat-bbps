"""Tab director console: everything the tab team needs, plain and functional."""
import csv
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from participants.models import Adjudicator, Institution

from . import logic, notify
from .models import MAX_SCORE, Notification, Pairing, RoundRelease, TournamentRelease
from .views import TournamentView


def release_pairing(request, tournament, pairing, prep_minutes):
    """Start a pair's prep clock and message both speakers. Returns a status line."""
    if pairing.motion_id is None:
        raise ValidationError(f"Pick a motion for Pair {pairing.seq} first.")
    now = timezone.now()
    pairing.motion_released_at = now
    pairing.prep_ends_at = now + timedelta(minutes=prep_minutes)
    pairing.save(update_fields=['motion_released_at', 'prep_ends_at'])
    rows = notify.notify_pairing(pairing, request.build_absolute_uri(reverse(
        'nsdcroom-public-batch', kwargs={'tournament_slug': tournament.slug, 'room_id': pairing.room_id})))
    sent = sum(1 for r in rows if r.status == 'sent')
    failed = sum(1 for r in rows if r.status == 'failed')
    return (f"Pair {pairing.seq}: motion released, prep ends {notify.ist_time(pairing.prep_ends_at)}. "
            f"Messages sent: {sent}" + (f", failed: {failed}" if failed else "") + ".")


class DirectorView(TournamentView):
    section = 'overview'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def release(self):
        return TournamentRelease.objects.get_or_create(tournament=self.tournament)[0]

    def judge_url(self, judge):
        return self.request.build_absolute_uri(reverse('nsdcroom-judge', kwargs={
            'tournament_slug': self.tournament.slug, 'url_key': judge.url_key})) if judge.url_key else ''

    def rooms(self, track=''):
        rooms = list(logic.tournament_rooms(self.tournament))
        return [r for r in rooms if not track or logic.track_letter(r) == track]

    def ctx(self, **kw):
        rounds = self.rounds()
        round = kw.pop('round', None) or self.pick_round(rounds)
        tracks = sorted({logic.track_letter(r) for r in logic.tournament_rooms(self.tournament)} - {''})
        base = {'tournament': self.tournament, 'rounds': rounds, 'round': round, 'section': self.section,
                'track': self.request.GET.get('track', ''), 'max_score': MAX_SCORE,
                'tracks': [{'letter': t, 'name': logic.TRACK_NAMES.get(t, t)} for t in tracks],
                'released': logic.results_released(round) if round else False, 'release': self.release()}
        base.update(kw)
        return base

    def back(self, name='nsdcroom-admin', anchor='', **kw):
        url = reverse(name, kwargs={'tournament_slug': self.tournament.slug, **kw})
        q = '&'.join(f"{k}={self.request.POST.get(k)}" for k in ('round', 'track') if self.request.POST.get(k))
        return redirect(url + (f"?{q}" if q else '') + (f"#{anchor}" if anchor else ''))


# ---------------------------------------------------------------- Overview

class OverviewView(DirectorView):

    def get(self, request, *args, **kwargs):
        c = self.ctx()
        round, rows = c['round'], []
        totals = {'pairs': 0, 'scored': 0, 'released': 0, 'absent': 0}
        for room in self.rooms(c['track']):
            profile = getattr(room, 'nsdc_batch', None)
            judges = list(Adjudicator.objects.filter(tournament=self.tournament, institution=room).order_by('id'))
            pairings = logic.pairings_for(round, room) if round else []
            scored = sum(1 for p in pairings if p.is_scored)
            out = sum(1 for p in pairings if p.is_released)
            absent = sum(1 for p in pairings for m in p.members if m.score == 0)
            for k, v in (('pairs', len(pairings)), ('scored', scored), ('released', out), ('absent', absent)):
                totals[k] += v
            status = ('done' if pairings and scored == len(pairings) else
                      'live' if out or scored else 'waiting')
            rows.append({'room': room, 'label': logic.public_batch_name(room), 'profile': profile,
                         'count': len(logic.room_teams(self.tournament, room)),
                         'judges': [{'j': j, 'url': self.judge_url(j)} for j in judges],
                         'pairs': len(pairings), 'scored': scored, 'out': out, 'absent': absent, 'status': status})
        return render(request, 'nsdcroom/director/overview.html', self.ctx(round=round, rows=rows, totals=totals))


# ---------------------------------------------------------------- Batch

class BatchView(DirectorView):
    section = 'batches'

    def get(self, request, *args, **kwargs):
        room = get_object_or_404(Institution, id=kwargs['room_id'])
        c = self.ctx()
        round = c['round']
        teams = logic.room_teams(self.tournament, room)
        pairings = logic.pairings_for(round, room)
        logic.label_members(pairings, teams)
        latest = {}
        for n in Notification.objects.filter(pairing__in=pairings).order_by('created_at'):
            latest[(n.pairing_id, n.team_id, n.channel)] = n
        placed = {}
        for p in pairings:
            p.prep_end_ist = notify.ist_time(p.prep_ends_at)
            for m in p.members:
                m.wa = latest.get((p.id, m.team_id, 'whatsapp'))
                m.em = latest.get((p.id, m.team_id, 'email'))
                placed[m.team_id] = (p.seq, m.side)
        speakers = sorted(({'team': t, 'name': logic.team_name(t), 'school': logic.team_school(t),
                            'pair': placed.get(t.id, (None, None))[0], 'side': placed.get(t.id, (None, None))[1]}
                           for t in teams), key=lambda s: (s['pair'] or 999, s['side'] or 0, s['name'].lower()))
        judges = list(Adjudicator.objects.filter(tournament=self.tournament, institution=room).order_by('id'))
        rounds = c['rounds']
        return render(request, 'nsdcroom/director/batch.html', self.ctx(
            round=round, room=room, label=logic.public_batch_name(room), profile=getattr(room, 'nsdc_batch', None),
            pairings=pairings, speakers=speakers, motions=logic.round_motions(round, room),
            pair_choices=range(1, len(teams) // 2 + 3),
            judges=[{'j': j, 'url': self.judge_url(j)} for j in judges],
            all_judges=Adjudicator.objects.filter(tournament=self.tournament).order_by('name'),
            standings=logic.ranked(teams, [r for r in rounds if r.seq <= round.seq]),
            all_rooms=logic.tournament_rooms(self.tournament)))

    def post(self, request, *args, **kwargs):
        room = get_object_or_404(Institution, id=kwargs['room_id'])
        round = self.pick_round(self.rounds())
        action = request.POST.get('action')
        anchor = ''
        try:
            if action in ('score', 'clear_score', 'release', 'swap', 'motion'):
                pairing = get_object_or_404(Pairing, id=request.POST.get('pairing'), round=round, room=room)
                anchor = f"p{pairing.seq}"
                if action == 'score':
                    logic.save_scores(pairing, logic.raw_scores(request.POST, pairing))
                    messages.success(request, f"Pair {pairing.seq} scores saved.")
                elif action == 'clear_score':
                    for m in pairing.members:
                        m.score = None
                        m.save(update_fields=['score'])
                    messages.success(request, f"Pair {pairing.seq} scores deleted.")
                elif action == 'swap':
                    members = pairing.members
                    if len(members) != 2:
                        raise ValidationError("Only a pair of two can swap sides.")
                    for m in members:
                        m.side = 3 - m.side
                        m.side += 10  # avoid the unique (pairing, side) clash mid-swap
                        m.save(update_fields=['side'])
                    for m in members:
                        m.side -= 10
                        m.save(update_fields=['side'])
                    logic.mirror_native(round, room)
                    messages.success(request, f"Pair {pairing.seq}: sides swapped.")
                else:
                    raw = request.POST.get('motion', '')
                    allowed = {m.id for m in logic.round_motions(round, room)}
                    motion_id = int(raw) if raw else None
                    if motion_id is not None and motion_id not in allowed:
                        raise ValidationError("Pick a motion from the list.")
                    pairing.motion_id = motion_id
                    pairing.save(update_fields=['motion'])
                    if action == 'release':
                        messages.success(request, release_pairing(request, self.tournament, pairing,
                                                                  self.release().prep_minutes))
                    else:
                        messages.success(request, f"Pair {pairing.seq}: motion saved (not released).")
            elif action == 'edit_draw':
                teams = logic.room_teams(self.tournament, room)
                assignments = {}
                for t in teams:
                    pair = request.POST.get(f'pair_{t.id}', '')
                    if pair:
                        assignments[t.id] = (int(pair), int(request.POST.get(f'side_{t.id}') or 1))
                logic.apply_manual_draw(round, room, assignments, {t.id for t in teams})
                logic.mirror_native(round, room)
                messages.success(request, "Draw saved. Public pages updated.")
                anchor = 'draw'
            elif action == 'set_judge':
                judge = get_object_or_404(Adjudicator, tournament=self.tournament, id=request.POST.get('judge'))
                for old in Adjudicator.objects.filter(tournament=self.tournament, institution=room).exclude(id=judge.id):
                    old.institution = None
                    old.save(update_fields=['institution'])
                judge.institution = room
                judge.save(update_fields=['institution'])
                for r in self.rounds():
                    logic.mirror_native(r, room)
                messages.success(request, f"{judge.name} now judges Batch {room.code} (same private link).")
            else:
                raise ValidationError("Unknown action.")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        except ValueError:
            messages.error(request, "Something in the form was not a number.")
        return self.back('nsdcroom-director-batch', anchor, room_id=room.id)


# ---------------------------------------------------------------- Results

class ResultsView(DirectorView):
    section = 'results'

    def get(self, request, *args, **kwargs):
        c = self.ctx()
        round, only_missing = c['round'], request.GET.get('missing') == '1'
        blocks = []
        for room in self.rooms(c['track']):
            teams = logic.room_teams(self.tournament, room)
            pairings = logic.pairings_for(round, room)
            logic.label_members(pairings, teams)
            if only_missing:
                pairings = [p for p in pairings if not p.is_scored]
            if pairings:
                blocks.append({'room': room, 'label': logic.public_batch_name(room), 'pairings': pairings})
        return render(request, 'nsdcroom/director/results.html', self.ctx(round=round, blocks=blocks,
                                                                          only_missing=only_missing))

    def post(self, request, *args, **kwargs):
        round = self.pick_round(self.rounds())
        action = request.POST.get('action')
        if action in ('release_results', 'hide_results') and round:
            rel, _ = RoundRelease.objects.get_or_create(round=round)
            rel.results_released = action == 'release_results'
            rel.save()
            messages.success(request, f"{round.name} results {'released to the public' if rel.results_released else 'hidden'}.")
        return self.back('nsdcroom-director-results')


# ---------------------------------------------------------------- Standings

class StandingsView(DirectorView):
    section = 'standings'

    def table(self, track):
        rounds = self.rounds()
        played = [r for r in rounds if Pairing.objects.filter(round=r, pairingspeaker__score__isnull=False).exists()]
        teams = [t for room in self.rooms(track) for t in logic.room_teams(self.tournament, room)]
        rows = logic.ranked(teams, played) if teams else []
        for r in rows:
            r['batch'] = logic.public_batch_name(r['team'].institution)
            r['scores'] = [r['by_round'].get(rd.id) for rd in rounds]
        return rounds, rows

    def get(self, request, *args, **kwargs):
        c = self.ctx()
        track = c['track'] or (c['tracks'][0]['letter'] if c['tracks'] else '')
        rounds, rows = self.table(track)
        if request.GET.get('format') == 'csv':
            resp = HttpResponse(content_type='text/csv')
            resp['Content-Disposition'] = f'attachment; filename="nsdc-standings-{track or "all"}.csv"'
            w = csv.writer(resp)
            w.writerow(['Rank', 'Name', 'School', 'Batch'] + [r.name for r in rounds] + ['Total', 'Wins', 'Qualified'])
            for r in rows:
                w.writerow([r['rank'], r['name'], r['school'], r['batch']]
                           + [('Absent' if s == 0 else s if s is not None else '') for s in r['scores']]
                           + [r['total'], r['wins'], 'Yes' if r['debated'] and r['rank'] <= c['release'].qualify_count else ''])
            return resp
        c.update(track=track, rows=rows, round_names=[r.name for r in rounds])
        return render(request, 'nsdcroom/director/standings.html', c)

    def post(self, request, *args, **kwargs):
        rel = self.release()
        action = request.POST.get('action')
        if action in ('release_standings', 'hide_standings'):
            rel.standings_released = action == 'release_standings'
            messages.success(request, f"Final rankings {'released to the public' if rel.standings_released else 'hidden'}.")
        rel.save()
        return self.back('nsdcroom-director-standings')


# ---------------------------------------------------------------- Judges

class JudgesView(DirectorView):
    section = 'judges'

    def get(self, request, *args, **kwargs):
        judges = Adjudicator.objects.filter(tournament=self.tournament).select_related('institution').order_by(
            'institution__code', 'name')
        rows = [{'j': j, 'url': self.judge_url(j),
                 'batch': logic.public_batch_name(j.institution) if j.institution else ''} for j in judges]
        covered = {j.institution_id for j in judges if j.institution_id}
        uncovered = [r for r in logic.tournament_rooms(self.tournament) if r.id not in covered]
        return render(request, 'nsdcroom/director/judges.html', self.ctx(
            rows=rows, uncovered=uncovered, all_rooms=logic.tournament_rooms(self.tournament)))

    def post(self, request, *args, **kwargs):
        judge = get_object_or_404(Adjudicator, tournament=self.tournament, id=request.POST.get('judge'))
        room_id = request.POST.get('room')
        old_room = judge.institution
        judge.institution = get_object_or_404(Institution, id=room_id) if room_id else None
        judge.save(update_fields=['institution'])
        for room in {old_room, judge.institution} - {None}:
            for r in self.rounds():
                logic.mirror_native(r, room)
        messages.success(request, f"{judge.name}: " + (f"now judges Batch {judge.institution.code}."
                                                      if judge.institution else "moved to backups."))
        return self.back('nsdcroom-director-judges')


# ---------------------------------------------------------------- Messages

class MessagesView(DirectorView):
    section = 'messages'

    def get(self, request, *args, **kwargs):
        qs = Notification.objects.filter(pairing__round__tournament=self.tournament).select_related(
            'pairing__room', 'pairing__round', 'team').order_by('-created_at')
        status = request.GET.get('status', '')
        if status:
            qs = qs.filter(status=status)
        rows = list(qs[:500])
        for n in rows:
            n.when = notify.ist_time(n.created_at)
            n.name = logic.team_name(n.team)
        counts = {s: Notification.objects.filter(pairing__round__tournament=self.tournament, status=s).count()
                  for s in ('sent', 'failed', 'skipped')}
        return render(request, 'nsdcroom/director/messages.html', self.ctx(rows=rows, status=status, counts=counts))


# ---------------------------------------------------------------- Settings

class SettingsView(DirectorView):
    section = 'settings'

    def get(self, request, *args, **kwargs):
        return render(request, 'nsdcroom/director/settings.html', self.ctx())

    def post(self, request, *args, **kwargs):
        rel = self.release()
        try:
            rel.prep_minutes = max(1, int(request.POST.get('prep_minutes') or rel.prep_minutes))
            rel.qualify_count = max(0, int(request.POST.get('qualify_count') or rel.qualify_count))
            rel.save()
            messages.success(request, f"Saved: prep {rel.prep_minutes} min, top {rel.qualify_count} per track qualify.")
        except ValueError:
            messages.error(request, "Use whole numbers.")
        return self.back('nsdcroom-director-settings')
