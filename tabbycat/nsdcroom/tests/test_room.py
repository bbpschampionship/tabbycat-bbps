from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from motions.models import Motion, RoundMotion
from participants.models import Adjudicator, Institution, Speaker, Team
from tournaments.models import Round, Tournament

from nsdcroom import logic
from django.utils import timezone

from nsdcroom.models import Attendance, Notification, Pairing, PairingSpeaker, RoundRelease, TournamentRelease


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

    def test_odd_room_gives_one_swing_and_no_rematches(self):
        ids = [t.id for t in self.teams]  # 7 speakers
        groups = logic.build_groups(self.rounds[0], self.room, ids)
        self.assertEqual(sorted(len(g) for g in groups), [1, 2, 2, 2])
        self.assertEqual(sorted(i for g in groups for i in g), sorted(ids))
        logic.replace_draw(self.rounds[0], self.room, groups)
        swing = Pairing.objects.get(round=self.rounds[0], pairingspeaker__isnull=False, seq=4)
        self.assertTrue(swing.is_swing)
        self.assertEqual(swing.members[0].side_label, 'For')
        for p in Pairing.objects.filter(round=self.rounds[0]):
            logic.save_scores(p, {m.team_id: str(50 + 10 * k) for k, m in enumerate(p.members)})
        self.assertEqual(Pairing.objects.get(id=swing.id).winner.team_id, swing.members[0].team_id)  # automatic win
        self.assertEqual(logic.tally(self.rounds[:1])[swing.members[0].team_id]['wins'], 1)
        r1_opponents = {frozenset(g) for g in groups if len(g) == 2}
        groups2 = logic.build_groups(self.rounds[1], self.room, ids)
        for g in groups2:
            if len(g) == 2:
                self.assertNotIn(frozenset(g), r1_opponents)
            else:  # nobody gets the swing twice
                self.assertNotEqual(g[0], swing.members[0].team_id)

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

        # the draw is public straight away; motions only once released
        public_url = reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id})
        public = self.client.get(public_url)
        self.assertContains(public, 'Pair 3')
        self.assertContains(public, 'Motion soon')
        resp = self.post({'action': 'release', 'pairing': pairings[0].id})
        self.assertContains(resp, 'Pick a motion for Pair 1 first')
        resp = self.post({'action': 'release', 'pairing': pairings[0].id, f'motion_{pairings[0].id}': self.motions[0].id})
        self.assertContains(resp, 'Pair 1: motion released, prep ends at')
        p1 = Pairing.objects.get(id=pairings[0].id)
        self.assertEqual(round((p1.prep_ends_at - p1.motion_released_at).total_seconds()), 20 * 60)
        # no messaging configured in tests: both channels logged as skipped for both speakers
        self.assertEqual(Notification.objects.filter(pairing=p1, status='skipped').count(), 4)
        public = self.client.get(public_url)
        self.assertContains(public, 'This House would 1')
        self.assertNotContains(public, 'This House would 2')
        self.assertContains(public, 'Prep ends')

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
        self.assertNotContains(public, '★ Winner')
        RoundRelease.objects.create(round=self.rounds[0], results_released=True)
        public = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        self.assertContains(public, '★ Winner')
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

        # kid 5 arrives late: debates the swing as pair 3; pairs 1-2 untouched keep scores and motions
        late = self.teams[4]
        self.mark_present(self.teams[:5])
        self.assertContains(self.client.get(self.url()), 'Present but not in the draw')
        data = {'action': 'edit_draw'}
        for p in (p1, p2):
            for m in p.members:
                data[f'pair_{m.team_id}'] = p.seq
                data[f'side_{m.team_id}'] = m.side
        data[f'pair_{late.id}'] = 3
        data[f'side_{late.id}'] = 2
        resp = self.post(data)
        self.assertContains(resp, 'must be For')
        data[f'side_{late.id}'] = 1
        resp = self.post(data)
        self.assertContains(resp, 'Draw updated')
        pairings = list(Pairing.objects.filter(round=self.rounds[0], room=self.room))
        self.assertEqual([len(p.members) for p in pairings], [2, 2, 1])
        self.assertTrue(pairings[0].is_scored)
        self.assertEqual(pairings[1].motion_id, self.motions[1].id)

        # two speakers on the same side are rejected
        a2, b2 = pairings[1].members
        data[f'side_{b2.team_id}'] = a2.side
        self.assertContains(self.post(data), 'same side')

        # swing result: one score, automatic win
        swing = pairings[2]
        resp = self.post({'action': 'score', 'pairing': swing.id, f'score_{late.id}': '64'})
        self.assertContains(resp, 'Pair 3 result saved')
        self.assertEqual(Pairing.objects.get(id=swing.id).winner.team_id, late.id)

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


