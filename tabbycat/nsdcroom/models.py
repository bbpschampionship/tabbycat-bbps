"""Judge-run rooms for the NSDC 1v1 qualifiers.

A room is a training batch, modelled as the Tabbycat Institution shared by the
batch's speakers (one-speaker teams) and its judge(s). Judges take attendance,
generate and edit the room's own draw, pick a motion per pair and enter one
whole-number score out of 100 per speaker. Feedback is verbal, so nothing else
is recorded.
"""
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

MAX_SCORE = 100


class Attendance(models.Model):
    round = models.ForeignKey('tournaments.Round', models.CASCADE)
    team = models.ForeignKey('participants.Team', models.CASCADE)
    present = models.BooleanField(default=False)
    marked_by = models.ForeignKey('participants.Adjudicator', models.SET_NULL, null=True, blank=True)
    marked_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['round', 'team'], name='nsdc_attendance_unique')]


class RoomRound(models.Model):
    """Per-room, per-round state: whether the judge has announced the draw."""
    round = models.ForeignKey('tournaments.Round', models.CASCADE)
    room = models.ForeignKey('participants.Institution', models.CASCADE)
    draw_announced = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['round', 'room'], name='nsdc_roomround_unique')]


class Pairing(models.Model):
    round = models.ForeignKey('tournaments.Round', models.CASCADE)
    room = models.ForeignKey('participants.Institution', models.CASCADE)
    seq = models.PositiveIntegerField(help_text="Pair number within the room")
    motion = models.ForeignKey('motions.Motion', models.SET_NULL, null=True, blank=True)
    motion_released_at = models.DateTimeField(null=True, blank=True)
    prep_ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['seq']
        constraints = [models.UniqueConstraint(fields=['round', 'room', 'seq'], name='nsdc_pairing_unique')]

    def __str__(self):
        return f"{self.room.name} {self.round.abbreviation} pair {self.seq}"

    @property
    def members(self):
        return list(self.pairingspeaker_set.all())

    @property
    def is_scored(self):
        members = self.members
        return bool(members) and all(m.score is not None for m in members)

    @property
    def is_swing(self):
        """A lone speaker debating the swing: they take For and win automatically."""
        return len(self.members) == 1

    @property
    def is_released(self):
        return self.motion_released_at is not None

    @property
    def winner(self):
        members = self.members
        if not members or not self.is_scored:
            return None
        return max(members, key=lambda m: m.score)


class PairingSpeaker(models.Model):
    SIDE_LABELS = {1: "For", 2: "Against"}

    pairing = models.ForeignKey(Pairing, models.CASCADE)
    team = models.ForeignKey('participants.Team', models.CASCADE)
    side = models.PositiveSmallIntegerField(default=1)
    score = models.PositiveSmallIntegerField(null=True, blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(MAX_SCORE)])

    class Meta:
        ordering = ['side']
        constraints = [
            models.UniqueConstraint(fields=['pairing', 'team'], name='nsdc_pairingspeaker_unique'),
            models.UniqueConstraint(fields=['pairing', 'side'], name='nsdc_pairingspeaker_side_unique'),
        ]

    @property
    def side_label(self):
        return self.SIDE_LABELS.get(self.side, f"Speaker {self.side}")


class RoundRelease(models.Model):
    """Tab-director switch: once released, a round's scores are public and locked for judges."""
    round = models.OneToOneField('tournaments.Round', models.CASCADE)
    results_released = models.BooleanField(default=False)


class TournamentRelease(models.Model):
    tournament = models.OneToOneField('tournaments.Tournament', models.CASCADE)
    standings_released = models.BooleanField(default=False)
    qualify_count = models.PositiveIntegerField(default=16,
        help_text="How many top speakers qualify (highlighted on the public standings)")
    prep_minutes = models.PositiveIntegerField(default=20, help_text="Prep time after a pair's motion is released")


class BatchProfile(models.Model):
    """Extra batch details shown on the public tab (batch = Institution: name + code)."""
    institution = models.OneToOneField('participants.Institution', models.CASCADE, related_name='nsdc_batch')
    track = models.CharField(max_length=40, blank=True, help_text='e.g. "A (Grade 3-5)"')
    time_slot = models.CharField(max_length=40, blank=True)
    grades = models.CharField(max_length=40, blank=True)
    poc_name = models.CharField(max_length=100, blank=True)
    poc_phone = models.CharField(max_length=40, blank=True)

    @property
    def grades_label(self):
        """'3 to 4' -> 'Grades 3–4', '5th' -> 'Grade 5'"""
        g = self.grades.strip()
        if ' to ' in g:
            return "Grades " + g.replace(' to ', '–')
        digits = ''.join(c for c in g if c.isdigit())
        return f"Grade {digits}" if digits else g


class StudentProfile(models.Model):
    team = models.OneToOneField('participants.Team', models.CASCADE, related_name='nsdc_student')
    school = models.CharField(max_length=200, blank=True)
    grade = models.CharField(max_length=20, blank=True)


class MotionTrack(models.Model):
    """Which grade track (A/B/C) a motion belongs to; the judge's dropdown only offers their track's motions."""
    motion = models.OneToOneField('motions.Motion', models.CASCADE, related_name='nsdc_track')
    track = models.CharField(max_length=2, help_text="Track letter: A, B or C")


class Notification(models.Model):
    """One WhatsApp or email sent to a student when their pair's motion is released."""
    pairing = models.ForeignKey(Pairing, models.CASCADE)
    team = models.ForeignKey('participants.Team', models.CASCADE)
    channel = models.CharField(max_length=10)  # whatsapp | email
    destination = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=10)  # sent | failed | skipped
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
