import re

# TTY/TDD shorthand from the Corada TDD/TTY Etiquette Glossary. Expanded into
# full words before Piper TTS so the receiver hears "Go ahead" instead of "G A".
TTY_ABBREVIATIONS = {
    # Universal terms
    "GA TO SK": "Completing messages and getting ready to hang up",
    "SKSK":     "Hanging up",
    "GA":       "Go ahead",
    "SK":       "Stop keying",
    "TDD":      "Telecommunications Device for the Deaf",
    "TTY":      "Teletypewriter",
    "XXXX":     "Erasing the error",
    "Q":        "Question mark",
    # Common terms
    "ASAP": "As soon as possible",
    "ASST": "Assistant",
    "BIZ":  "Business",
    "BYE":  "Goodbye",
    "CD":   "Could",
    "CLD":  "Could",
    "CUL":  "See you later",
    "CUZ":  "Because",
    "DR":   "Doctor",
    "FIG":  "Figures",
    "HD":   "Hold",
    "HLD":  "Hold",
    "ILY":  "I love you",
    "IMPT": "Important",
    "INC":  "Incomplete",
    "LTRS": "Letters",
    "MISC": "Miscellaneous",
    "MSG":  "Message",
    "MSGE": "Message",
    "MSGS": "Messages",
    "MTG":  "Meeting",
}

# Sort keys longest-first so "GA TO SK" matches before "GA"/"SK" and "SKSK"
# matches before "SK".
_TTY_ABBREV_PATTERN = re.compile(
    r'\b(' + '|'.join(
        re.escape(k) for k in sorted(TTY_ABBREVIATIONS, key=len, reverse=True)
    ) + r')\b',
    re.IGNORECASE,
)


def expand_tty_abbreviations(text):
    """Replace TTY/TDD shorthand (GA, SKSK, ASAP, ILY, MSG, ...) with the
    full-word form so Piper reads it as prose. Case-insensitive; word-boundary
    matched so 'QSO' won't trigger 'Q' and 'Doctor' won't trigger 'DR'."""
    return _TTY_ABBREV_PATTERN.sub(
        lambda m: TTY_ABBREVIATIONS[m.group(1).upper()],
        text,
    )
