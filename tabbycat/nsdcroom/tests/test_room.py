from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from motions.models import Motion, RoundMotion
from participants.models import Adjudicator, Institution, Speaker, Team
from tournaments.models import Round, Tournament

from nsdcroom import logic
from nsdcroom.models import Attendance, Pairing, PairingSpeaker, RoundRelease, TournamentRelease


class RoomTestBase(TestCase):

    def setUp(self):
        self.t = Tournament.objects.create(slug='west', name='NSDC West Zone', short_name='West')
        self.rounds = [Round.objects.create(tournament=self.t, seq=i, name=f'Round {i}', abbreviation=f'R{i}',
                                            draw_type=Round.DrawType.RANDOM if i == 1 else Round.DrawType.POWERPAIRED)
                       for i in (1, 2, 3)]
        self.room = Institution.objects.create(name='Batch A', code='A')
        self.other_room = Institution.objects.create(name='Batch B', code='B')
        self.teams = [self.make_team(self.room, f'Kid {i}') for i in range(1, 8)]  # 7 = odd
        self.other_team = self.make_team(self.other_room, 'Other kid')
        self.judge = Adjudicator.objects.create(tournament=self.t, name='Judge A', institution=self.room, url_key='judgekeyaaaa')
        self.motions = [Motion.objects.create(tournament=self.t, text=f'This House would {i}', reference=f'M{i}') for i in (1, 2, 3, 4)]
        for i, m in enumerate(self.motions, start=1):
            RoundMotion.objects.create(round=self.rounds[0], motion=m, seq=i)

    def make_team(self, room, name):
        team = Team.objects.create(tournament=self.t, institution=room, reference=name, use_institution_prefix=False)
        Speaker.objects.create(team=team, name=name)
        return team

    def url(self, round_seq=1):
        return reverse('nsdcroom-judge', kwargs={'tournament_slug': self.t.slug, 'url_key': self.judge.url_key}) + f'?round={round_seq}'

    def post(self, data, round_seq=1):
        data = {'round': round_seq, **data}
        return self.client.post(self.url(round_seq), data, follow=True)

    def mark_present(self, teams, round_seq=1):
        return self.post({'action': 'attendance', **{f'present_{t.id}': 'on' for t in teams}}, round_seq)


class LogicTests(RoomTestBase):

    def test_scores_whole_numbers_out_of_100_no_ties(self):
        self.assertEqual(logic.validate_scores(['72', '68']), [72, 68])
        for bad in (['70', '70'], ['70.5', '60'], ['101', '50'], ['', '50'], ['-3', '50']):
            with self.assertRaises(ValidationError):
                logic.validate_scores(bad)

    def test_odd_room_makes_one_trio_and_no_rematches(self):
        ids = [t.id for t in self.teams]
        groups = logic.build_groups(self.rounds[0], self.room, ids)
        self.assertEqual(sorted(len(g) for g in groups), [2, 2, 3])
        self.assertEqual(sorted(i for g in groups for i in g), sorted(ids))
        logic.replace_draw(self.rounds[0], self.room, groups)
        for p in Pairing.objects.filter(round=self.rounds[0]):
            members = p.members
            logic.save_scores(p, {m.team_id: str(50 + 10 * k) for k, m in enumerate(members)})
        r1_opponents = {frozenset(g) for g in groups if len(g) == 2}
        groups2 = logic.build_groups(self.rounds[1], self.room, ids)
        for g in groups2:
            if len(g) == 2:
                self.assertNotIn(frozenset(g), r1_opponents)

    def test_single_speaker(self):
        self.assertEqual(logic.build_groups(self.rounds[0], self.room, [self.teams[0].id]), [[self.teams[0].id]])


