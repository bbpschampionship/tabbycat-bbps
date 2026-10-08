import random
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction

from motions.models import Motion
from participants.models import Team

from .models import MAX_SCORE, Attendance, Pairing, PairingSpeaker, RoomRound, RoundRelease


def team_name(team):
    speakers = list(team.speaker_set.all())
    if speakers:
        return speakers[0].name
    return team.reference or team.short_name


def team_school(team):
    profile = getattr(team, 'nsdc_student', None)
    return profile.school if profile else ''


def batch_label(room):
    return f"{room.name} · Batch {room.code}" if room.code else room.name


def batch_track(room):
    profile = getattr(room, 'nsdc_batch', None)
    return profile.track if profile else ''


def split_track(track):
    """'B (Grade 6-8)' -> {'letter': 'B', 'grades': 'Grades 6–8'}"""
    import re
    m = re.match(r'\s*([A-Z])\s*\((?:Grades?)\s*([\d]+)\s*-\s*(\d+)\)', track or '')
    if not m:
        return {'letter': track, 'grades': ''}
    return {'letter': m.group(1), 'grades': f"Grades {m.group(2)}–{m.group(3)}"}


def label_members(pairings, teams):
    by_id = {t.id: t for t in teams}
    for p in pairings:
        for m in p.members:
            t = by_id.get(m.team_id)
            m.name = team_name(t) if t else '?'
            m.school = team_school(t) if t else ''


def room_teams(tournament, room):
    return list(Team.objects.filter(tournament=tournament, institution=room)
                .select_related('nsdc_student').prefetch_related('speaker_set').order_by('reference'))


def tournament_rooms(tournament):
    from participants.models import Institution
    return Institution.objects.filter(team__tournament=tournament).distinct().select_related('nsdc_batch').order_by('code', 'name')


def round_motions(round):
    motions = list(Motion.objects.filter(rounds=round).order_by('roundmotion__seq'))
    if not motions:
        motions = list(Motion.objects.filter(tournament=round.tournament).order_by('reference', 'id'))
    return motions


def pairings_for(round, room):
    return list(Pairing.objects.filter(round=round, room=room)
                .select_related('motion')
                .prefetch_related('pairingspeaker_set__team__speaker_set'))


def present_team_ids(round, teams):
    ids = {t.id for t in teams}
    return set(Attendance.objects.filter(round=round, team_id__in=ids, present=True)
               .values_list('team_id', flat=True))


def results_released(round):
    return RoundRelease.objects.filter(round=round, results_released=True).exists()


def room_round(round, room):
    return RoomRound.objects.get_or_create(round=round, room=room)[0]


# ------------------------------------------------------------------------------
# Standings
# ------------------------------------------------------------------------------

def tally(rounds, team_ids=None):
    """{team_id: {'total', 'wins', 'debated', 'by_round': {round_id: score}}} over scored pairs."""
    stats = defaultdict(lambda: {'total': 0, 'wins': 0, 'debated': 0, 'by_round': {}})
    qs = Pairing.objects.filter(round__in=rounds).prefetch_related('pairingspeaker_set')
    if team_ids is not None:
        qs = qs.filter(pairingspeaker__team_id__in=team_ids).distinct()
    for pairing in qs:
        members = pairing.members
        if not pairing.is_scored:
            continue
        winner = pairing.winner
        for m in members:
            if team_ids is not None and m.team_id not in team_ids:
                continue
            s = stats[m.team_id]
            s['total'] += m.score
            s['debated'] += 1
            s['by_round'][pairing.round_id] = m.score
            if winner is not None and winner.team_id == m.team_id:
                s['wins'] += 1
    return stats


def ranked(teams, rounds):
    """Teams ranked by total score, then wins; ties share a rank."""
    stats = tally(rounds, {t.id for t in teams})
    rows = []
    for t in teams:
        s = stats.get(t.id, {'total': 0, 'wins': 0, 'debated': 0, 'by_round': {}})
        rows.append({'team': t, 'name': team_name(t), 'school': team_school(t), **s})
    rows.sort(key=lambda r: (-r['total'], -r['wins'], r['name'].lower()))
    prev, rank = None, 0
    for i, r in enumerate(rows, start=1):
        key = (r['total'], r['wins'])
        if key != prev:
            rank, prev = i, key
        r['rank'] = rank
    return rows


# ------------------------------------------------------------------------------
# Draw generation
# ------------------------------------------------------------------------------

def _previous_opponents(round, room):
    earlier = round.tournament.prelim_rounds(before=round)
    opponents = defaultdict(set)
    prop_count = defaultdict(int)
    for pairing in Pairing.objects.filter(round__in=earlier, room=room).prefetch_related('pairingspeaker_set'):
        ids = [m.team_id for m in pairing.members]
        for m in pairing.members:
            opponents[m.team_id].update(i for i in ids if i != m.team_id)
            if m.side == 1:
                prop_count[m.team_id] += 1
    return earlier, opponents, prop_count