class ParentHomeTests(RoomTestBase):

    def test_home_has_finder_and_links_but_not_batch_list(self):
        from nsdcroom.models import BatchProfile, StudentProfile
        BatchProfile.objects.create(institution=self.room, track='A (Grade 3-5)', time_slot='3PM-4:30PM', grades='3 to 5')
        StudentProfile.objects.create(team=self.teams[0], school='Shalom Presidency School')
        home = self.client.get(reverse('nsdcroom-public-batches', kwargs={'tournament_slug': self.t.slug}))
        self.assertContains(home, "Find your child")
        self.assertContains(home, 'Shalom Presidency School')
        self.assertContains(home, 'Results announcement')
        self.assertContains(home, 'must take part in all 3 rounds')
        self.assertNotContains(home, '3PM-4:30PM')
        self.assertContains(home, reverse('nsdcroom-public-batch-list', kwargs={'tournament_slug': self.t.slug}))
        self.assertNotContains(home, 'class="card bcard"')
        lst = self.client.get(reverse('nsdcroom-public-batch-list', kwargs={'tournament_slug': self.t.slug}))
        self.assertContains(lst, 'class="card bcard"')

    def test_subpages(self):
        from nsdcroom.models import BatchProfile
        BatchProfile.objects.create(institution=self.room, track='A (Grade 3-5)', time_slot='10AM-11:30AM', grades='3 to 4')
        kw = {'tournament_slug': self.t.slug}
        judges = self.client.get(reverse('nsdcroom-public-judges', kwargs=kw))
        self.assertContains(judges, 'Judge A')
        self.assertNotContains(judges, self.judge.url_key)
        self.judge.name = ''
        self.judge.save()
        self.assertContains(self.client.get(reverse('nsdcroom-public-judges', kwargs=kw)), 'To be announced')
        # rounds shows announced draws; results stays empty until released
        logic.replace_draw(self.rounds[0], self.room, [[self.teams[0].id, self.teams[1].id]])
        p = Pairing.objects.get(round=self.rounds[0])
        p.motion = self.motions[0]
        p.save()
        logic.save_scores(p, {self.teams[0].id: '71', self.teams[1].id: '69'})
        rr = logic.room_round(self.rounds[0], self.room)
        rr.draw_announced = True
        rr.save()
        p.motion_released_at = p.prep_ends_at = timezone.now()
        p.save()
        self.assertContains(self.client.get(reverse('nsdcroom-public-rounds', kwargs=kw) + '?round=1'), 'This House would 1')
        results = self.client.get(reverse('nsdcroom-public-results', kwargs=kw) + '?round=1')
        self.assertContains(results, 'will be published')
        self.assertNotContains(results, '>71<')
        RoundRelease.objects.create(round=self.rounds[0], results_released=True)
        self.assertContains(self.client.get(reverse('nsdcroom-public-results', kwargs=kw) + '?round=1'), '71')
        home = self.client.get(reverse('nsdcroom-public-batches', kwargs=kw))
        for name in ('Batches', 'Participants', 'Judges', 'Rounds', 'Results', 'Rankings'):
            self.assertContains(home, name)