class JudgeFlowTests(RoomTestBase):

    def test_full_round(self):
        resp = self.client.get(self.url())
        self.assertContains(resp, 'Batch A')
        self.assertNotContains(resp, 'Other kid')

        present = self.teams[:6]
        self.mark_present(present)
        self.assertEqual(Attendance.objects.filter(present=True).count(), 6)
        self.assertEqual(Attendance.objects.filter(present=False).count(), 1)

        resp = self.post({'action': 'generate'})
        self.assertContains(resp, 'Draw generated for 6 speakers')
        pairings = list(Pairing.objects.filter(round=self.rounds[0], room=self.room))
        self.assertEqual(len(pairings), 3)

        # announcing needs a motion on every pair
        resp = self.post({'action': 'announce'})
        self.assertContains(resp, 'Pick a motion for every pair')
        # picking motions and announcing in one go saves the motions too
        resp = self.post({'action': 'announce', **{f'motion_{p.id}': self.motions[i].id for i, p in enumerate(pairings)}})
        self.assertContains(resp, 'Draw announced')

        public = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        self.assertContains(public, 'This House would 1')
        self.assertContains(public, 'Pair 3')

        # a draw (tie) is rejected
        p = pairings[0]
        a, b = p.members
        resp = self.post({'action': 'score', 'pairing': p.id, f'score_{a.team_id}': '70', f'score_{b.team_id}': '70'})
        self.assertContains(resp, 'No draws')
        resp = self.post({'action': 'score', 'pairing': p.id, f'score_{a.team_id}': '70.5', f'score_{b.team_id}': '60'})
        self.assertContains(resp, 'whole numbers')
        resp = self.post({'action': 'score', 'pairing': p.id, f'score_{a.team_id}': '78', f'score_{b.team_id}': '74'})
        self.assertContains(resp, 'Pair 1 result saved')
        self.assertEqual(Pairing.objects.get(id=p.id).winner.team_id, a.team_id)

        # scores hidden publicly until released
        public = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        self.assertNotContains(public, '★ winner')
        RoundRelease.objects.create(round=self.rounds[0], results_released=True)
        public = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        self.assertContains(public, '★ winner')
        self.assertContains(public, 'Batch ranking')

        # released round is locked for the judge
        resp = self.post({'action': 'score', 'pairing': p.id, f'score_{a.team_id}': '10', f'score_{b.team_id}': '90'})
        self.assertContains(resp, 'have been released')
        self.assertEqual(PairingSpeaker.objects.get(pairing=p, team_id=a.team_id).score, 78)

    def test_late_arrival_and_leaver_edit_draw(self):
        self.mark_present(self.teams[:4])
        self.post({'action': 'generate'})
        p1, p2 = Pairing.objects.filter(round=self.rounds[0], room=self.room)
        self.post({'action': 'motions', f'motion_{p1.id}': self.motions[0].id, f'motion_{p2.id}': self.motions[1].id})
        a, b = p1.members
        self.post({'action': 'score', 'pairing': p1.id, f'score_{a.team_id}': '80', f'score_{b.team_id}': '75'})

        # kid 5 arrives late: join pair 2 as third speaker; pair 1 untouched keeps score
        late = self.teams[4]
        self.mark_present(self.teams[:5])
        resp = self.client.get(self.url())
        self.assertContains(resp, 'Present but not in the draw')
        data = {'action': 'edit_draw'}
        for p in (p1, p2):
            for m in p.members:
                data[f'pair_{m.team_id}'] = p.seq
                data[f'side_{m.team_id}'] = m.side
        data[f'pair_{late.id}'] = 2
        data[f'side_{late.id}'] = 3
        resp = self.post(data)
        self.assertContains(resp, 'Draw updated')
        pairings = list(Pairing.objects.filter(round=self.rounds[0], room=self.room))
        self.assertEqual([len(p.members) for p in pairings], [2, 3])
        self.assertTrue(pairings[0].is_scored)
        self.assertEqual(pairings[1].motion_id, self.motions[1].id)  # motion kept for pair 2

        # duplicate side in one pair is rejected
        data[f'side_{late.id}'] = 1
        resp = self.post(data)
        self.assertContains(resp, 'same side')

        # three-way result
        p = pairings[1]
        resp = self.post({'action': 'score', 'pairing': p.id, **{f'score_{m.team_id}': str(60 + i) for i, m in enumerate(p.members)}})
        self.assertContains(resp, 'Pair 2 result saved')

    def test_regenerate_needs_confirm_once_scored(self):
        self.mark_present(self.teams[:2])
        self.post({'action': 'generate'})
        p = Pairing.objects.get(round=self.rounds[0], room=self.room)
        a, b = p.members
        self.post({'action': 'score', 'pairing': p.id, f'score_{a.team_id}': '61', f'score_{b.team_id}': '60'})
        resp = self.post({'action': 'generate'})
        self.assertContains(resp, 'Tick the confirm box')
        resp = self.post({'action': 'generate', 'confirm': 'yes'})
        self.assertContains(resp, 'Draw generated')

    def test_unknown_key_404(self):
        resp = self.client.get(reverse('nsdcroom-judge', kwargs={'tournament_slug': self.t.slug, 'url_key': 'nope'}))
        self.assertEqual(resp.status_code, 404)


