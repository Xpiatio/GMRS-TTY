import re

LOCATION_RE = re.compile(
    r'\b(?:in|from|near|at)\s+([A-Z][a-z]+(?:[\s,]+[A-Z][a-z]+){0,3})',
)


def extract_name_location(text, callsign):
    """Heuristic: name is the first capitalized word after the callsign mention;
    location is the capitalized phrase after 'in/from/near/at' anywhere in the text."""
    name = ""
    location = ""
    upper = text.upper()
    idx = upper.find(callsign)
    if idx >= 0:
        after = text[idx + len(callsign):].lstrip(",.;: \t")
        name_match = re.match(r'([A-Z][a-z]+)', after)
        if name_match:
            name = name_match.group(1)
    loc_match = LOCATION_RE.search(text)
    if loc_match:
        location = loc_match.group(1).strip(" ,")
    return name, location
