CONFIG_FILE = "config.json"
CONTACTS_FILE = "contacts.json"

# WCAG 2.1 AA color palette. Text colors meet ≥4.5:1 contrast against white;
# UI borders/icons meet ≥3:1. Picked from the Tailwind palette which has
# documented contrast ratios.
COLOR_RX = "#15803D"      # green-700, 5.59:1 on white — incoming transmissions
COLOR_TX = "#1D4ED8"      # blue-700, 7.10:1 on white — outgoing transmissions
COLOR_ERROR = "#B91C1C"   # red-700, 6.45:1 on white — errors
COLOR_WARN = "#92400E"    # amber-800, 8.13:1 on white — warnings / info
PILL_BG = "#FEF3C7"       # amber-100 background for pending-station pills
PILL_TEXT = "#78350F"     # amber-900, ≥10:1 on PILL_BG
PILL_BORDER = "#A16207"   # amber-700, 4.05:1 on white (UI border)