class JudgeAllocationTests(RoomTestBase):

    def test_judge_phone_public_backups_private(self):
        self.judge.phone = '+91 90000 11111'
        self.judge.save()
        backup = Adjudicator.objects.create(tournament=self.t, name='Backup B', phone='+91 90000 22222', url_key='backupkeybbbb')
        kw = {'tournament_slug': self.t.slug}
        public = self.client.get(reverse('nsdcroom-public-judges', kwargs=kw))
        self.assertContains(public, 'Judge A')
        self.assertContains(public, '+91 90000 11111')  # parents call the judge for help
        self.assertNotContains(public, '22222')
        self.assertNotContains(public, 'Backup B')
        admin = get_user_model().objects.create_superuser('boss', 'b@example.com', 'pw')
        self.client.force_login(admin)
        page = self.client.get(reverse('nsdcroom-admin', kwargs=kw))
        self.assertContains(page, '+91 90000 11111')
        self.assertContains(page, 'backupkeybbbb')
        resp = self.client.post(reverse('nsdcroom-admin', kwargs=kw),
                                {'action': 'assign_judge', 'judge': backup.id, 'room': self.room.id, 'round': 1}, follow=True)
        self.assertContains(resp, 'can now run Batch A')
        backup.refresh_from_db()
        self.assertEqual(backup.institution, self.room)
        self.client.logout()
        judge_page = self.client.get(reverse('nsdcroom-judge', kwargs={**kw, 'url_key': 'backupkeybbbb'}))
        self.assertContains(judge_page, 'Kid 1')


