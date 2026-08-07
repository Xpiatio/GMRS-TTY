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
