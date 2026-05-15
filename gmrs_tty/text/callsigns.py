import re

from gmrs_tty.text.phonetics import (
    collapse_single_char_runs,
    convert_phonetics,
    join_letters_and_digits,
)

# Callsign formats we detect:
#   - GMRS modern:  W + 3 letters + 3 digits         (WSLZ233)
#   - GMRS legacy:  KA + 1 letter + 3-4 digits       (KAE1234)
#   - US amateur:   1-2 letters (A/K/N/W prefix) +
#                   1 digit + 1-3 letters            (K1ABC, KD9XYZ, W1AW)
CALLSIGN_RE = re.compile(
    r'\b(W[A-Z]{3}\d{3}|KA[A-Z]\d{3,4}|[AKNW][A-Z]?\d[A-Z]{1,3})\b',
    re.IGNORECASE,
)

LETTER_TO_NATO = {
    "A": "Alpha", "B": "Bravo", "C": "Charlie", "D": "Delta",
    "E": "Echo", "F": "Foxtrot", "G": "Golf", "H": "Hotel",
    "I": "India", "J": "Juliet", "K": "Kilo", "L": "Lima",
    "M": "Mike", "N": "November", "O": "Oscar", "P": "Papa",
    "Q": "Quebec", "R": "Romeo", "S": "Sierra", "T": "Tango",
    "U": "Uniform", "V": "Victor", "W": "Whiskey", "X": "X-ray",
    "Y": "Yankee", "Z": "Zulu",
}


def detect_callsigns(text):
    """Return uppercased GMRS callsigns found in raw or phonetic/spaced forms.
    Handles separators: whitespace, hyphens, and periods between letters/digits."""
    if not text:
        return []
    found = set()
    phonetic = convert_phonetics(text)
    variants = [
        text,
        join_letters_and_digits(text),
        collapse_single_char_runs(text),
        join_letters_and_digits(collapse_single_char_runs(text)),
        collapse_single_char_runs(phonetic),
        join_letters_and_digits(phonetic),
        join_letters_and_digits(collapse_single_char_runs(phonetic)),
    ]
    for variant in variants:
        for m in CALLSIGN_RE.finditer(variant):
            found.add(m.group(1).upper())
    return sorted(found)


def callsign_to_nato(callsign):
    """'WSLZ233' -> 'Whiskey Sierra Lima Zulu 2 3 3'. Letters become NATO words,
    digits stay individual."""
    parts = []
    for ch in callsign.upper():
        if ch in LETTER_TO_NATO:
            parts.append(LETTER_TO_NATO[ch])
        elif ch.isdigit():
            parts.append(ch)
    return ' '.join(parts)


def spell_digits_in_callsigns(text):
    """Insert spaces around every digit in any detected callsign so TTS reads
    them one at a time. 'WSLZ233' -> 'WSLZ 2 3 3', 'K1ABC' -> 'K 1 ABC'.
    Amateur callsigns have a digit between letter groups, so we tokenize on
    letter-runs vs. individual digits rather than assuming a single prefix."""
    def repl(m):
        cs = m.group(1)
        tokens = re.findall(r'[A-Za-z]+|\d', cs)
        return ' '.join(tokens)

    return CALLSIGN_RE.sub(repl, text)
