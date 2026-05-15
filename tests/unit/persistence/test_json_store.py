import json

from gmrs_tty.persistence.json_store import load_json, save_json


class TestLoadJson:
    def test_missing_file_returns_default(self, tmp_path):
        default = {"callsign": "N0CALL"}
        result = load_json(str(tmp_path / "missing.json"), default)
        assert result == default

    def test_corrupted_file_returns_default(self, tmp_path, capsys):
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json")
        default = {"fallback": True}
        result = load_json(str(path), default)
        assert result == default
        # The helper prints a diagnostic so the operator can see it failed.
        assert "Error decoding" in capsys.readouterr().out

    def test_valid_file_returns_parsed(self, tmp_path):
        path = tmp_path / "ok.json"
        path.write_text(json.dumps({"callsign": "WSLZ233", "name": "Bob"}))
        result = load_json(str(path), {})
        assert result == {"callsign": "WSLZ233", "name": "Bob"}

    def test_valid_list_payload(self, tmp_path):
        path = tmp_path / "list.json"
        path.write_text(json.dumps([{"callsign": "ALL"}, {"callsign": "WSLZ233"}]))
        result = load_json(str(path), [])
        assert result == [{"callsign": "ALL"}, {"callsign": "WSLZ233"}]


class TestSaveJson:
    def test_round_trips_dict(self, tmp_path):
        path = tmp_path / "out.json"
        save_json(str(path), {"key": "value"})
        assert json.loads(path.read_text()) == {"key": "value"}

    def test_round_trips_list(self, tmp_path):
        path = tmp_path / "out.json"
        save_json(str(path), [{"callsign": "WSLZ233"}])
        assert json.loads(path.read_text()) == [{"callsign": "WSLZ233"}]

    def test_pretty_printed_with_indent(self, tmp_path):
        # 4-space indent is part of the on-disk format; users hand-edit these files.
        path = tmp_path / "out.json"
        save_json(str(path), {"a": 1})
        assert "    " in path.read_text()

    def test_save_then_load_round_trip(self, tmp_path):
        path = tmp_path / "round.json"
        payload = {"callsign": "WSLZ233", "name": "Bob", "vad_threshold": 0.5}
        save_json(str(path), payload)
        assert load_json(str(path), {}) == payload