class ReleaseAndImportTests(RoomTestBase):

    def setUp(self):
        super().setUp()
        from nsdcroom.models import BatchProfile
        BatchProfile.objects.create(institution=self.room, track='A (Grade 3-5)', poc_name='Riya POC', poc_phone='+91 95555 00000')
        for i, t in enumerate(self.teams):
            sp = t.speaker_set.first()
            sp.email, sp.phone = f'kid{i}@example.com', f'98765 4321{i}'
            sp.save()

    def test_judge_dropdown_only_offers_own_track(self):
        from nsdcroom.models import MotionTrack
        MotionTrack.objects.create(motion=self.motions[0], track='A')
        MotionTrack.objects.create(motion=self.motions[1], track='B')
        offered = {m.id for m in logic.round_motions(self.rounds[0], self.room)}
        self.assertIn(self.motions[0].id, offered)
        self.assertNotIn(self.motions[1].id, offered)

    def test_release_sends_whatsapp_and_email_with_side_motion_and_prep_end(self):
        import json
        from unittest import mock
        from django.core import mail
        from django.core.mail import get_connection
        from nsdcroom import notify
        logic.replace_draw(self.rounds[0], self.room, [[self.teams[0].id, self.teams[1].id]])
        p = Pairing.objects.get(round=self.rounds[0])
        sent = []

        class Resp:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return b'{"success":"true"}'

        def fake_urlopen(req, timeout=None):
            sent.append(json.loads(req.data))
            return Resp()

        env = {'AISENSY_API_KEY': 'k', 'NSDC_AISENSY_CAMPAIGN': 'nsdc_motion', 'NSDC_SMTP_USER': 'u@x.com', 'NSDC_SMTP_PASSWORD': 'p'}
        with mock.patch.dict('os.environ', env), mock.patch('urllib.request.urlopen', fake_urlopen), \
                mock.patch.object(notify, 'smtp_connection', lambda: get_connection('django.core.mail.backends.locmem.EmailBackend')):
            resp = self.post({'action': 'release', 'pairing': p.id, f'motion_{p.id}': self.motions[2].id})
        self.assertContains(resp, 'Messages sent: 4')
        self.assertEqual([s['destination'] for s in sent], ['919876543210', '919876543211'])
        params = sent[0]['templateParams']
        self.assertEqual(params[0], 'Kid 1')
        self.assertIn('FOR', params[3])
        self.assertEqual(params[5], 'This House would 3')
        self.assertTrue(params[6].endswith(('AM', 'PM')))
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn('This House would 3', mail.outbox[0].body)
        self.assertIn('Riya POC', mail.outbox[0].body)
        self.assertIn('Judge A', mail.outbox[0].body)

    def test_motion_and_poc_import(self):
        import os, tempfile
        import openpyxl
        from django.core.management import call_command
        from nsdcroom.models import BatchProfile, MotionTrack
        self.room.code = '01'
        self.room.save()
        d = tempfile.mkdtemp()
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(['Round', 'Track', 'Motion'])
        for rnd in (1, 2):
            for trk in ('Primary', 'Junior'):
                for k in range(3):
                    ws.append([f'Round {rnd}', trk, f'THW motion {trk} R{rnd} #{k}'])
        mpath = os.path.join(d, 'm.xlsx'); wb.save(mpath)
        call_command('nsdc_import_motions', mpath, tournament=self.t.slug, stdout=open(os.devnull, 'w'))
        call_command('nsdc_import_motions', mpath, tournament=self.t.slug, stdout=open(os.devnull, 'w'))  # idempotent
        self.assertEqual(MotionTrack.objects.filter(track='A').count(), 6)
        self.assertEqual(MotionTrack.objects.filter(track='B').count(), 6)
        offered = [m.text for m in logic.round_motions(self.rounds[1], self.room)]
        self.assertIn('THW motion Primary R2 #0', offered)
        self.assertNotIn('THW motion Junior R2 #0', offered)
        self.assertNotIn('THW motion Primary R1 #0', offered)
        wb = openpyxl.Workbook(); ws = wb.active
        ws.append(['Batch Code', 'Batch', 'POC', 'POC Contact'])
        ws.append(['01', 'Batch A', 'Meera', '+91 91111 22222'])
        ppath = os.path.join(d, 'p.xlsx'); wb.save(ppath)
        call_command('nsdc_import_pocs', ppath, tournament=self.t.slug, stdout=open(os.devnull, 'w'))
        bp = BatchProfile.objects.get(institution=self.room)
        self.assertEqual((bp.poc_name, bp.poc_phone), ('Meera', '+91 91111 22222'))
        page = self.client.get(reverse('nsdcroom-public-batch', kwargs={'tournament_slug': self.t.slug, 'room_id': self.room.id}))
        self.assertContains(page, 'Meera')
        self.assertContains(page, '+91 91111 22222')

    def test_release_via_n8n_webhook_records_results(self):
        import json
        from unittest import mock
        logic.replace_draw(self.rounds[0], self.room, [[self.teams[0].id, self.teams[1].id]])
        p = Pairing.objects.get(round=self.rounds[0])
        calls = []

        class Resp:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self, n=-1): return self.body

        def fake_urlopen(req, timeout=None):
            payload = json.loads(req.data)
            calls.append(payload)
            res = [{'team_id': s['team_id'], 'channel': 'whatsapp', 'status': 'sent', 'detail': 'ok'} for s in payload['students']]
            res += [{'team_id': s['team_id'], 'channel': 'email', 'status': 'failed', 'detail': 'quota'} for s in payload['students']]
            return Resp(json.dumps({'results': res}).encode())

        env = {'NSDC_N8N_WEBHOOK_URL': 'https://n8n.example/webhook/x', 'NSDC_N8N_SECRET': 's3cret'}
        with mock.patch.dict('os.environ', env), mock.patch('urllib.request.urlopen', fake_urlopen):
            resp = self.post({'action': 'release', 'pairing': p.id, f'motion_{p.id}': self.motions[0].id})
        self.assertContains(resp, 'Messages sent: 2, failed: 2')
        body = calls[0]
        self.assertEqual(body['secret'], 's3cret')
        self.assertEqual([s['side'] for s in body['students']], ['FOR', 'AGAINST'])
        self.assertEqual(body['students'][0]['phone'], '919876543210')
        self.assertEqual(body['students'][1]['opponent'], 'Kid 1')
        self.assertEqual(body['poc'], 'Riya POC +91 95555 00000')
        self.assertEqual(Notification.objects.filter(pairing=p, channel='whatsapp', status='sent').count(), 2)

        def down(req, timeout=None):
            raise OSError('connection refused')
        with mock.patch.dict('os.environ', env), mock.patch('urllib.request.urlopen', down):
            resp = self.post({'action': 'release', 'pairing': p.id, f'motion_{p.id}': self.motions[0].id})
        self.assertContains(resp, 'failed: 4')
        self.assertTrue(Pairing.objects.get(id=p.id).is_released)  # prep still starts when n8n is down
