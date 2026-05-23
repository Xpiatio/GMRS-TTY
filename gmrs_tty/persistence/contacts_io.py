import csv
import json

from gmrs_tty.persistence.contacts import ContactDict, normalize_callsign

_CSV_FIELDS = ("callsign", "name", "location", "gmrs_callsign", "ham_callsign")


def export_contacts_json(contacts: list[ContactDict], path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(contacts, fh, indent=4, ensure_ascii=False)


def export_contacts_csv(contacts: list[ContactDict], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for contact in contacts:
            writer.writerow({f: contact.get(f, "") for f in _CSV_FIELDS})


def import_contacts_json(path: str) -> list[ContactDict]:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError("JSON file must contain a list of contacts")
    result = []
    for c in data:
        if not isinstance(c, dict) or not c.get("callsign"):
            continue
        c = dict(c)
        c["callsign"] = normalize_callsign(c["callsign"])
        result.append(c)
    return result


def import_contacts_csv(path: str) -> list[ContactDict]:
    contacts = []
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cs = normalize_callsign(row.get("callsign", ""))
            if not cs:
                continue
            contact: ContactDict = {"callsign": cs}
            for field in ("name", "location", "gmrs_callsign", "ham_callsign"):
                val = (row.get(field) or "").strip()
                if val:
                    contact[field] = val
            contacts.append(contact)
    return contacts


def merge_contacts(
    existing: list[ContactDict], incoming: list[ContactDict]
) -> list[ContactDict]:
    """Merge `incoming` into `existing`, keyed by (uppercase callsign, lowercased name).

    When a key matches, non-empty fields from `incoming` overwrite the existing
    entry; metadata absent from `incoming` (e.g. verified/verified_at on a CSV
    import) is left untouched. New keys are appended after existing entries.
    """
    by_key: dict[tuple[str, str], ContactDict] = {}
    key_order: list[tuple[str, str]] = []

    for c in existing:
        key = _contact_key(c)
        if key not in by_key:
            key_order.append(key)
            by_key[key] = dict(c)

    for contact in incoming:
        cs = normalize_callsign(contact.get("callsign", ""))
        if not cs:
            continue
        key = _contact_key(contact)
        if key in by_key:
            for k, v in contact.items():
                if v is not None and v != "":
                    by_key[key][k] = v
        else:
            key_order.append(key)
            by_key[key] = dict(contact)

    return [by_key[k] for k in key_order]


def _contact_key(c: ContactDict) -> tuple[str, str]:
    return (
        normalize_callsign(c.get("callsign", "")),
        (c.get("name") or "").strip().lower(),
    )