class StandingsTests(RoomTestBase):

    def test_overall_rankings_released_with_qualifiers(self):
        url = reverse('nsdcroom-public-standings', kwargs={'tournament_slug': self.t.slug})
        self.assertContains(self.client.get(url), 'will be published')
        logic.replace_draw(self.rounds[0], self.room, [[self.teams[0].id, self.teams[1].id]])
        p = Pairing.objects.get(round=self.rounds[0])
        logic.save_scores(p, {self.teams[0].id: '90', self.teams[1].id: '40'})
        TournamentRelease.objects.create(tournament=self.t, standings_released=True, qualify_count=1)
        resp = self.client.get(url)
        self.assertContains(resp, 'Qualified', count=1)
        self.assertContains(resp, 'Kid 1')

    def test_admin_page_requires_superuser(self):
        url = reverse('nsdcroom-admin', kwargs={'tournament_slug': self.t.slug})
        self.assertEqual(self.client.get(url).status_code, 302)
        admin = get_user_model().objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.force_login(admin)
        resp = self.client.get(url)
        self.assertContains(resp, 'judgekeyaaaa')
        resp = self.client.post(url, {'action': 'release_results', 'round': 1}, follow=True)
        self.assertContains(resp, 'Round 1 results released')
        self.assertTrue(logic.results_released(self.rounds[0]))


class PrivateUrlLinkTests(RoomTestBase):

    def test_judge_private_url_links_to_room(self):
        resp = self.client.get(reverse('privateurls-person-index', kwargs={'tournament_slug': self.t.slug, 'url_key': self.judge.url_key}))
        self.assertContains(resp, reverse('nsdcroom-judge', kwargs={'tournament_slug': self.t.slug, 'url_key': self.judge.url_key}))


class ProfileDisplayTests(RoomTestBase):

    def test_school_batch_name_and_code_shown(self):
        from nsdcroom.models import BatchProfile, StudentProfile
        self.room.code = '07'
        self.room.save()
        BatchProfile.objects.create(institution=self.room, track='B (Grade 6-8)', time_slot='10AM-11:30AM')
        StudentProfile.objects.create(team=self.teams[0], school='Shalom Presidency School')
        self.judge.name = ''
        self.judge.save()
        public = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        for text in ('Kid 1', 'Shalom Presidency School', 'Batch A', 'Batch 07'):
            self.assertContains(public, text)
        judge = self.client.get(self.url())
        self.assertContains(judge, 'Shalom Presidency School')
        self.assertContains(judge, 'Batch A · Batch 07')

    def test_find_a_student_page(self):
        resp = self.client.get(reverse('nsdcroom-public-students', kwargs={'tournament_slug': self.t.slug}))
        self.assertContains(resp, 'Kid 7')
        self.assertContains(resp, 'Batch A')

    def test_tournament_home_goes_to_batches(self):
        from nsdcroom.models import BatchProfile
        BatchProfile.objects.create(institution=self.room, track='A')
        resp = self.client.get(reverse('tournament-public-index', kwargs={'tournament_slug': self.t.slug}))
        self.assertRedirects(resp, reverse('nsdcroom-public-batches', kwargs={'tournament_slug': self.t.slug}),
                             fetch_redirect_response=False)
