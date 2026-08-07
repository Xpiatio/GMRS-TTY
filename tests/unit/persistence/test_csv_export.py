"""CSV rendering — quoting semantics mirror the Hearthwave TS reference."""
from gmrs_tty.persistence.csv_export import (
    all_sessions_to_csv,
    session_to_csv,
    stats_to_csv,
)


class TestSessionToCsv:
    def test_header_and_rows(self):
        csv_text = session_to_csv({"roster": [
            {"callsign": "WSLZ233", "name": "Ben", "location": "Ada, MI",
             "gmrs": "WSLZ233", "ham": ""},
        ]})
        lines = csv_text.split("\n")
        assert lines[0] == '"callsign","name","location","gmrs","ham"'
        assert lines[1] == '"WSLZ233","Ben","Ada, MI","WSLZ233",""'

    def test_embedded_quotes_doubled(self):
        csv_text = session_to_csv({"roster": [
            {"callsign": "X", "name": 'Bob "Bobby" Smith', "location": "",
             "gmrs": "", "ham": ""},
        ]})
        assert '"Bob ""Bobby"" Smith"' in csv_text

    def test_empty_roster_is_header_only(self):
        assert session_to_csv({"roster": []}).count("\n") == 0


class TestAllSessionsToCsv:
    def test_one_row_per_station_per_session(self):
        csv_text = all_sessions_to_csv([
            {"id": "s2", "started_at": "2026-08-07T12:00:00+00:00",
             "stations": [{"callsign": "A1", "name": "Ann"}]},
            {"id": "s1", "started_at": "2026-08-01T12:00:00+00:00",
             "stations": [{"callsign": "A1", "name": "Ann"},
                          {"callsign": "B2", "name": ""}]},
        ])
        lines = csv_text.split("\n")
        assert lines[0] == '"net_id","net_date","callsign","name"'
        assert lines[1] == '"s2","2026-08-07","A1","Ann"'
        assert len(lines) == 4


class TestStatsToCsv:
    def test_fields_in_order(self):
        csv_text = stats_to_csv([{
            "callsign": "A1", "name": "Ann", "total_nets": 3,
            "attended_of_recent": 2, "recent_window": 10,
            "current_streak": 1, "last_seen": "2026-08-07T12:00:00+00:00",
        }])
        lines = csv_text.split("\n")
        assert lines[0].startswith('"callsign","name","total_nets"')
        assert lines[1] == '"A1","Ann","3","2","10","1","2026-08-07T12:00:00+00:00"'


class TestFormulaInjection:
    """Excel and LibreOffice evaluate a cell opening with = + - @ as a formula.
    Exports get mailed around, so neutralize the prefix."""

    def _row(self, name):
        return session_to_csv({"roster": [
            {"callsign": "A1", "name": name, "location": "",
             "gmrs": "", "ham": ""},
        ]}).split("\n")[1]

    def test_equals_prefix_is_escaped(self):
        assert self._row("=1+1") == '"A1","\'=1+1","","",""'

    def test_plus_at_and_minus_prefixes_are_escaped(self):
        for prefix in ("+", "-", "@"):
            assert self._row(f"{prefix}cmd") == f'"A1","\'{prefix}cmd","","",""'

    def test_cmd_formula_payload_is_neutralized(self):
        assert self._row('=cmd|" /c calc"!A1').startswith('"A1","\'=cmd')

    def test_ordinary_text_is_untouched(self):
        assert self._row("Ann O'Hara") == '"A1","Ann O\'Hara","","",""'

    def test_formula_char_mid_string_is_untouched(self):
        assert self._row("Ada=MI") == '"A1","Ada=MI","","",""'

    def test_header_is_not_mangled(self):
        assert session_to_csv({"roster": []}) == \
            '"callsign","name","location","gmrs","ham"'

    def test_missing_field_renders_empty_not_none(self):
        row = session_to_csv({"roster": [{"callsign": "A1"}]}).split("\n")[1]
        assert row == '"A1","","","",""'
