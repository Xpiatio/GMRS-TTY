import csv
import json

import pytest

from gmrs_tty.persistence.contacts_io import (
    export_contacts_csv,
    export_contacts_json,
    import_contacts_csv,
    import_contacts_json,
    merge_contacts,
)

_FULL = [
    {"callsign": "ALL", "name": "Everyone"},
    {
        "callsign": "WSLZ100",
        "name": "Alice",
        "location": "Hill Top",
        "verified": True,
        "verified_at": "2026-05-23T00:00:00Z",
    },
    {
        "callsign": "KAE1234",
        "name": "Bob",
        "gmrs_callsign": "KAE1234",
        "ham_callsign": "K1BOB",
    },
]


class TestExportImportJson:
    def test_round_trip_preserves_all_fields(self, tmp_path):
        path = str(tmp_path / "contacts.json")
        export_contacts_json(_FULL, path)
        loaded = import_contacts_json(path)
        assert loaded == _FULL

    def test_export_writes_valid_json_list(self, tmp_path):
        path = str(tmp_path / "contacts.json")
        export_contacts_json(_FULL, path)
        with open(path) as fh:
            data = json.load(fh)
        assert isinstance(data, list)
        assert len(data) == len(_FULL)

    def test_import_skips_entries_without_callsign(self, tmp_path):
        path = str(tmp_path / "contacts.json")
        with open(path, "w") as fh:
            json.dump([{"callsign": "WSLZ100"}, {"name": "No callsign"}, {}], fh)
        loaded = import_contacts_json(path)
        assert len(loaded) == 1
        assert loaded[0]["callsign"] == "WSLZ100"

    def test_import_normalizes_callsign_uppercase(self, tmp_path):
        path = str(tmp_path / "contacts.json")
        with open(path, "w") as fh:
            json.dump([{"callsign": "wslz100", "name": "Alice"}], fh)
        loaded = import_contacts_json(path)
        assert loaded[0]["callsign"] == "WSLZ100"

    def test_import_raises_for_non_list_json(self, tmp_path):
        path = str(tmp_path / "contacts.json")
        with open(path, "w") as fh:
            json.dump({"callsign": "WSLZ100"}, fh)
        with pytest.raises(ValueError, match="list"):
            import_contacts_json(path)


