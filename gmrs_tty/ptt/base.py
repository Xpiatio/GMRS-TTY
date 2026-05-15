class PTT:
    """PTT interface. Modes share lead-in/tail silence padding so the radio's
    keying ramp or VOX hang time doesn't clip audio."""
    lead_in_seconds = 0.0
    tail_seconds = 0.0

    def key(self):
        pass

    def unkey(self):
        pass

    def close(self):
        pass