def _pair_up(order, opponents):
    """Pair neighbours in `order`, avoiding rematches where possible (backtracking)."""
    def solve(remaining):
        if not remaining:
            return []
        first, rest = remaining[0], remaining[1:]
        for i, other in enumerate(rest):
            if other in opponents[first]:
                continue
            tail = solve(rest[:i] + rest[i + 1:])
            if tail is not None:
                return [(first, other)] + tail
        return None

    result = solve(order) if len(order) <= 26 else None
    if result is None:  # rematches unavoidable: plain neighbour pairing
        result = [(order[i], order[i + 1]) for i in range(0, len(order) - 1, 2)]
    return result


def build_groups(round, room, team_ids, rng=None):
    """Ordered list of groups (lists of team ids, side order). Pairs of two;
    an odd room ends with one group of three (or a single speaker if alone)."""
    rng = rng or random.Random()
    earlier, opponents, prop_count = _previous_opponents(round, room)
    order = list(team_ids)
    rng.shuffle(order)
    stats = tally(earlier, set(order)) if earlier.exists() else {}
    if stats:  # power-pair: strongest first, random among equals
        order.sort(key=lambda t: (-stats.get(t, {}).get('total', 0), -stats.get(t, {}).get('wins', 0)))

    trio = []
    if len(order) % 2 == 1:
        if len(order) == 1:
            return [order]
        trio, order = order[-3:], order[:-3]

    groups = [list(p) for p in _pair_up(order, opponents)]
    if trio:
        groups.append(trio)
    for g in groups:  # whoever has proposed more often opposes now
        g.sort(key=lambda t: prop_count[t])
    return groups


@transaction.atomic
def replace_draw(round, room, groups):
    Pairing.objects.filter(round=round, room=room).delete()
    for seq, group in enumerate(groups, start=1):
        pairing = Pairing.objects.create(round=round, room=room, seq=seq)
        for side, team_id in enumerate(group, start=1):
            PairingSpeaker.objects.create(pairing=pairing, team_id=team_id, side=side)
    rr = room_round(round, room)
    rr.draw_announced = False
    rr.save()


@transaction.atomic
def apply_manual_draw(round, room, assignments, allowed_team_ids):
    """`assignments`: {team_id: (pair_no, side)} for speakers placed in the draw.
    Keeps motion and scores of pairs whose line-up is unchanged."""
    groups = defaultdict(dict)
    for team_id, (pair_no, side) in assignments.items():
        if team_id not in allowed_team_ids:
            raise ValidationError("A speaker in the draw is not in this room.")
        if side in groups[pair_no]:
            raise ValidationError(f"Pair {pair_no} has two speakers on the same side.")
        groups[pair_no][side] = team_id
    for pair_no, sides in groups.items():
        if len(sides) > 3:
            raise ValidationError(f"Pair {pair_no} has more than three speakers.")

    old, old_motion_by_seq = {}, {}
    for p in pairings_for(round, room):
        old[frozenset((m.team_id, m.side) for m in p.members)] = p
        old_motion_by_seq[p.seq] = p.motion_id

    new_specs = []
    for new_seq, pair_no in enumerate(sorted(groups), start=1):
        sides = groups[pair_no]
        # close gaps in side numbers (e.g. only "Opposition" chosen -> becomes side 1)
        line_up = [sides[s] for s in sorted(sides)]
        new_specs.append((new_seq, line_up))

    kept = {}
    for new_seq, line_up in new_specs:
        key = frozenset((t, side) for side, t in enumerate(line_up, start=1))
        if key in old:
            kept[new_seq] = old.pop(key)

    Pairing.objects.filter(round=round, room=room).exclude(id__in=[p.id for p in kept.values()]).delete()
    # shift kept pairings out of the way so seq renumbering never collides
    for p in kept.values():
        p.seq = p.seq + 1000
        p.save(update_fields=['seq'])
    for new_seq, line_up in new_specs:
        if new_seq in kept:
            p = kept[new_seq]
            p.seq = new_seq
            p.save(update_fields=['seq'])
            continue
        # a changed line-up keeps the motion the judge had picked for that pair number
        pairing = Pairing.objects.create(round=round, room=room, seq=new_seq,
                                         motion_id=old_motion_by_seq.get(new_seq))
        for side, team_id in enumerate(line_up, start=1):
            PairingSpeaker.objects.create(pairing=pairing, team_id=team_id, side=side)


def validate_scores(scores):
    """`scores`: list of raw strings for one pair. Returns ints or raises."""
    values = []
    for raw in scores:
        raw = (raw or '').strip()
        if not raw:
            raise ValidationError("Enter a score for every speaker.")
        if not raw.isdigit():
            raise ValidationError("Scores must be whole numbers (no decimals).")
        v = int(raw)
        if v > MAX_SCORE:
            raise ValidationError(f"Scores are out of {MAX_SCORE}.")
        values.append(v)
    if len(values) > 1 and len(set(values)) != len(values):
        raise ValidationError("No draws: the winner must score higher than the loser.")
    return values


@transaction.atomic
def save_scores(pairing, raw_by_team):
    members = pairing.members
    values = validate_scores([raw_by_team.get(m.team_id) for m in members])
    for m, v in zip(members, values):
        m.score = v
        m.save(update_fields=['score'])