class TestExportImportCsv:
    def test_round_trip_preserves_editable_fields(self, tmp_path):
        path = str(tmp_path / "contacts.csv")
        contacts = [
            {
                "callsign": "WSLZ100",
                "name": "Alice",
                "location": "Hill Top",
                "gmrs_callsign": "WSLZ100",
                "ham_callsign": "K1ABC",
            }
        ]
        export_contacts_csv(contacts, path)
        loaded = import_contacts_csv(path)
        assert len(loaded) == 1
        c = loaded[0]
        assert c["callsign"] == "WSLZ100"
        assert c["name"] == "Alice"
        assert c["location"] == "Hill Top"
        assert c["gmrs_callsign"] == "WSLZ100"
        assert c["ham_callsign"] == "K1ABC"

    def test_export_omits_metadata_fields(self, tmp_path):
        path = str(tmp_path / "contacts.csv")
        contacts = [
            {
                "callsign": "WSLZ100",
                "name": "Alice",
                "verified": True,
                "verified_at": "2026-05-23T00:00:00Z",
            }
        ]
        export_contacts_csv(contacts, path)
        with open(path, newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert "verified" not in rows[0]
        assert "verified_at" not in rows[0]

    def test_import_normalizes_callsign_uppercase(self, tmp_path):
        path = str(tmp_path / "contacts.csv")
        with open(path, "w", newline="") as fh:
            csv.DictWriter(fh, fieldnames=["callsign", "name"]).writeheader()
            csv.DictWriter(fh, fieldnames=["callsign", "name"]).writerow(
                {"callsign": "wslz100", "name": "Alice"}
            )
        loaded = import_contacts_csv(path)
        assert loaded[0]["callsign"] == "WSLZ100"

    def test_import_skips_empty_callsign_rows(self, tmp_path):
        path = str(tmp_path / "contacts.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["callsign", "name"])
            w.writeheader()
            w.writerow({"callsign": "", "name": "Nobody"})
            w.writerow({"callsign": "WSLZ100", "name": "Alice"})
        loaded = import_contacts_csv(path)
        assert len(loaded) == 1
        assert loaded[0]["callsign"] == "WSLZ100"

    def test_import_omits_blank_optional_fields(self, tmp_path):
        path = str(tmp_path / "contacts.csv")
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["callsign", "name", "location"])
            w.writeheader()
            w.writerow({"callsign": "WSLZ100", "name": "Alice", "location": ""})
        loaded = import_contacts_csv(path)
        assert "location" not in loaded[0]


class TestMergeContacts:
    def test_empty_existing_returns_all_incoming(self):
        incoming = [{"callsign": "WSLZ100", "name": "Alice"}]
        result = merge_contacts([], incoming)
        assert len(result) == 1
        assert result[0]["callsign"] == "WSLZ100"

    def test_empty_incoming_returns_existing_unchanged(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        result = merge_contacts(existing, [])
        assert result == existing

    def test_new_callsign_appended(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        incoming = [{"callsign": "KAE1234", "name": "Bob"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 2
        assert result[1]["callsign"] == "KAE1234"

    def test_matching_key_updates_fields(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice", "location": ""}]
        incoming = [{"callsign": "WSLZ100", "name": "Alice", "location": "Hill Top"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 1
        assert result[0]["location"] == "Hill Top"

    def test_matching_key_preserves_metadata_absent_from_incoming(self):
        existing = [
            {
                "callsign": "WSLZ100",
                "name": "Alice",
                "verified": True,
                "verified_at": "2026-05-23T00:00:00Z",
            }
        ]
        incoming = [{"callsign": "WSLZ100", "name": "Alice", "location": "Hill Top"}]
        result = merge_contacts(existing, incoming)
        assert result[0]["verified"] is True
        assert result[0]["verified_at"] == "2026-05-23T00:00:00Z"
        assert result[0]["location"] == "Hill Top"

    def test_same_callsign_different_name_adds_new_row(self):
        # Family members share a callsign but have different names.
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        incoming = [{"callsign": "WSLZ100", "name": "Bob"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 2

    def test_case_insensitive_callsign_match(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        incoming = [{"callsign": "wslz100", "name": "Alice", "location": "Hill Top"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 1
        assert result[0]["location"] == "Hill Top"

    def test_case_insensitive_name_match(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        incoming = [{"callsign": "WSLZ100", "name": "alice", "location": "Hill Top"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 1

    def test_all_entry_preserved_when_not_in_incoming(self):
        existing = [
            {"callsign": "ALL", "name": "Everyone"},
            {"callsign": "WSLZ100", "name": "Alice"},
        ]
        incoming = [{"callsign": "KAE1234", "name": "Bob"}]
        result = merge_contacts(existing, incoming)
        assert any(c["callsign"] == "ALL" for c in result)

    def test_blank_incoming_fields_do_not_overwrite_existing(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice", "location": "Hill Top"}]
        # incoming has no 'location' key — should not erase the existing value
        incoming = [{"callsign": "WSLZ100", "name": "Alice"}]
        result = merge_contacts(existing, incoming)
        assert result[0]["location"] == "Hill Top"

    def test_preserves_order_existing_then_new(self):
        existing = [
            {"callsign": "WSLZ100", "name": "Alice"},
            {"callsign": "KAE1234", "name": "Bob"},
        ]
        incoming = [{"callsign": "ZZZ999", "name": "Carol"}]
        result = merge_contacts(existing, incoming)
        assert [r["callsign"] for r in result] == ["WSLZ100", "KAE1234", "ZZZ999"]

    def test_incoming_empty_callsign_skipped(self):
        existing = [{"callsign": "WSLZ100", "name": "Alice"}]
        incoming = [{"callsign": "", "name": "Ghost"}]
        result = merge_contacts(existing, incoming)
        assert len(result) == 1
