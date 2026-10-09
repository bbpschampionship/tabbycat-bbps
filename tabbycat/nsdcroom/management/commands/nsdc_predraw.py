"""Pre-generate every round's draw: each batch debates only within itself, no rematches,
pairs listed in order. Writes the NSDC room draw (public + judge pages) and mirrors it
into Tabbycat's own draw (one venue per batch, the batch judge as chair, For/Against)."""
import random

from django.core.management.base import BaseCommand
from django.db import transaction

from adjallocation.models import DebateAdjudicator
from draw.models import Debate, DebateTeam
from participants.models import Adjudicator
from tournaments.models import Round, Tournament
from venues.models import Venue

from nsdcroom import logic


class Command(BaseCommand):
    help = "Pre-generate within-batch draws for all preliminary rounds"

    def add_arguments(self, parser):
        parser.add_argument('--tournament', default='nsdc-qualifiers')
        parser.add_argument('--seed', type=int, default=2026)

    @transaction.atomic
    def handle(self, *args, **opts):
        t = Tournament.objects.get(slug=opts['tournament'])
        rng = random.Random(opts['seed'])
        t.preferences['debate_rules__side_names'] = 'for-against'
        t.preferences['feedback__feedback_paths'] = 'no-adjs'
        t.preferences['feedback__feedback_from_teams'] = 'no-one'
        t.preferences['data_entry__participant_feedback'] = 'off'
        t.preferences['draw_rules__avoid_same_institution'] = False

        rooms = list(logic.tournament_rooms(t))
        venues = {}
        for room in rooms:
            name = f"Batch {room.code}"
            venues[room.id], _ = Venue.objects.get_or_create(tournament=t, name=name, defaults={'priority': 100})

        rounds = list(t.prelim_rounds().order_by('seq'))
        for r in rounds:
            Debate.objects.filter(round=r).delete()
            rank = 0
            for room in rooms:
                team_ids = [tm.id for tm in logic.room_teams(t, room)]
                groups = logic.build_groups(r, room, team_ids, rng=rng)
                logic.replace_draw(r, room, groups)
                judges = list(Adjudicator.objects.filter(tournament=t, institution=room))
                for group in groups:
                    if len(group) < 2:  # swing: shown on the NSDC batch pages only
                        continue
                    rank += 1
                    d = Debate.objects.create(round=r, venue=venues[room.id], room_rank=rank, bracket=0)
                    for side, team_id in enumerate(group):
                        DebateTeam.objects.create(debate=d, team_id=team_id, side=side)
                    if judges:
                        DebateAdjudicator.objects.create(debate=d, adjudicator=judges[0], type=DebateAdjudicator.TYPE_CHAIR)
            r.draw_status = Round.Status.CONFIRMED
            r.save()
            self.stdout.write(f"{r.name}: {rank} debates across {len(rooms)} batches")
