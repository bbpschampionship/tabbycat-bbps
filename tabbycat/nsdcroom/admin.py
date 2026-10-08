from django.contrib import admin

from .models import Attendance, Pairing, PairingSpeaker, RoomRound, RoundRelease, TournamentRelease


class PairingSpeakerInline(admin.TabularInline):
    model = PairingSpeaker
    extra = 0


@admin.register(Pairing)
class PairingAdmin(admin.ModelAdmin):
    list_display = ('room', 'round', 'seq', 'motion')
    list_filter = ('round', 'room')
    inlines = [PairingSpeakerInline]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('team', 'round', 'present', 'marked_by', 'marked_at')
    list_filter = ('round', 'present')


admin.site.register(RoomRound)
admin.site.register(RoundRelease)
admin.site.register(TournamentRelease)
