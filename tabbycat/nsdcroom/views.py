from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from participants.models import Adjudicator, Institution
from tournaments.models import Round, Tournament

from . import logic
from .models import MAX_SCORE, Attendance, Pairing, RoundRelease, TournamentRelease


class TournamentView(View):

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.tournament = get_object_or_404(Tournament, slug=kwargs['tournament_slug'])

    def rounds(self):
        return list(self.tournament.prelim_rounds().order_by('seq'))

    def pick_round(self, rounds):
        seq = self.request.GET.get('round') or self.request.POST.get('round')
        if seq:
            for r in rounds:
                if str(r.seq) == str(seq):
                    return r
        current = self.tournament.current_round
        if current in rounds:
            return current
        return rounds[0] if rounds else None


# ==============================================================================
# Judge console (private URL)
# ==============================================================================

class JudgeRoomView(TournamentView):
    template_name = 'nsdcroom/judge_room.html'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.judge = get_object_or_404(Adjudicator, tournament=self.tournament, url_key=kwargs['url_key'])
        self.room = self.judge.institution

    ANCHORS = {'generate': 'draw', 'edit_draw': 'draw', 'motions': 'motions', 'announce': 'motions',
               'unannounce': 'motions'}

    def here(self, round, anchor=''):
        url = reverse('nsdcroom-judge', kwargs={'tournament_slug': self.tournament.slug, 'url_key': self.judge.url_key})
        url = f"{url}?round={round.seq}" if round else url
        return redirect(f"{url}#{anchor}" if anchor else url)

    def get(self, request, *args, **kwargs):
        rounds = self.rounds()
        round = self.pick_round(rounds)
        ctx = {'tournament': self.tournament, 'judge': self.judge, 'room': self.room,
               'batch_label': logic.batch_label(self.room) if self.room else '',
               'rounds': rounds, 'round': round, 'max_score': MAX_SCORE}
        if self.room is None or round is None:
            return render(request, self.template_name, ctx)

        teams = logic.room_teams(self.tournament, self.room)
        present = logic.present_team_ids(round, teams)
        marked = set(Attendance.objects.filter(round=round, team__in=teams).values_list('team_id', flat=True))
        pairings = logic.pairings_for(round, self.room)
        placed = {m.team_id: (p.seq, m.side) for p in pairings for m in p.members}
        logic.label_members(pairings, teams)

        speakers = []
        for t in teams:
            speakers.append({'team': t, 'name': logic.team_name(t), 'school': logic.team_school(t),
                             'present': t.id in present,
                             'marked': t.id in marked, 'pair': placed.get(t.id, (None, None))[0],
                             'side': placed.get(t.id, (None, None))[1]})
        speakers.sort(key=lambda s: s['name'].lower())
        unplaced_present = [s for s in speakers if s['present'] and s['pair'] is None]
        placed_absent = [s for s in speakers if not s['present'] and s['pair'] is not None]

        ctx.update({
            'speakers': speakers, 'present_count': len(present), 'pairings': pairings,
            'motions': logic.round_motions(round), 'room_round': logic.room_round(round, self.room),
            'locked': logic.results_released(round), 'unplaced_present': unplaced_present,
            'placed_absent': placed_absent,
            'pair_choices': range(1, max(len(pairings), (len(teams) + 1) // 2) + 2),
            'scored_count': sum(1 for p in pairings if p.is_scored),
            'any_scores': any(m.score is not None for p in pairings for m in p.members),
            'standings': logic.ranked(teams, [r for r in rounds if r.seq <= round.seq]),
        })
        return render(request, self.template_name, ctx)

    def post(self, request, *args, **kwargs):
        rounds = self.rounds()
        round = self.pick_round(rounds)
        if self.room is None or round is None:
            raise Http404
        if logic.results_released(round):
            messages.error(request, "Results for this round have been released — ask the tab team to make changes.")
            return self.here(round)

        teams = logic.room_teams(self.tournament, self.room)
        team_ids = {t.id for t in teams}
        action = request.POST.get('action')
        try:
            if action == 'attendance':
                self.save_attendance(round, teams)
                messages.success(request, "Attendance saved.")
            elif action == 'generate':
                present = logic.present_team_ids(round, teams)
                if not present:
                    raise ValidationError("Mark who is present before generating the draw.")
                if (Pairing.objects.filter(round=round, room=self.room, pairingspeaker__score__isnull=False).exists()
                        and request.POST.get('confirm') != 'yes'):
                    raise ValidationError("Scores are already entered. Tick the confirm box to throw them away and re-draw.")
                logic.replace_draw(round, self.room, logic.build_groups(round, self.room, sorted(present)))
                messages.success(request, f"Draw generated for {len(present)} speakers.")
            elif action == 'edit_draw':
                assignments = {}
                for t in teams:
                    pair = request.POST.get(f'pair_{t.id}', '')
                    if pair:
                        assignments[t.id] = (int(pair), int(request.POST.get(f'side_{t.id}') or 1))
                logic.apply_manual_draw(round, self.room, assignments, team_ids)
                messages.success(request, "Draw updated.")
            elif action == 'motions':
                self.save_motions(round)
                messages.success(request, "Motions saved.")
            elif action in ('announce', 'unannounce'):
                rr = logic.room_round(round, self.room)
                pairings = logic.pairings_for(round, self.room)
                if action == 'announce':
                    self.save_motions(round)
                    pairings = logic.pairings_for(round, self.room)
                    if not pairings:
                        raise ValidationError("Generate the draw first.")
                    if any(p.motion_id is None for p in pairings):
                        raise ValidationError("Pick a motion for every pair before announcing.")
                rr.draw_announced = action == 'announce'
                rr.save()
                messages.success(request, "Draw announced — it is now on the public page." if rr.draw_announced
                                 else "Draw hidden from the public page.")
            elif action == 'score':
                pairing = get_object_or_404(Pairing, id=request.POST.get('pairing'), round=round, room=self.room)
                raw = {m.team_id: request.POST.get(f'score_{m.team_id}') for m in pairing.members}
                logic.save_scores(pairing, raw)
                messages.success(request, f"Pair {pairing.seq} result saved.")
            else:
                raise ValidationError("Unknown action.")
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        except ValueError:
            messages.error(request, "Something in the form was not a number.")
        anchor = self.ANCHORS.get(action, '')
        if action == 'score':
            anchor = f"pair-{request.POST.get('pairing_seq', '')}" if request.POST.get('pairing_seq') else 'results'
        return self.here(round, anchor)

    def save_motions(self, round):
        allowed = {m.id for m in logic.round_motions(round)}
        for p in Pairing.objects.filter(round=round, room=self.room):
            key = f'motion_{p.id}'
            if key not in self.request.POST:
                continue
            raw = self.request.POST.get(key, '')
            motion_id = int(raw) if raw else None
            if motion_id is not None and motion_id not in allowed:
                raise ValidationError("Pick a motion from the list.")
            if p.motion_id != motion_id:
                p.motion_id = motion_id
                p.save(update_fields=['motion'])

    @transaction.atomic
    def save_attendance(self, round, teams):
        for t in teams:
            Attendance.objects.update_or_create(
                round=round, team=t,
                defaults={'present': request_has(self.request, f'present_{t.id}'), 'marked_by': self.judge})


def request_has(request, key):
    return request.POST.get(key) in ('on', '1', 'true')


# ==============================================================================
# Public pages
# ==============================================================================

def _public_round_blocks(tournament, room, rounds, teams):
    blocks = []
    for r in rounds:
        rr = logic.room_round(r, room)
        released = logic.results_released(r)
        pairings = logic.pairings_for(r, room) if (rr.draw_announced or released) else []
        logic.label_members(pairings, teams)
        blocks.append({'round': r, 'announced': rr.draw_announced, 'released': released,
                       'pairings': pairings})
    return blocks


class PublicHomeView(TournamentView):
    """The parent-facing front page: find your child's batch, the day's slots, how it works."""

    SLOT_ORDER = {'AM': 0, 'PM': 1}

    def get(self, request, *args, **kwargs):
        teams = list(self.tournament.team_set.select_related('institution__nsdc_batch', 'nsdc_student')
                     .prefetch_related('speaker_set'))
        students = sorted(({'name': logic.team_name(t), 'school': logic.team_school(t), 'room': t.institution,
                            'profile': getattr(t.institution, 'nsdc_batch', None) if t.institution else None}
                           for t in teams), key=lambda s: s['name'].lower())
        rooms = list(logic.tournament_rooms(self.tournament))
        slots = {}
        for room in rooms:
            profile = getattr(room, 'nsdc_batch', None)
            if profile and profile.time_slot:
                slots.setdefault(profile.time_slot, []).append(room)

        def slot_key(label):
            import re
            m = re.match(r'(\d+)(?::\d+)?\s*(AM|PM)', label)
            if not m:
                return (9, 0)
            hour = int(m.group(1)) % 12 + (12 if m.group(2) == 'PM' else 0)
            return (0, hour)

        def slot_name(hour):
            return 'Morning' if hour < 12 else 'Afternoon' if hour < 17 else 'Evening'

        tracks = {}
        for room in rooms:
            profile = getattr(room, 'nsdc_batch', None)
            tracks.setdefault(profile.track if profile else '', 0)
            tracks[profile.track if profile else ''] += 1
        rounds = self.rounds()
        round = self.pick_round(rounds)
        live = round and logic.RoomRound.objects.filter(round=round, draw_announced=True).exists()
        release = TournamentRelease.objects.filter(tournament=self.tournament).first()
        return render(request, 'nsdcroom/public_home.html', {
            'tournament': self.tournament, 'students': students, 'room_count': len(rooms),
            'slots': [{'label': k, 'rooms': v, 'name': slot_name(slot_key(k)[1])}
                      for k, v in sorted(slots.items(), key=lambda kv: slot_key(kv[0]))],
            'tracks': [{'track': k, **logic.split_track(k), 'count': n} for k, n in sorted(tracks.items())],
            'round': round, 'draw_live': live, 'release': release, 'nav': 'home',
            'standings_released': bool(release and release.standings_released)})


class PublicBatchesView(TournamentView):
    """Batches (directory), Rounds (announced draws) and Results (released scores) share one layout."""
    mode = 'batches'

    def get(self, request, *args, **kwargs):
        rounds = self.rounds()
        round = self.pick_round(rounds)
        released = bool(round and logic.results_released(round))
        rooms = []
        for room in logic.tournament_rooms(self.tournament):
            teams = logic.room_teams(self.tournament, room)
            block = None
            if self.mode != 'batches' and round:
                block = _public_round_blocks(self.tournament, room, [round], teams)[0]
                if self.mode == 'results' and not (block['released'] and block['pairings']):
                    continue
            rooms.append({'room': room, 'label': logic.batch_label(room), 'profile': getattr(room, 'nsdc_batch', None),
                          'count': len(teams), 'block': block})
        tracks = {}
        for row in rooms:
            tracks.setdefault(row['profile'].track if row['profile'] else '', []).append(row)
        return render(request, 'nsdcroom/public_batch_list.html', {
            'tournament': self.tournament, 'rounds': rounds, 'round': round, 'rooms': rooms, 'mode': self.mode,
            'nav': self.mode, 'released': released,
            'tracks': [{'track': k, **logic.split_track(k), 'rooms': v} for k, v in sorted(tracks.items())],
            'student_count': sum(r['count'] for r in rooms)})


class PublicJudgesView(TournamentView):

    def get(self, request, *args, **kwargs):
        rows = []
        for room in logic.tournament_rooms(self.tournament):
            judges = [j.name for j in Adjudicator.objects.filter(tournament=self.tournament, institution=room) if j.name]
            rows.append({'room': room, 'profile': getattr(room, 'nsdc_batch', None), 'judges': judges})
        return render(request, 'nsdcroom/public_judges.html', {'tournament': self.tournament, 'rows': rows, 'nav': 'judges'})


class PublicBatchView(TournamentView):

    def get(self, request, *args, **kwargs):
        room = get_object_or_404(Institution, id=kwargs['room_id'])
        teams = logic.room_teams(self.tournament, room)
        if not teams:
            raise Http404
        rounds = self.rounds()
        released_rounds = [r for r in rounds if logic.results_released(r)]
        standings = logic.ranked(teams, released_rounds) if released_rounds else []
        students = sorted(({'name': logic.team_name(t), 'school': logic.team_school(t)} for t in teams),
                          key=lambda s: s['name'].lower())
        return render(request, 'nsdcroom/public_batch.html', {
            'tournament': self.tournament, 'room': room, 'rounds': rounds, 'nav': 'batches',
            'label': logic.batch_label(room), 'profile': getattr(room, 'nsdc_batch', None),
            'track': logic.split_track(getattr(getattr(room, 'nsdc_batch', None), 'track', '')),
            'blocks': _public_round_blocks(self.tournament, room, rounds, teams),
            'students': students,
            'released_rounds': released_rounds,
            'standings': standings if any(r['debated'] for r in standings) else []})


class PublicStudentsView(TournamentView):

    def get(self, request, *args, **kwargs):
        teams = (self.tournament.team_set.select_related('institution__nsdc_batch', 'nsdc_student')
                 .prefetch_related('speaker_set'))
        students = sorted(({'name': logic.team_name(t), 'school': logic.team_school(t), 'room': t.institution}
                           for t in teams), key=lambda s: s['name'].lower())
        return render(request, 'nsdcroom/public_students.html', {'tournament': self.tournament, 'students': students,
                                                                 'nav': 'participants'})


class PublicStandingsView(TournamentView):

    def get(self, request, *args, **kwargs):
        release = TournamentRelease.objects.filter(tournament=self.tournament).first()
        tracks = []
        if release and release.standings_released:
            teams = list(self.tournament.team_set.select_related('institution__nsdc_batch', 'nsdc_student')
                         .prefetch_related('speaker_set'))
            by_track = {}
            for t in teams:
                by_track.setdefault(logic.batch_track(t.institution) if t.institution else '', []).append(t)
            rounds = self.rounds()
            for track in sorted(by_track):
                rows = logic.ranked(by_track[track], rounds)
                for r in rows:
                    r['batch'] = logic.batch_label(r['team'].institution) if r['team'].institution else ''
                    r['qualified'] = r['rank'] <= release.qualify_count
                tracks.append({'track': track, **logic.split_track(track), 'rows': rows})
        return render(request, 'nsdcroom/public_standings.html', {
            'tournament': self.tournament, 'tracks': tracks, 'release': release, 'rounds': self.rounds(),
            'nav': 'rankings'})


# ==============================================================================
# Tab director overview
# ==============================================================================

class AdminRoomsView(TournamentView):

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('login')}?next={request.path}")
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        rounds = self.rounds()
        round = self.pick_round(rounds)
        rooms = []
        for room in logic.tournament_rooms(self.tournament):
            teams = logic.room_teams(self.tournament, room)
            judges = list(Adjudicator.objects.filter(tournament=self.tournament, institution=room))
            row = {'room': room, 'label': logic.batch_label(room), 'count': len(teams), 'judges': [
                {'judge': j, 'url': request.build_absolute_uri(reverse('nsdcroom-judge', kwargs={
                    'tournament_slug': self.tournament.slug, 'url_key': j.url_key})) if j.url_key else None}
                for j in judges]}
            if round:
                pairings = logic.pairings_for(round, room)
                row.update({'present': len(logic.present_team_ids(round, teams)), 'pairs': len(pairings),
                            'scored': sum(1 for p in pairings if p.is_scored),
                            'announced': logic.room_round(round, room).draw_announced})
            rooms.append(row)
        orphan_judges = Adjudicator.objects.filter(tournament=self.tournament, institution__isnull=True)
        return render(request, 'nsdcroom/admin_rooms.html', {
            'tournament': self.tournament, 'rounds': rounds, 'round': round, 'rooms': rooms,
            'released': logic.results_released(round) if round else False,
            'release': TournamentRelease.objects.get_or_create(tournament=self.tournament)[0],
            'orphan_judges': orphan_judges})

    def post(self, request, *args, **kwargs):
        rounds = self.rounds()
        round = self.pick_round(rounds)
        action = request.POST.get('action')
        if action in ('release_results', 'hide_results') and round:
            rel, _ = RoundRelease.objects.get_or_create(round=round)
            rel.results_released = action == 'release_results'
            rel.save()
            messages.success(request, f"{round.name} results {'released' if rel.results_released else 'hidden'}.")
        elif action in ('release_standings', 'hide_standings'):
            rel, _ = TournamentRelease.objects.get_or_create(tournament=self.tournament)
            rel.standings_released = action == 'release_standings'
            try:
                rel.qualify_count = max(0, int(request.POST.get('qualify_count') or rel.qualify_count))
            except ValueError:
                pass
            rel.save()
            messages.success(request, f"Standings {'released' if rel.standings_released else 'hidden'}.")
        url = reverse('nsdcroom-admin', kwargs={'tournament_slug': self.tournament.slug})
        return redirect(f"{url}?round={round.seq}" if round else url)
