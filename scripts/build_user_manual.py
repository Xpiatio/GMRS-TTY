"""Render the GMRS-TTY user manual to docs/USER_MANUAL.pdf.

Run from the repo root:

    python scripts/build_user_manual.py

The manual content lives in this file so it stays in lockstep with the
codebase — when a UI label or shortcut changes, update the matching string
here and re-run.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate, Frame, KeepTogether, NextPageTemplate, PageBreak,
    PageTemplate, Paragraph, Preformatted, Spacer, Table, TableStyle,
)


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUTPUT_PATH = os.path.join(REPO_ROOT, "docs", "USER_MANUAL.pdf")

sys.path.insert(0, REPO_ROOT)
from gmrs_tty import __version__  # noqa: E402

PRIMARY = colors.HexColor("#1D4ED8")   # TX blue
ACCENT  = colors.HexColor("#15803D")   # RX green
WARN    = colors.HexColor("#92400E")   # amber
ERROR   = colors.HexColor("#B91C1C")   # error red
PILL_BG = colors.HexColor("#FEF3C7")
PILL_BORDER = colors.HexColor("#F59E0B")
CODE_BG = colors.HexColor("#F3F4F6")
RULE    = colors.HexColor("#D1D5DB")
MUTED   = colors.HexColor("#6B7280")


# ---------------------------------------------------------------------------
# Style sheet
# ---------------------------------------------------------------------------

def build_styles():
    base = getSampleStyleSheet()
    styles = {}
    styles["body"] = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica",
        fontSize=10.5, leading=14, spaceAfter=6, alignment=TA_LEFT,
    )
    styles["body_indent"] = ParagraphStyle(
        "body_indent", parent=styles["body"], leftIndent=18,
    )
    styles["h1"] = ParagraphStyle(
        "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=22, leading=26, spaceBefore=0, spaceAfter=12,
        textColor=PRIMARY,
    )
    styles["h2"] = ParagraphStyle(
        "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=15, leading=18, spaceBefore=14, spaceAfter=6,
        textColor=PRIMARY,
    )
    styles["h3"] = ParagraphStyle(
        "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
        fontSize=12, leading=15, spaceBefore=10, spaceAfter=4,
        textColor=colors.black,
    )
    styles["bullet"] = ParagraphStyle(
        "bullet", parent=styles["body"], leftIndent=18, bulletIndent=6,
        spaceAfter=3,
    )
    styles["sub_bullet"] = ParagraphStyle(
        "sub_bullet", parent=styles["body"], leftIndent=34, bulletIndent=22,
        spaceAfter=2,
    )
    styles["code"] = ParagraphStyle(
        "code", parent=base["Code"], fontName="Courier",
        fontSize=9.2, leading=12, leftIndent=10, rightIndent=10,
        spaceBefore=6, spaceAfter=8, backColor=CODE_BG,
        borderColor=RULE, borderWidth=0.5, borderPadding=6,
    )
    styles["callout"] = ParagraphStyle(
        "callout", parent=styles["body"], leftIndent=10, rightIndent=10,
        spaceBefore=6, spaceAfter=8, backColor=PILL_BG,
        borderColor=PILL_BORDER, borderWidth=0.7, borderPadding=8,
        textColor=colors.HexColor("#78350F"),
    )
    styles["note"] = ParagraphStyle(
        "note", parent=styles["body"], leftIndent=10, rightIndent=10,
        spaceBefore=6, spaceAfter=8,
        backColor=colors.HexColor("#EFF6FF"),
        borderColor=colors.HexColor("#93C5FD"), borderWidth=0.7,
        borderPadding=8, textColor=colors.HexColor("#1E3A8A"),
    )
    styles["warning"] = ParagraphStyle(
        "warning", parent=styles["body"], leftIndent=10, rightIndent=10,
        spaceBefore=6, spaceAfter=8,
        backColor=colors.HexColor("#FEE2E2"),
        borderColor=ERROR, borderWidth=0.7, borderPadding=8,
        textColor=colors.HexColor("#7F1D1D"),
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=42, leading=48, alignment=TA_CENTER, textColor=PRIMARY,
        spaceAfter=12,
    )
    styles["cover_subtitle"] = ParagraphStyle(
        "cover_subtitle", parent=base["BodyText"], fontName="Helvetica",
        fontSize=16, leading=22, alignment=TA_CENTER, textColor=MUTED,
        spaceAfter=18,
    )
    styles["cover_blurb"] = ParagraphStyle(
        "cover_blurb", parent=base["BodyText"], fontName="Helvetica",
        fontSize=12, leading=18, alignment=TA_CENTER,
        textColor=colors.black, spaceAfter=8,
    )
    styles["caption"] = ParagraphStyle(
        "caption", parent=styles["body"], fontSize=9, textColor=MUTED,
        leading=11, spaceAfter=10,
    )
    styles["toc_entry"] = ParagraphStyle(
        "toc_entry", parent=styles["body"], leftIndent=0, fontSize=11,
        leading=15, spaceAfter=2,
    )
    return styles


# ---------------------------------------------------------------------------
# Page templates with header / footer / page numbers
# ---------------------------------------------------------------------------

def _draw_chrome(canvas, doc):
    canvas.saveState()
    page = canvas.getPageNumber()
    if page == 1:
        canvas.restoreState()
        return
    width, height = LETTER
    canvas.setFont("Helvetica", 8.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(0.75 * inch, height - 0.55 * inch, "GMRS-TTY — User Manual")
    canvas.drawRightString(width - 0.75 * inch, height - 0.55 * inch,
                           "Full reference")
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.4)
    canvas.line(0.75 * inch, height - 0.62 * inch,
                width - 0.75 * inch, height - 0.62 * inch)
    canvas.drawCentredString(width / 2.0, 0.5 * inch, f"— {page} —")
    canvas.restoreState()


def make_doc(path):
    doc = BaseDocTemplate(
        path, pagesize=LETTER,
        leftMargin=0.85 * inch, rightMargin=0.85 * inch,
        topMargin=0.9 * inch, bottomMargin=0.85 * inch,
        title="GMRS-TTY User Manual",
        author="GMRS-TTY",
        subject="GMRS-TTY desktop application reference manual",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="main")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame]),
        PageTemplate(id="body", frames=[frame], onPage=_draw_chrome),
    ])
    return doc


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------

@dataclass
class Builder:
    styles: dict
    flow: list

    def add(self, item):
        self.flow.append(item)

    def h1(self, text):
        self.add(Paragraph(text, self.styles["h1"]))

    def h2(self, text):
        self.add(Paragraph(text, self.styles["h2"]))

    def h3(self, text):
        self.add(Paragraph(text, self.styles["h3"]))

    def p(self, text):
        self.add(Paragraph(text, self.styles["body"]))

    def indent(self, text):
        self.add(Paragraph(text, self.styles["body_indent"]))

    def bullets(self, items, style="bullet"):
        for item in items:
            if isinstance(item, tuple):
                lead, body = item
                self.add(Paragraph(f"<b>{lead}</b> — {body}",
                                   self.styles[style], bulletText="•"))
            else:
                self.add(Paragraph(item, self.styles[style],
                                   bulletText="•"))

    def sub_bullets(self, items):
        self.bullets(items, style="sub_bullet")

    def code(self, text):
        self.add(Preformatted(text, self.styles["code"]))

    def callout(self, text):
        self.add(Paragraph(text, self.styles["callout"]))

    def note(self, text):
        self.add(Paragraph(text, self.styles["note"]))

    def warn(self, text):
        self.add(Paragraph(text, self.styles["warning"]))

    def spacer(self, amount=8):
        self.add(Spacer(1, amount))

    def page_break(self):
        self.add(PageBreak())

    def table(self, header, rows, col_widths=None, body_align="LEFT"):
        # Wrap every cell in a Paragraph so reportlab word-wraps inside the
        # cell width. Raw strings would otherwise overflow the column.
        cell_style = ParagraphStyle(
            "tbl_cell", parent=self.styles["body"],
            fontSize=9.2, leading=11.5, spaceAfter=0,
        )
        header_style = ParagraphStyle(
            "tbl_head", parent=cell_style,
            fontName="Helvetica-Bold", textColor=colors.white,
        )

        def wrap(value, style):
            return value if hasattr(value, "wrap") else Paragraph(str(value), style)

        wrapped_header = [wrap(h, header_style) for h in header]
        wrapped_rows = [[wrap(c, cell_style) for c in row] for row in rows]
        data = [wrapped_header] + wrapped_rows
        tbl = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PRIMARY),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
            ("TOPPADDING",    (0, 0), (-1, 0), 6),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
            ("TOPPADDING",    (0, 1), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ALIGN",  (0, 1), (-1, -1), body_align),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F9FAFB")]),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
            ("LINEBELOW", (0, -1), (-1, -1), 0.5, RULE),
            ("BOX", (0, 0), (-1, -1), 0.5, RULE),
        ]))
        self.add(KeepTogether(tbl))
        self.spacer(8)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

def build_cover(b: Builder):
    b.add(Spacer(1, 1.6 * inch))
    b.add(Paragraph("GMRS-TTY", b.styles["cover_title"]))
    b.add(Paragraph("User Manual &mdash; Full Reference",
                    b.styles["cover_subtitle"]))
    b.add(Paragraph(f"Version v{__version__}", b.styles["cover_subtitle"]))
    b.add(Spacer(1, 0.4 * inch))
    b.add(Paragraph(
        "A TTY-style accessibility communicator for the General Mobile "
        "Radio Service (GMRS) and Family Radio Service (FRS), built for "
        "deaf, hard-of-hearing, and mute operators.",
        b.styles["cover_blurb"]))
    b.add(Spacer(1, 0.25 * inch))
    b.add(Paragraph("Live transcription &middot; offline TTS &middot; "
                    "FCC Part 95 ID rules built in",
                    b.styles["cover_blurb"]))
    b.add(Spacer(1, 1.2 * inch))
    b.add(Paragraph(
        "<i>Read the keyboard-shortcut reference on page 4 if you want "
        "to skip the tour and start operating immediately.</i>",
        b.styles["caption"]))


def build_toc(b: Builder):
    b.h1("Contents")
    entries = [
        ("1.",  "About this manual"),
        ("2.",  "System requirements"),
        ("3.",  "Installation — pre-built packages &amp; from source"),
        ("4.",  "First run &amp; configuration"),
        ("5.",  "Main window tour"),
        ("5.11.", "Session Journals"),
        ("5.12.", "Touch-screen mode"),
        ("6.",  "Configuration dialog"),
        ("7.",  "Contacts dialog"),
        ("8.",  "Quick Messages dialog"),
        ("9.",  "Add Station dialog"),
        ("10.", "Keyboard shortcuts &amp; mnemonics"),
        ("11.", "GMRS vs FRS service mode"),
        ("12.", "PTT (Push-to-Talk) modes"),
        ("13.", "Receive (Rx) pipeline"),
        ("14.", "Transmit (Tx) pipeline"),
        ("15.", "Callsign detection &amp; FCC verification"),
        ("16.", "FCC Part 95 compliance features"),
        ("17.", "Accessibility (WCAG 2.1 AA)"),
        ("18.", "Off-grid operation"),
        ("19.", "Troubleshooting"),
        ("20.", "File reference (config.json, contacts.json)"),
        ("21.", "Glossary"),
    ]
    for num, title in entries:
        b.add(Paragraph(f"<b>{num}</b>&nbsp;&nbsp;{title}",
                        b.styles["toc_entry"]))


def build_about(b: Builder):
    b.h1("1. About this manual")
    b.p("This manual is the full operating reference for GMRS-TTY, a "
        "cross-platform desktop application that lets deaf, hard-of-hearing, "
        "and mute operators participate in two-way voice radio conversations "
        "over GMRS and FRS. The program is written in Python with PySide6, "
        "runs fully offline once installed, and ships every feature behind "
        "the FCC Part 95 rule set so operators can stay legal without "
        "memorizing the regulations.")
    b.p("The manual is organized as a reference rather than a tutorial. "
        "Section 5 walks every region of the main window in "
        "top-to-bottom order. Sections 6–9 document each dialog. "
        "Section 10 is the keyboard cheat sheet. Sections 11–16 cover "
        "the deeper behaviors (service mode, PTT modes, the audio "
        "pipelines, callsign verification, and FCC compliance). "
        "Section 19 is troubleshooting. Sections 20–21 give the "
        "on-disk file formats and a glossary.")
    b.callout(
        "<b>If you only have five minutes (pre-built installer):</b> "
        "install the <font face=\"Courier\">.deb</font> or "
        "<font face=\"Courier\">.msi</font> (section 3.1), drop one "
        "Piper voice into the "
        "<font face=\"Courier\">Voices/</font> subdirectory of the "
        "install folder, then launch GMRS-TTY and open "
        "<b>Settings &rarr; Configuration</b> to set your callsign and "
        "pick the voice. Press <b>Alt+L</b> to listen and type into the "
        "message box to transmit. "
        "<b>From source:</b> follow section 3.2 (clone, pip install, "
        "bootstrap_models.py, run)."
    )


def build_requirements(b: Builder):
    b.h1("2. System requirements")
    b.h3("Operating system")
    b.bullets([
        ("Linux", "Debian 12+, Ubuntu 22.04+, Raspberry Pi OS (Bookworm). "
                  "PortAudio dev libs required: "
                  "<font face=\"Courier\">sudo apt install libportaudio2 "
                  "portaudio19-dev</font>. On PipeWire/PulseAudio systems "
                  "also install "
                  "<font face=\"Courier\">pulseaudio-utils</font> "
                  "(<font face=\"Courier\">sudo apt install "
                  "pulseaudio-utils</font>) — provides "
                  "<font face=\"Courier\">parec</font> and "
                  "<font face=\"Courier\">pactl</font>, used for both "
                  "microphone capture (preferred over PortAudio's "
                  "PipeWire-via-ALSA bridge, which can silently deliver "
                  "flat-zero audio on PipeWire 1.4) and System Audio Output "
                  "(loopback) mode. Without it the app falls back to "
                  "PortAudio for mic capture; loopback mode requires it."),
        ("Windows", "Windows 10 or 11. PortAudio ships in the wheel; no "
                    "extra system libraries needed."),
        ("macOS", "Not formally targeted, but Python 3.11+ with PortAudio "
                  "available through Homebrew usually works."),
    ])
    b.h3("Hardware")
    b.bullets([
        ("Microphone", "Anything Linux/Windows recognizes — a USB "
                       "headset, the built-in laptop mic, or a sound-card "
                       "channel cabled from your radio's speaker output."),
        ("Speaker / radio audio path", "A speaker for live listening, or a "
                                       "USB sound card / Signalink / Digirig "
                                       "for feeding TTS audio directly into "
                                       "your radio."),
        ("Optional: PTT cable", "A USB-serial adapter (FTDI is the most "
                                "common) for keying PTT via RTS/DTR. Not "
                                "needed if your radio has VOX or you key "
                                "manually."),
    ])
    b.h3("Software")
    b.bullets([
        ("<b>Pre-built installers</b> (section 3.1)", "No Python or pip "
         "required — Python 3.13, all dependencies, and the offline STT "
         "models are bundled. ~1.5 GB disk for the installer and installed "
         "footprint."),
        ("<b>From source</b> (section 3.2+)", "Python 3.11 or newer "
         "(3.13 recommended). ~1 GB free disk for Python dependencies plus "
         "75&ndash;150 MB for the Whisper STT model. Internet access once "
         "to install pip packages and fetch the model; the core radio "
         "workflow needs no network after that."),
    ])


def build_install(b: Builder):
    b.h1("3. Installation")

    # ---- Pre-built installers ------------------------------------------ #
    b.h2("3.1 Pre-built installers (recommended for end users)")
    b.p("The pre-built installers bundle Python 3.13, all Python packages "
        "(CPU-only PyTorch, faster-whisper, PySide6, Piper, Silero VAD, "
        "and their dependencies), and the offline Whisper STT + speaker "
        "identification models. No Python installation or internet access "
        "is needed after downloading the installer.")
    b.note(
        "Piper TTS <i>voice</i> models are <b>not</b> bundled — they "
        "are large, numerous, and user-chosen. Add them after install "
        "(see section 3.1.3 below)."
    )

    b.h3("3.1.1 Debian / Ubuntu (.deb)")
    b.p("Targets Debian 13 / Ubuntu 24.04+ on x86-64. System "
        "dependencies installed automatically by apt.")
    b.code(
        "sudo apt install ./gmrs-tty_0.0.1_amd64.deb\n"
        "gmrs-tty"
    )
    b.p("The package installer (postinst) creates a Python virtual "
        "environment at "
        "<font face=\"Courier\">/opt/gmrs-tty/.venv</font>, installs "
        "all bundled wheels offline, and seeds an initial "
        "<font face=\"Courier\">config.json</font> from the example. "
        "Open <b>Settings &rarr; Configuration</b> on first launch to "
        "set your callsign, name, location, and Piper TTS voice.")
    b.bullets([
        ("Install location", "<font face=\"Courier\">/opt/gmrs-tty/"
                             "</font> — writable by all users so the "
                             "app can persist "
                             "<font face=\"Courier\">config.json</font> "
                             "and "
                             "<font face=\"Courier\">contacts.json"
                             "</font> in-place."),
        ("Launcher", "<font face=\"Courier\">/usr/bin/gmrs-tty</font> "
                     "— runnable from a terminal or the desktop shortcut "
                     "created at install time."),
        ("Uninstall", "<font face=\"Courier\">sudo apt remove gmrs-tty"
                      "</font>. The venv and any locally-staged Piper "
                      "voices under "
                      "<font face=\"Courier\">/opt/gmrs-tty/Voices/"
                      "</font> are preserved; only the package files "
                      "are removed."),
    ])

    b.h3("3.1.2 Windows (.msi)")
    b.p("Bundles Python 3.13 embeddable runtime. No separate Python "
        "installation required. Installs to "
        "<font face=\"Courier\">C:\\Program Files\\GMRS-TTY\\"
        "</font> by default.")
    b.bullets([
        "Run the <font face=\"Courier\">gmrs-tty_0.0.1_x64.msi</font> "
        "installer and step through the wizard.",
        "A <b>GMRS-TTY</b> shortcut is added to the Desktop and Start "
        "Menu, pointing at the bundled "
        "<font face=\"Courier\">python\\pythonw.exe main.py</font>.",
        "Open <b>Settings &rarr; Configuration</b> on first launch.",
        "Uninstall via Windows Settings &rarr; Apps.",
    ])
    b.note(
        "The Windows installer is built by "
        "<font face=\"Courier\">scripts\\build-msi.ps1</font> on a "
        "Windows machine using WiX v4. Source builds are not required "
        "to run the pre-built MSI."
    )

    b.h3("3.1.3 Adding Piper TTS voices")
    b.p("Piper ONNX voices must be added manually after install. Drop "
        "each <font face=\"Courier\">.onnx</font> + "
        "<font face=\"Courier\">.onnx.json</font> pair into the "
        "<font face=\"Courier\">Voices/</font> subfolder of the install "
        "directory:")
    b.code(
        "# Debian / Ubuntu\n"
        "ls /opt/gmrs-tty/Voices/\n\n"
        "# Windows — in Explorer:\n"
        "C:\\Program Files\\GMRS-TTY\\Voices\\"
    )
    b.p("Download voices from: "
        "<font color=\"#1D4ED8\">https://github.com/rhasspy/piper/"
        "blob/master/VOICES.md</font>. Most voices are MIT-licensed; "
        "<font face=\"Courier\">en_US-libritts-high</font> is CC BY 4.0 "
        "and requires attribution if redistributed.")
    b.p("After adding voices, open Configuration and pick one from the "
        "<b>Voice Model</b> dropdown. Click <b>Test</b> to preview "
        "before saving.")

    # ---- From source ------------------------------------------------------ #
    b.h2("3.2 From source (developer / advanced install)")
    b.p("Five steps from a fresh clone to a working radio session.")

    b.h3("3.2.1 Clone and create a virtual environment")
    b.code(
        "git clone <repo-url> GMRS-TTY\n"
        "cd GMRS-TTY\n\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate              # Linux / macOS\n"
        "# .venv\\Scripts\\activate              # Windows\n\n"
        "pip install -r requirements.txt"
    )

    b.h3("3.2.2 Drop in a Piper voice")
    b.p("Download at least one Piper ONNX voice and its matching "
        "<font face=\"Courier\">.json</font> config file into a "
        "<font face=\"Courier\">Voices/</font> directory at the project "
        "root. The Configuration dialog reads this folder at launch and "
        "lists every voice it finds.")
    b.code(
        "Voices/\n"
        "├── en_US-ryan-high.onnx\n"
        "├── en_US-ryan-high.onnx.json\n"
        "├── en_US-amy-medium.onnx\n"
        "└── en_US-amy-medium.onnx.json"
    )

    b.h3("3.2.3 Bootstrap the speech-to-text model")
    b.p("The Whisper STT model is not bundled in the repo. Fetch it once "
        "on an internet-connected machine:")
    b.code(
        "python bootstrap_models.py                       # default: small.en\n"
        "python bootstrap_models.py --model base.en       # smaller, faster, less accurate\n"
        "python bootstrap_models.py --model medium.en     # higher accuracy, slower"
    )
    b.p("This populates "
        "<font face=\"Courier\">Models/STT/&lt;model_name&gt;/</font> with "
        "the faster-whisper CTranslate2 artifacts. The app loads from "
        "there on Listen and never attempts network access — if the "
        "directory is missing, listening fails fast with an instruction "
        "to run the bootstrap.")
    b.note(
        "<b>For air-gapped installs:</b> run the bootstrap once on an "
        "internet-connected machine, then copy the entire "
        "<font face=\"Courier\">Models/</font> directory (alongside the "
        "source) to the offline target. Silero VAD and Piper voices ship "
        "as local files already, so no other fetches are involved."
    )

    b.h3("3.2.4 Configure")
    b.code(
        "cp config.example.json config.json\n"
        "$EDITOR config.json    # set your callsign, name, location, voice"
    )
    b.p("You can also leave the file at its defaults and edit everything "
        "through the in-app Configuration dialog after first launch.")

    b.h3("3.2.5 Run")
    b.code(
        "source .venv/bin/activate\n"
        "python main.py"
    )


def build_first_run(b: Builder):
    b.h1("4. First run &amp; configuration")
    b.p("On first launch the app reads "
        "<font face=\"Courier\">config.json</font> from the working "
        "directory. If your callsign is still "
        "<font face=\"Courier\">YOUR_CALL</font> the header will display "
        "that literal string — open Settings → Configuration "
        "(or click the gear icon on the right side of the service toolbar). "
        "The dialog has six tabs; the minimum fields for a working session are:")
    b.bullets([
        ("<b>Identity tab</b> — Callsign",
         "Your FCC GMRS callsign (e.g. "
         "<font face=\"Courier\">WSLZ233</font>). Saved uppercased."),
        ("Identity — Name",
         "Your operator name. Appears in the callsign preface and "
         "the station-ID button output."),
        ("Identity — Location",
         "Free-form city / state. Used by the standalone "
         "<b>This is</b> ID announcement."),
        ("<b>Audio tab</b> — Input Device",
         "Microphone the Listen button captures from. "
         "<i>System Default</i> works for most setups. "
         "Select <i>System Audio Output (loopback)</i> to "
         "capture whatever is playing through the computer's "
         "speakers — open YouTube in a browser, play a "
         "podcast, or use any media player and the app will "
         "transcribe that audio. When this mode is selected "
         "a <b>Monitor Sink</b> dropdown appears so you can "
         "target a specific output device; "
         "<i>System Default</i> follows your OS default "
         "playback device. No extra tools required."),
        ("Audio — Output Device",
         "Where TTS audio is played — choose a USB "
         "sound card / Signalink / Digirig channel here "
         "to feed your radio directly."),
        ("Audio — VAD Threshold",
         "Silero VAD sensitivity (0.10–0.95). Lower "
         "is more sensitive (catches quiet signals but "
         "more false starts); higher is stricter."),
        ("<b>Voice tab</b> — Voice Model",
         "Pick the Piper voice you dropped into "
         "<font face=\"Courier\">Voices/</font>. Click "
         "<b>Test</b> to hear a sample before committing."),
        ("Voice — Speech Rate",
         "Slider from 0.70× (faster) to 1.50× "
         "(slower); 1.00× is the voice's native pace."),
        ("<b>PTT tab</b> — PTT Mode",
         "Manual, VOX, or USB FTDI / Serial. See section 12."),
        ("<b>Behavior tab</b> — Time Format",
         "24-hour or 12-hour AM/PM timestamps on RX lines."),
        ("Behavior — Filter profanity",
         "On by default. Masks the f/s-words and "
         "similar with asterisks in both RX transcripts "
         "and outgoing TX before TTS speaks them."),
    ])
    b.p("Click <b>OK</b>. The header updates, the dropdown lists the new "
        "voice, and the listener restarts automatically if you changed "
        "the input device or VAD threshold.")
    b.note(
        "Configuration is stored as plain JSON in "
        "<font face=\"Courier\">config.json</font> next to "
        "<font face=\"Courier\">main.py</font>. You can hand-edit it "
        "between runs; the in-app dialog and the file are interchangeable."
    )


def build_main_window(b: Builder):
    b.h1("5. Main window tour")
    b.p("The main window is built on Qt's dockable-panel system: a "
        "movable <b>Service toolbar</b> at the top, a <b>Chat surface</b> "
        "in the center, four rearrangeable docked panels "
        "(<b>Station</b>, <b>Waterfall</b>, <b>Pending Stations</b>, "
        "<b>Quick Messages</b>), and a <b>Transmit</b> panel that stays "
        "pinned to the bottom by default but can also be moved or "
        "floated. The menubar holds Settings + View, and the status bar "
        "carries the live online/offline indicator on its right edge. "
        "The layout (dock positions, sizes, tabs, floats, window "
        "geometry) persists to "
        "<font face=\"Courier\">config.json</font> under "
        "<font face=\"Courier\">ui_layout</font> on close and restores "
        "on the next launch — see section 5.5 for customization details. "
        "Minimum window size is 720×520 to guarantee no clipping at "
        "high-DPI / large-font settings; the default is 960×720.")

    b.h3("5.1 Service toolbar (top by default)")
    b.p("A movable <font face=\"Courier\">QToolBar</font>. Drag the "
        "left-edge handle to relocate it to any of the four toolbar "
        "areas (top, bottom, left, right). Hide via the View menu if "
        "you want to keep service-mode controls keyboard-only.")
    b.bullets([
        ("Service:", "Label."),
        ("GMRS / FRS", "Segmented radio buttons (Alt+G / Alt+F). Choose "
                       "your operating service. The selection persists to "
                       "<font face=\"Courier\">radio_service</font> in "
                       "config.json. See section 11 for the full "
                       "behavior diff."),
        ("Touch toggle (⊞ / ⊟)", "Leftmost icon in the cluster. "
                                "Click ⊞ to enter touch-screen "
                                "mode; click ⊟ to return to the "
                                "desktop layout. In touch mode all "
                                "dock panels hide automatically and "
                                "the central panel switches to a "
                                "large-button view designed for "
                                "finger operation. Persists to "
                                "<font face=\"Courier\">touch_mode"
                                "</font> in config.json. See "
                                "section 5.12 for full details."),
        ("Theme toggle (🌙 / ☀️)", "Moon glyph in light "
                                               "mode, sun glyph in dark "
                                               "mode. Repaints the "
                                               "entire UI instantly: "
                                               "window background, "
                                               "conversation log "
                                               "background and text, "
                                               "header, dock title "
                                               "bars, menus, callsign "
                                               "pills, and status bar. "
                                               "The glyph shows the "
                                               "<i>destination</i> "
                                               "state — a moon means "
                                               "click for dark. "
                                               "Persists in "
                                               "<font face=\"Courier"
                                               "\">dark_mode</font>; "
                                               "stays enabled in both "
                                               "modes."),
        ("Q icon", "Bold capital Q. Opens the Quick Messages editor — "
                   "same destination as Settings → Quick Messages."),
        ("Person icon", "Bust-in-silhouette glyph. Opens Contacts — "
                        "same destination as Settings → Contacts or "
                        "Ctrl+B. Disabled in FRS mode (no callsigns)."),
        ("Notebook icon (📓)", "Opens the Session Journals browser — "
                               "same destination as Tools → View Session "
                               "Journals or Ctrl+Shift+J. Enabled in "
                               "both modes."),
        ("Gear icon", "Cog wheel. Opens Configuration — same "
                      "destination as Settings → Configuration or "
                      "Ctrl+,. Enabled in both modes."),
    ])

    b.h3("5.2 Station panel (dock — Ctrl+Shift+S)")
    b.p("Docked at the top by default. Drag its title bar to move it to "
        "any side of the chat surface, float it as a separate window, or "
        "tab it with another panel. The panel content is a bold strip: "
        "in GMRS mode it reads "
        "<font face=\"Courier\">Station: WSLZ233 | Operator: Benjamin | "
        "Location: Lansing, MI</font>. In FRS mode the station segment "
        "is replaced with <font face=\"Courier\">FRS Mode</font> because "
        "FRS has no callsign requirement.")

    b.h3("5.3 Chat area")
    b.p("A single horizontal <b>Listen strip</b> sits directly above the "
        "conversation log. It lives in the always-visible central widget "
        "rather than in any dock, so the RX controls and the chat they "
        "feed stay reachable independent of which docks are shown, "
        "moved, or floated.")
    b.bullets([
        ("Listen toggle", "Leftmost on the strip. Alt+L or Ctrl+L. "
                          "Starts or stops microphone capture and live "
                          "transcription. Loads the Whisper model from "
                          "<font face=\"Courier\">Models/STT/&lt;model&gt;/"
                          "</font> on first start; subsequent toggles are "
                          "instant. The label flips to <i>Listening…</i> "
                          "while active so the state is visible at a "
                          "glance, and the accessible description updates "
                          "for screen readers."),
        ("Listen only (RX-only safety)", "Sits immediately right of the "
                          "Listen toggle. Mnemonic Alt+O. Checkable: when "
                          "on, every TX path is blocked — Transmit, "
                          "<b>This is</b>, Enter-to-send in the message "
                          "box, the quick-message preset buttons, and the "
                          "Ctrl+Return / Ctrl+I / Alt+1…Alt+9 global "
                          "shortcuts all refuse to fire (the buttons grey "
                          "out so the gate is visible). Microphone "
                          "capture, transcription, callsign detection, "
                          "callsigns detected, and the chat surface keep working "
                          "normally. Persists to "
                          "<font face=\"Courier\">config.json</font> "
                          "under <font face=\"Courier\">listen_only"
                          "</font>, so an operator who finishes a session "
                          "in RX-only mode comes back up the same way. "
                          "Toggling back off re-enables transmission "
                          "instantly — and simultaneously disables the "
                          "Monitor toggle (see below)."),
        ("Monitor (audio monitor)", "Sits to the right of the Listen only "
                          "toggle, separated by a small gap that signals "
                          "it is a conditional sub-tool. Mnemonic Alt+M. "
                          "Checkable: when on, incoming radio audio is "
                          "routed unfiltered to the configured output "
                          "device in real-time — only the "
                          "16&nbsp;kHz&nbsp;&rarr;&nbsp;48&nbsp;kHz "
                          "polyphase upsample is applied — so the "
                          "operator hears the raw channel through "
                          "speakers while the app simultaneously "
                          "transcribes it. Transcription is not "
                          "affected. <b>Available only when Listen-only "
                          "mode is active</b> — enabling Monitor on a "
                          "channel where transmissions are possible would "
                          "risk audio feedback through the radio mic, so "
                          "the button is greyed out whenever Listen only "
                          "is off. When Listen-only is turned off the "
                          "monitor stream stops automatically. Persists "
                          "to <font face=\"Courier\">config.json</font> "
                          "under <font face=\"Courier\">monitor_enabled"
                          "</font>. A power-on default is also "
                          "configurable from <b>Settings &rarr; "
                          "Configuration &rarr; Monitor audio</b>."),
        ("Live input-level meter", "Thin horizontal bar stretching across "
                                   "the middle of the strip — real-time "
                                   "peak amplitude of the captured audio. "
                                   "Use it to verify your mic / cable / "
                                   "device is wired up; if it stays at "
                                   "zero while you key audio into the "
                                   "radio, the app isn't getting audio. "
                                   "Stays at zero when Listen is off."),
        ("Clear chat button", "Right-aligned on the strip. Ctrl+K "
                              "from anywhere, or Tools &rarr; Clear Chat "
                              "from the menu. Asks for Yes/No confirmation "
                              "then wipes the log. Chat history is "
                              "in-memory only — it cannot be recovered "
                              "once cleared."),
        ("Conversation log", "Timestamped messages. Incoming lines are "
                             "green <font face=\"Courier\">[RX HH:MM:SS]:"
                             "</font>. Outgoing lines are blue "
                             "<font face=\"Courier\">[TX to &lt;target&gt;]:"
                             "</font>. Errors say <font face=\"Courier\">"
                             "Error:</font> or <font face=\"Courier\">"
                             "Failed:</font> in the text — state is "
                             "never carried by color alone."),
        ("Auto-tail", "New messages keep the viewport pinned to the "
                      "bottom while you're caught up. Scroll up to "
                      "re-read older context and incoming traffic will "
                      "<i>not</i> yank you back."),
        ("Callsign pills", "Any callsign that matches a saved contact is "
                           "rendered with an amber, bold pill background. "
                           "Hover for every operator linked to that "
                           "callsign — useful for family-shared GMRS "
                           "calls. A green ✓ appears immediately "
                           "after the callsign when the contact has a "
                           "confirmed FCC license match (hover the check "
                           "for the FCC license verified tooltip)."),
    ])

    b.h3("5.4 Transmit panel (dock — Ctrl+Shift+T)")
    b.p("Pinned to the bottom by default. Movable and floatable but "
        "<b>not closable</b> — the input row is operationally critical, "
        "so an accidental dismiss cannot leave the operator with no TX "
        "path. The dock holds, left-to-right: <b>Target</b>, "
        "<b>Message box</b>, <b>Transmit</b>, and the standalone "
        "<b>This is</b> ID button. The Listen toggle and live "
        "input-level meter were previously bundled into this dock; they "
        "now live in the Listen strip above the chat (see "
        "Section 5.3) so RX feedback stays visible regardless of dock "
        "state.")
    b.bullets([
        ("Target dropdown", "Pick a contact callsign or <i>All</i>. "
                            "Entries are sorted alphabetically; <i>All</i> "
                            "is pinned at the top. Family-shared GMRS "
                            "calls appear on separate rows like "
                            "<font face=\"Courier\">WSLZ233 (Eliza)</font> "
                            "/ <font face=\"Courier\">WSLZ233 (Jennifer)"
                            "</font>, and the preface speaks the exact "
                            "operator name from the row you selected."),
        ("Message box", "Text input. Type your message and press Enter "
                        "or click Transmit. Placeholder reads "
                        "<i>Type your message here&hellip;</i>."),
        ("Transmit button", "Alt+T or Ctrl+Return / Ctrl+Enter. Sends "
                            "the message through the TX pipeline: "
                            "shorthand expansion, profanity masking, "
                            "callsign framing, 15-minute ID check, PTT "
                            "keying, TTS synthesis, and STT auto-pause "
                            "until the unkey."),
        ("This is button", "Alt+I or Ctrl+I. Sends a standalone station "
                           "ID — <font face=\"Courier\">This is "
                           "&lt;CALL&gt;, &lt;NATO phonetic&gt;. "
                           "&lt;name&gt; from &lt;location&gt;.</font> "
                           "— without needing to type anything. Resets "
                           "the 15-minute ID timer. Disabled in FRS "
                           "mode (FRS has no ID rule); hover the "
                           "disabled button for the explanation."),
    ])

    b.h3("5.5 Customizing the layout")
    b.p("Drag any panel's title bar to dock it on the left, right, top, "
        "or bottom of the chat surface — or release it outside the main "
        "window to float it as a separate window. Drop one title bar "
        "onto another to tab two panels together. Drag the splitters "
        "between docked areas to resize.")
    b.p("Right-click a panel's title bar — or press the <b>Menu</b> key "
        "while the title bar has focus — for a keyboard-accessible "
        "<b>Move to Left / Right / Top / Bottom</b>, <b>Float / Re-dock</b>, "
        "and <b>Hide</b> menu. The keyboard path mirrors the mouse drag "
        "for operators who can't drag. <b>F6</b> / <b>Shift+F6</b> walks "
        "keyboard focus across visible panel title bars so you can land "
        "on a panel and open its menu in two key presses.")
    b.p("Shortcuts: <b>Ctrl+Shift+S / P / Q / T</b> show or hide the "
        "Station / Pending / Quick Messages / Transmit panels "
        "(Transmit, having no Close, refocuses instead of hiding). "
        "<b>Ctrl+Shift+W</b> toggles the Waterfall (also at "
        "View → Show waterfall). <b>Ctrl+Shift+0</b> snaps everything "
        "back to the documented default arrangement while preserving "
        "your dark-mode and waterfall preferences.")
    b.p("The layout is saved to "
        "<font face=\"Courier\">config.json</font> under "
        "<font face=\"Courier\">ui_layout</font> on close — only on "
        "close, so dragging doesn't churn the file. If the saved state "
        "is missing, malformed, or from a different schema version, the "
        "default arrangement is used and re-written on next close. "
        "Forward-only migration: no user action needed when upgrading.")

    b.h3("5.6 Pending Stations panel (dock — Ctrl+Shift+P)")
    b.p("Docked at the bottom by default, tabbed with Quick Messages. "
        "Hidden when no pills are pending so an empty titled frame "
        "doesn't sit on screen. Yellow pill buttons appear when a new "
        "GMRS callsign is detected on RX:")
    b.bullets([
        "<b>Click</b> a pill to open the Add Station dialog (section 9) "
        "pre-filled with the detected name and location.",
        "<b>Right-click</b> or long-press a pill to dismiss that one "
        "without adding it.",
        "<b>Dismiss all</b> (Alt+D) appears on the right edge whenever "
        "any pill is present — clears every pending pill at once.",
        "Pills wrap to additional rows up to a maximum of three; past "
        "that a vertical scrollbar appears so the chat area doesn't get "
        "squeezed.",
    ])

    b.h3("5.7 Quick Messages panel (dock — Ctrl+Shift+Q)")
    b.p("Docked at the bottom by default, tabbed with Pending Stations. "
        "Hidden when the preset list is empty. Each button rides the "
        "standard TX pipeline. Curly-brace tokens like "
        "<font face=\"Courier\">{N}</font> in "
        "<font face=\"Courier\">QSY to channel {N}</font> prompt for a "
        "value before transmitting. The first nine buttons are bound to "
        "<b>Alt+1</b> through <b>Alt+9</b>. Edit the list from "
        "Settings → Quick Messages or the Q icon.")
    b.p("The seed list is: <i>Radio check, Loud and clear, Standing by, "
        "Acknowledged, Say again, QSY to channel {N}, Clear, Monitoring, "
        "Net check-in, Emergency traffic</i>.")

    b.h3("5.8 Callsigns Detected panel (dock — Ctrl+Shift+A)")
    b.p("A roll-call grid that records every callsign detected during "
        "the current Listen session. Docked at the bottom by default, "
        "tabbed with Pending Stations and Quick Messages. "
        "<b>Off by default</b> — enable it from "
        "<b>View → Show callsigns detected</b> or "
        "<b>Settings → Configuration → Callsigns Detected</b> (Alt+D in "
        "the dialog). Persists at "
        "<font face=\"Courier\">attendance.enabled</font> in "
        "<font face=\"Courier\">config.json</font>. Disabled in FRS "
        "mode alongside every other callsign-dependent surface.")
    b.bullets([
        ("Columns", "<b>Callsign | Name | Location | GMRS | HAM</b>. "
                    "Read-only; the grid is for reference, not editing. "
                    "All columns autofit to their content each time a "
                    "new callsign is recorded. Drag any column divider "
                    "to adjust widths manually — the autofit on the "
                    "next detection will refit all columns to content "
                    "again."),
        ("Auto-population", "Unknown callsigns appear with only the "
                            "Callsign column filled. The moment that "
                            "callsign is added to (or already in) "
                            "Contacts, the remaining four columns fill "
                            "in automatically from the contact row — "
                            "adding a station retroactively fills its "
                            "callsigns-detected row."),
        ("Order", "Insertion order, deduplicated — the first station "
                  "heard sits at the top. Re-hearing a callsign within "
                  "the same session does not add a second row."),
        ("Persists across Listen cycles", "Toggling Listen off and back "
                                          "on does not clear the grid — "
                                          "callsigns accumulate across the "
                                          "entire operating session. Only "
                                          "the Remove and Clear controls "
                                          "below, or switching to FRS "
                                          "mode, reset the list."),
        ("Remove selected button", "Enabled when a row is selected. "
                                   "Removes that single callsign from "
                                   "the session list without touching "
                                   "Contacts. Right-clicking any row "
                                   "shows an equivalent context-menu "
                                   "option: "
                                   "<i>Remove CALLSIGN from session</i>. "
                                   "Removed callsigns can be re-detected "
                                   "and re-added if heard again."),
        ("Clear callsigns detected button", "Sits below the table to the "
                                            "right of Remove selected. "
                                            "Empties the entire grid "
                                            "immediately; future detections "
                                            "still log normally."),
        ("Save session button", "Stores the current grid as a timestamped "
                                "net-session record under "
                                "<font face=\"Courier\">net_sessions/</font> "
                                "for the attendance history (see Tools → "
                                "Net Attendance History). Auto-save is "
                                "available in Settings → Configuration → "
                                "Behavior → Auto-save sessions: the grid is "
                                "stored every time Listen stops, skipping "
                                "sessions with no callsigns."),
        ("Export CSV button", "Saves the live grid to a CSV file with "
                              "columns Callsign, Name, Location, GMRS, HAM."),
        ("Net Attendance History", "Tools → Net Attendance History opens a "
                                   "two-tab browser. <b>History</b> lists "
                                   "every saved session newest-first with "
                                   "its full roster, per-session CSV export, "
                                   "an export-all CSV (one row per station "
                                   "per session), and per-session delete. "
                                   "<b>Statistics</b> aggregates per-station "
                                   "attendance — total nets, attendance over "
                                   "the last 10, current streak, last seen — "
                                   "sorted busiest-first, with CSV export. A "
                                   "station is a callsign + name pair, so "
                                   "family members sharing one GMRS callsign "
                                   "count separately."),
        ("Touch-screen mode", "When the app is in touch mode the "
                              "<b>Remove selected</b>, <b>Clear "
                              "callsigns detected</b>, <b>Save session</b>, "
                              "and <b>Export CSV</b> buttons scale to "
                              "44 px minimum height for reliable touch "
                              "targets. The table itself is not affected."),
    ])

    b.h3("5.9 Status bar")
    b.p("Carries a permanent <b>Online</b> / <b>Offline</b> indicator on "
        "the right edge (matching the OS taskbar convention). Green ● "
        "for online, amber ○ for offline. Updates every 30 seconds. The "
        "indicator is the user-visible side of the contract for opt-in "
        "network features — when offline, the FCC verification button "
        "disables and save-time verification is skipped. Hidden in FRS "
        "mode where FCC lookups don't apply. The left side of the "
        "status bar shows transient messages (Ready, STT status, "
        "waterfall activity).")

    b.h3("5.10 Menubar")
    b.p("Three menus: <b>Settings</b> (Alt+S), <b>View</b> (Alt+V), "
        "and <b>Tools</b> (Alt+T).")
    b.p("Settings contains persistent configuration only — nothing "
        "destructive:")
    b.bullets([
        ("Configuration… (Alt+C or Ctrl+,)", "Opens the Configuration "
                                                   "dialog (section 6)."),
        ("Contacts… (Alt+N or Ctrl+B)", "Opens the Contacts dialog "
                                              "(section 7). Disabled in "
                                              "FRS mode."),
        ("Quick Messages… (Alt+Q)", "Opens the Quick Messages "
                                          "editor (section 8)."),
    ])
    b.p("View contains a <b>Waterfall</b> submenu (Show waterfall "
        "Ctrl+Shift+W, Color map, Frequency range, Time window — all "
        "waterfall controls co-located), the callsigns-detected toggle "
        "(<b>Show callsigns detected</b>, Ctrl+Shift+A — keeps "
        "<font face=\"Courier\">attendance.enabled</font> in sync with "
        "the Configuration dialog checkbox so both surfaces are "
        "interchangeable), a <b>Panels</b> submenu carrying the "
        "show/hide checkboxes for Station, Pending Stations, Quick "
        "Messages, and Transmit, and a <b>Reset layout to default</b> "
        "action (Ctrl+Shift+0).")
    b.p("Tools contains session-level actions:")
    b.bullets([
        ("Generate Session Journal… (Ctrl+J)", "Sends the current "
                                               "conversation transcript "
                                               "and detected callsigns to "
                                               "Google Gemini, which "
                                               "generates a titled narrative "
                                               "summary. The entry is saved "
                                               "to <font face=\"Courier\">"
                                               "journals/</font> as a "
                                               "timestamped JSON file. "
                                               "Requires a Gemini API key "
                                               "in Configuration. Shows an "
                                               "informative dialog if the "
                                               "key is missing or the "
                                               "transcript is empty. "
                                               "Generation runs in the "
                                               "background; the action "
                                               "disables until it "
                                               "completes."),
        ("View Session Journals… (Ctrl+Shift+J)", "Opens the non-modal "
                                                  "Session Journals browser "
                                                  "(section 5.11). Same "
                                                  "destination as the 📓 "
                                                  "toolbar button."),
        ("Clear Chat (Ctrl+K)", "Erases every message from the "
                                "conversation log after a Yes/No "
                                "confirmation. Chat history is "
                                "in-memory only and cannot be "
                                "recovered once cleared."),
    ])


def build_journals(b: Builder):
    b.h1("5.11 Session Journals")
    b.p("The Session Journals feature sends the current conversation "
        "transcript and detected callsigns to <b>Google Gemini 3.5 Flash</b>"
        " and saves an AI-generated journal entry to disk. It "
        "requires a free Google Gemini API key configured in Settings → "
        "Configuration → Gemini API Key.")
    b.h3("Generating a journal entry")
    b.p("Click <b>Tools → Generate Session Journal…</b> (Ctrl+J) or the "
        "<b>Generate log entry</b> button on the listen strip (visible "
        "when a Gemini API key is configured) while the conversation log has content. The "
        "app checks for a Gemini API key and a non-empty transcript; if "
        "either is missing an informative dialog explains what to do. "
        "When both are present, generation runs on a background thread — "
        "the action disables and the status bar shows "
        "<i>Generating journal entry via Gemini…</i> — so the UI stays "
        "responsive while the API call is in flight. On success, the "
        "status bar shows the saved file path for five seconds.")
    b.bullets([
        ("Title", "A concise session title — 10 words or fewer — "
                  "generated by Gemini."),
        ("Summary", "A 2–4 paragraph narrative of the conversations "
                    "and activities detected in the transcript."),
        ("Callsigns", "The list from the Callsigns Detected panel at "
                      "the moment of generation."),
        ("Transcript", "The full conversation log text."),
        ("Exported at", "ISO-8601 timestamp of when the entry was "
                        "generated."),
    ])
    b.p("Entries are saved under "
        "<font face=\"Courier\">journals/YYYYMMDD_HHMMSS.json</font> "
        "relative to the project root. The directory is created "
        "automatically on first use.")
    b.h3("Browsing journal entries")
    b.p("Click <b>Tools → View Session Journals…</b> (Ctrl+Shift+J) or "
        "the 📓 toolbar button to open the non-modal Journal browser. "
        "The dialog stays open while you listen, so you can review past "
        "sessions without interrupting the current one.")
    b.bullets([
        ("Entry list (left pane)", "All saved entries sorted newest "
                                   "first. Each row shows the export "
                                   "date and AI-generated title. Click "
                                   "any row to load its detail view."),
        ("Detail view (right pane)", "Shows the entry title, export "
                                     "timestamp, callsigns detected, and "
                                     "AI summary as formatted HTML."),
        ("Delete entry button", "Permanently deletes the selected "
                                "entry after a Yes/No confirmation. "
                                "Does not affect contacts or config. "
                                "The list reloads automatically after "
                                "deletion."),
    ])
    b.note(
        "Journal generation requires an internet connection to reach the "
        "Gemini API. The rest of the app (RX, TX, contacts) is fully "
        "offline as always — journals are an opt-in cloud feature."
    )


def build_touch_mode(b: Builder):
    b.h1("5.12 Touch-screen mode")
    b.p("Touch-screen mode replaces the normal docked-panel layout with a "
        "single full-panel view optimised for finger operation. It is "
        "designed for tablets, touch-enabled laptops, and Raspberry Pi "
        "units attached to a touchscreen display.")
    b.h3("Entering and leaving touch mode")
    b.p("Click the <b>⊞</b> button (leftmost icon in the service toolbar "
        "icon cluster) to enter touch mode. The label flips to <b>⊟</b> "
        "while touch mode is active. Click <b>⊟</b> to return to the "
        "standard desktop layout. The preference persists to "
        "<font face=\"Courier\">touch_mode</font> in "
        "<font face=\"Courier\">config.json</font> — operators who leave "
        "the app in touch mode come back to the touch view on the next "
        "launch.")
    b.h3("Touch view layout (top → bottom)")
    b.bullets([
        ("Pending-stations pill row", "The same pill buttons that appear "
                                      "on the Pending Stations dock are "
                                      "mirrored here at the top of the "
                                      "touch view. In touch mode the pills "
                                      "are larger — bolder text, extra "
                                      "padding, and 44 px minimum height — "
                                      "for reliable tap targets. Tap a pill "
                                      "to open the Add Station dialog; "
                                      "right-click or long-press to dismiss "
                                      "without adding."),
        ("Conversation log", "Full-height chat display — all RX "
                             "transcripts, TX echoes, and callsign "
                             "highlights stream in real time. The log "
                             "stays in sync with the normal view; "
                             "switching modes never drops a message. "
                             "A round <b>▼</b> button (56 × 56 px) "
                             "overlays the bottom-right corner whenever "
                             "the log is scrolled up; tapping it jumps "
                             "immediately to the latest message. The "
                             "button disappears automatically when the "
                             "log is already at the bottom."),
        ("Row 1 — primary radio controls (80 px tall)",
         "<b>Listen</b> (checkable, green) | "
         "<b>Listen Only</b> (checkable, amber). "
         "Both mirror the corresponding controls on the normal Listen "
         "strip — tapping either button on the touch view has exactly "
         "the same effect as clicking it on the desktop strip."),
        ("Row 2 — secondary controls (56 px tall)",
         "<b>Monitor</b> (checkable; enabled only when Listen-only "
         "is active, matching the desktop rule) | "
         "<b>🌙/☀️ Theme</b> (toggles dark/light mode) | "
         "<b>Callsigns</b> (floats the Callsigns Detected dock as an "
         "overlay without leaving touch mode — the Remove selected and "
         "Clear callsigns detected buttons inside that panel also scale "
         "to 44 px for touch use) | "
         "<b>Generate Log</b> (visible only when a Gemini API key is "
         "configured — generates an AI session journal entry) | "
         "<b>View Logs</b> (opens the Session Journals browser)."),
    ])
    b.h3("Dock behaviour")
    b.p("Entering touch mode automatically hides every dock panel "
        "(Station, Waterfall, Pending Stations, Quick Messages, "
        "Transmit). Their positions, sizes, and tab arrangements are "
        "saved internally. Exiting touch mode restores each panel to "
        "exactly the visibility it had before touch mode was activated "
        "— the desktop layout is preserved across the round trip.")
    b.note(
        "The Transmit dock is hidden in touch mode because touch-screen "
        "operation is receive-focused. All RX controls are available in "
        "the touch view. If you need to transmit a typed message, exit "
        "touch mode, type in the Transmit dock, then re-enter."
    )
    b.h3("State sync between views")
    b.p("The touch view always mirrors the normal-view state — no manual "
        "sync is needed when switching modes mid-session:")
    b.bullets([
        "Listen toggle state and label ("
        "<i>Listen</i> / <i>Listening…</i>) stay in step.",
        "Listen Only checked state stays in step.",
        "Monitor checked state and enabled state stay in step.",
        "Theme glyph (🌙 or ☀️) updates whenever the theme changes, "
        "in either view.",
        "Generate Log visibility updates whenever the Gemini API key "
        "is saved or cleared in Configuration.",
        "Pending-station pills are added and removed in both views "
        "simultaneously.",
    ])


def build_config_dialog(b: Builder):
    b.h1("6. Configuration dialog")
    b.p("Opened from Settings → Configuration, the gear icon, or "
        "Ctrl+,. Minimum width 420 px. Settings are organized into six "
        "tabs. All fields are mnemonic-linked (Alt+letter focuses the "
        "underlined field). The OK button is disabled until the background "
        "device-enumeration thread finishes; while loading you'll see "
        "<i>Loading devices&hellip;</i> in the device dropdowns.")
    b.h3("Identity tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["Callsign (Alt+C)", "Text",
             "Your FCC GMRS callsign. Saved uppercased and stripped."],
            ["Name (Alt+N)", "Text",
             "Operator name. Used in callsign preface and ID."],
            ["Location (Alt+L)", "Text",
             "City, state. Used by the standalone This is announcement."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.h3("Audio tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["Input Device (Alt+I)", "Dropdown",
             "Microphone for capture. System Default plus every device "
             "PortAudio reports, plus <i>System Audio Output (loopback)</i> "
             "at the bottom of the list. Selecting loopback reveals a "
             "<b>Monitor Sink</b> sub-dropdown — pick which output device "
             "to capture (System Default follows the OS default playback "
             "device). Play audio in any browser or media player and the "
             "app transcribes it. On Linux uses parec --device=<sink>.monitor "
             "via PipeWire/PulseAudio; on Windows uses WASAPI loopback. "
             "The Monitor toggle is blocked when loopback is the input to "
             "prevent a feedback loop. Changing this restarts the listener."],
            ["Monitor Sink (Alt+M, loopback only)", "Dropdown",
             "Visible only when System Audio Output (loopback) is selected "
             "as the Input Device. Lists the available audio output devices "
             "(PulseAudio/PipeWire sinks on Linux; WASAPI output devices "
             "on Windows). System Default captures whatever is set as the "
             "OS default playback device. Stored as system_monitor_sink."],
            ["Output Device (Alt+O)", "Dropdown",
             "Where TTS audio plays. Pick a USB sound card to feed your "
             "radio directly. System Default uses the OS default sink."],
            ["Monitor audio (Alt+M)", "Checkbox",
             "Default off. When checked, the Monitor toggle on the main "
             "window activates automatically each time Listen-only mode "
             "is enabled, routing incoming radio audio unfiltered to the "
             "output device in real-time. The Monitor toggle is the live "
             "control; this checkbox sets the power-on default only."],
            ["VAD Threshold (Alt+D)", "Spin 0.10–0.95 step 0.05",
             "Silero VAD speech probability cutoff. Lower = more "
             "sensitive, higher = stricter. Default 0.50. Changing this "
             "restarts the listener."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.h3("Voice tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["Voice Model (Alt+V)", "Dropdown + Test",
             "Lists every .onnx file in Voices/. Test button (Alt+T) "
             "synthesizes a short sample at the current speech rate, "
             "played on the currently selected output device."],
            ["Speech Rate (Alt+R)", "Slider 0.70×–1.50×",
             "Maps to Piper length_scale. 1.00× normal, lower = "
             "faster, higher = slower. Step 0.05. Stored as "
             "tts_length_scale."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.h3("STT tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["Whisper Model (Alt+M)", "Dropdown",
             "Which locally staged Whisper model transcribes incoming "
             "audio. Only models already present under Models/STT are "
             "listed — run bootstrap_models.py to stage more. Larger "
             "models are more accurate but slower. Changing this "
             "restarts the listener."],
            ["Final-pass model (Alt+N)", "Dropdown",
             "Default Off (single pass). When set, each completed "
             "transmission is re-transcribed whole by this larger model on "
             "a background thread and the chat line is upgraded in place. "
             "Auto picks the best model staged under Models/STT. Stage one "
             "with bootstrap_models.py --model small.en large-v3-turbo."],
            ["Final-pass device (Alt+V)", "Dropdown",
             "Auto / GPU / CPU. GPU needs the optional requirements-gpu.txt "
             "extras; any GPU failure falls back to CPU automatically."],
            ["Final-pass max length (Alt+L)", "Spin 5–600 s",
             "Transmissions longer than this keep their streaming "
             "transcript instead of a possibly-truncated re-read. "
             "Default 60 s."],
            ["Gain mode (Alt+G)", "Dropdown",
             "Gain stage applied to each utterance before transcription. "
             "Dynamic AGC (default) levels weak and strong stations with "
             "fast-attack/slow-release smoothing; RMS normalize applies "
             "one flat gain to −20 dBFS; No gain leaves levels "
             "untouched. Stored as stt_gain_mode."],
            ["Noise profile (Alt+F)", "Checkbox",
             "Default off. Samples channel static while the squelch is "
             "closed and uses it as the denoiser's stationary noise "
             "estimate, instead of guessing from the speech itself. Can "
             "improve accuracy on consistently noisy channels."],
            ["Custom phrases (Alt+H)", "Multi-line text",
             "One phrase per line — names, landmarks, club jargon. Added "
             "to the Whisper vocabulary bias alongside built-in radio "
             "procedure words and contact callsigns, so the transcriber "
             "stops mishearing them. Stored as saved_phrases."],
            ["Max callsigns (Alt+X)", "Spin 0–50",
             "How many saved contact callsigns to include in the "
             "recognition vocabulary (newest win when over the limit). "
             "Each costs about 6 of the ~223 available prompt tokens."],
            ["Debug capture (Alt+B)", "Checkbox",
             "Default off. Records every utterance's raw, segmented, and "
             "processed audio plus transcripts for offline accuracy "
             "analysis with python -m gmrs_tty.tools.eval_stt. Captures "
             "grow quickly; leave off in normal use."],
            ["Debug directory (Alt+Y)", "Text",
             "Where debug captures are written. Default debug/stt, "
             "relative to the working directory. Only enabled while "
             "Debug capture is checked."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.h3("PTT tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["PTT Mode (Alt+P)", "Dropdown",
             "Manual / VOX / USB FTDI / Serial. See section 12."],
            ["Serial Port (Alt+S)", "Text",
             "Only enabled in USB FTDI mode. e.g. /dev/ttyUSB0 or COM3."],
            ["Control Line (Alt+E)", "Dropdown",
             "Only enabled in USB FTDI mode. RTS or DTR."],
            ["VOX primer tone (Alt+O)", "Checkbox",
             "Default off. Plays a 1 kHz priming tone (then a short "
             "settle gap) before speech so a VOX-keyed radio is fully "
             "keyed before the first word — stops VOX attack from "
             "clipping the opening syllable."],
            ["Primer length (Alt+L)", "Spin 50–2000 ms",
             "Duration of the priming tone. Default 300 ms; radios with "
             "slow VOX attack may need longer."],
            ["Priming word (Alt+G)", "Checkbox",
             "Default off. Speaks a keyword before the actual message so "
             "the radio keys on a clear spoken word — an alternative or "
             "supplement to the tone."],
            ["Word (Alt+W)", "Text",
             "The spoken priming word. Default \"transmit\". Only "
             "enabled while Priming word is checked."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.h3("Behavior tab")
    b.table(
        ["Field", "Type", "Behavior"],
        [
            ["Time Format (Alt+F)", "Dropdown",
             "24-hour (14:32:15) or 12-hour (2:32:15 PM) for RX "
             "timestamps."],
            ["Filter profanity (Alt+Y)", "Checkbox",
             "Mask strong language with asterisks. Default on. Applies "
             "to both RX transcripts and TX messages before TTS speaks "
             "them."],
            ["Fuzzy callsigns (Alt+U)", "Checkbox",
             "Default off. When on, an incoming callsign that differs "
             "from a saved contact by exactly one same-class character "
             "(letter-for-letter or digit-for-digit) is rewritten in "
             "the chat to the canonical contact callsign and the "
             "pending-station pill is suppressed. Ambiguous near-misses "
             "(two contacts equally one character away) are left alone. "
             "See section 15.4."],
            ["Callsigns Detected (Alt+D)", "Checkbox",
             "Default off. Enables the Callsigns Detected dock — a roll-call "
             "grid of every callsign detected in the current Listen "
             "session. Persists at "
             "<font face=\"Courier\">attendance.enabled</font>. Also "
             "toggleable from View → Show callsigns detected "
             "(Ctrl+Shift+A). GMRS only."],
            ["Auto-save sessions (Alt+O)", "Checkbox",
             "Default off. Stores the Callsigns Detected grid as a net "
             "session record each time Listen stops (empty sessions are "
             "skipped). Records feed Tools → Net Attendance History. "
             "Persists at "
             "<font face=\"Courier\">attendance.autosave_sessions</font>."],
            ["Condition TX audio (Alt+X)", "Checkbox",
             "Default off. Band-limits synthesized speech to the "
             "300–3000 Hz FM voice channel, compresses peaks, and "
             "normalizes the level so the voice modulates the radio "
             "consistently without clipping. Leave off if TTS plays "
             "through regular speakers."],
            ["Max TX length (Alt+L)", "Spin 0–600 s",
             "Hard cap on how long PTT may stay keyed for one "
             "transmission — if playback runs longer, TX is stopped and "
             "PTT released with a chat notice. Default 60 s; 0 (Off) "
             "disables. An Abort TX button (Esc) also appears in the "
             "Transmit row while a transmission is in progress."],
            ["Synthesis timeout (Alt+T)", "Spin 0–300 s",
             "How long to wait for Piper synthesis before abandoning the "
             "transmission. The radio is never keyed on this path. "
             "Default 30 s; 0 (Off) disables."],
            ["Gemini API Key (Alt+G)", "Password text + Show/Hide",
             "Google Gemini API key for AI-generated session journals. "
             "Leave blank to disable journal generation. The field uses "
             "password echo by default; toggle <b>Show</b> to reveal "
             "the key. Obtain a free key at "
             "https://aistudio.google.com/app/apikey. "
             "Stored in config.json as "
             "<font face=\"Courier\">gemini_api_key</font>."],
        ],
        col_widths=[1.5 * inch, 1.4 * inch, 3.85 * inch],
    )
    b.note(
        "On save the dialog returns a sanitized config object: callsign "
        "uppercased, name/location/serial-port stripped of leading and "
        "trailing whitespace, length scale rounded to two decimals."
    )


def build_contacts_dialog(b: Builder):
    b.h1("7. Contacts dialog")
    b.p("Opened from Settings → Contacts, the person icon, or "
        "Ctrl+B. Minimum size 820×360. Six columns of editable "
        "data; <b>Verified</b> is read-only and reflects the FCC "
        "verification gate.")
    b.h3("Columns")
    b.bullets([
        ("Callsign", "Saved uppercased. Required — rows with empty "
                     "callsign are dropped on save."),
        ("Name", "Free-form operator name. Used by the callsign-match "
                 "side of FCC verification (“Tim” matches "
                 "“Surname, Timothy L” in the license record)."),
        ("Location", "Free-form city / state. Auto-backfilled from the "
                     "FCC city on a successful verification when the row "
                     "had no location of its own; values you typed are "
                     "never overwritten."),
        ("GMRS", "Cross-reference callsign — the operator's GMRS "
                 "call if the primary callsign is their HAM call. "
                 "Auto-populated from FCC <font face=\"Courier\">related"
                 "</font> records (service code <font face=\"Courier\">"
                 "ZA</font>) on verification. Hand-editable. Uppercased "
                 "on save."),
            ("HAM", "Cross-reference Amateur callsign. Auto-populated "
                    "from FCC <font face=\"Courier\">related</font> "
                    "records (service codes <font face=\"Courier\">HA"
                    "</font> / <font face=\"Courier\">HV</font>). "
                    "Hand-editable. Uppercased on save."),
            ("Verified", "Read-only. Green ✓ when the callsign is "
                         "in the active FCC database AND the contact's "
                         "name matches a token in the licensee's name. "
                         "Hover for the licensee, GMRS / HAM cross-refs, "
                         "and the timestamp of the last successful "
                         "lookup."),
    ])
    b.h3("Buttons")
    b.bullets([
        ("Add Contact", "Append a row with default values "
                        "<font face=\"Courier\">NEW_CALL</font> / "
                        "<font face=\"Courier\">New Name</font>. Edit "
                        "in place."),
        ("Remove Selected", "Remove the currently selected row."),
        ("Sort by Suffix (Alt+S)", "View-only reorder by the last 3 "
                                    "digits of each callsign. Useful for "
                                    "spotting consecutive licenses or "
                                    "family clusters. <i>ALL</i> stays at "
                                    "the top. Clicking OK still saves "
                                    "the list alphabetically."),
        ("Verify all (Alt+V)", "Check every not-yet-verified row "
                                "against the FCC database. Already-"
                                "verified rows whose callsign and name "
                                "match what was loaded are cached and "
                                "skipped. Disabled when the app is "
                                "offline; hover the disabled button for "
                                "the reason."),
        ("Import… (Alt+I)", "Open a file-picker to import contacts from "
                            "a <b>JSON</b> or <b>CSV</b> file. Incoming "
                            "contacts are <i>merged</i> into the current "
                            "list: rows matched by callsign + name are "
                            "updated with any non-blank fields from the "
                            "file while their FCC verification metadata "
                            "is preserved; entirely new callsigns are "
                            "appended. Works offline; FCC verification "
                            "is not re-run on import."),
        ("Export… (Alt+X)", "Save the current contact list to a file. "
                             "Choosing <b>JSON</b> exports all fields "
                             "(including verification metadata) for a "
                             "lossless round-trip between GMRS-TTY "
                             "instances. Choosing <b>CSV</b> exports the "
                             "five user-editable columns (Callsign, Name, "
                             "Location, GMRS, HAM) for editing in a "
                             "spreadsheet. The exported file can be "
                             "imported back with Import…."),
        ("OK / Cancel", "Standard. OK runs the same verification gate "
                        "as Verify all (newly added rows, edits, and "
                        "previously-failed lookups all get a fresh "
                        "round trip; cached rows are skipped) and saves "
                        "to <font face=\"Courier\">contacts.json</font>."),
    ])
    b.h3("Verification semantics")
    b.bullets([
        "A row earns a green ✓ when (a) the callsign is in the "
        "active FCC database AND (b) the contact's name matches a "
        "token in the licensee's name. Family members on a shared GMRS "
        "callsign whose name doesn't match the licensee remain "
        "unverified.",
        "GMRS / HAM cross-references are <i>only</i> written when the "
        "name matches the licensee. A family-member row keeps its own "
        "GMRS / HAM fields untouched because those callsigns describe "
        "the licensee, not the family member.",
        "Offline behavior: Verify all disables, save-time verification "
        "is skipped, and previously-earned green checks are preserved "
        "untouched — a transient outage will never wipe verified "
        "state.",
    ])


def build_quick_messages_dialog(b: Builder):
    b.h1("8. Quick Messages dialog")
    b.p("Opened from Settings → Quick Messages or the Q icon on the "
        "right side of the service toolbar. Minimum size 520×360. "
        "Single-column editable table of phrases plus four management "
        "buttons.")
    b.bullets([
        ("Add (Alt+A)", "Append a blank row and immediately enter edit "
                        "mode on the new cell."),
        ("Remove Selected (Alt+R)", "Delete the currently selected row."),
        ("Move Up (Alt+U) / Move Down (Alt+D)", "Reorder the selected "
                                                "row. Order matters: the "
                                                "first nine rows get "
                                                "<b>Alt+1</b>…"
                                                "<b>Alt+9</b> shortcuts; "
                                                "everything past slot "
                                                "nine is mouse-only."),
        ("OK / Cancel", "OK saves the trimmed phrase list to "
                        "<font face=\"Courier\">config.json</font> under "
                        "<font face=\"Courier\">quick_messages</font>. "
                        "Blank rows are dropped so the strip never shows "
                        "an unlabeled button."),
    ])
    b.h3("Placeholder tokens")
    b.p("Wrap a token in curly braces to prompt for a value at TX time. "
        "<font face=\"Courier\">QSY to channel {N}</font> opens a small "
        "input dialog asking for <i>N</i>; the substituted phrase then "
        "rides the standard TX pipeline. Multiple tokens are prompted "
        "in order. Cancelling any prompt aborts the transmission.")


def build_add_station_dialog(b: Builder):
    b.h1("9. Add Station dialog")
    b.p("Opens when you click a yellow pill on the Pending Stations panel. "
        "Three-field form with an inline FCC lookup:")
    b.bullets([
        ("Callsign (Alt+C)", "Pre-filled with the detected callsign in "
                              "canonical (compact, uppercase) form. "
                              "A <b>Look Up</b> (Alt+U) button sits to the "
                              "right of this field — see below."),
        ("Name (Alt+N)", "Pre-filled if the heuristic detected a name in "
                          "the surrounding transcription. Left blank if no "
                          "name was found; Look Up fills it from the FCC "
                          "record if the field is still empty when you click."),
        ("Location (Alt+L)", "Pre-filled if a location was detected. "
                              "Look Up fills it from the FCC city when empty."),
    ])
    b.h3("Look Up button (Alt+U)")
    b.p("Queries the FCC crossref database for the entered callsign on a "
        "background thread so the UI stays live during the lookup (up to "
        "5-second HTTP timeout). Behavior varies with what is already in "
        "the form:")
    b.bullets([
        ("Callsign only", "Name and Location are both empty. The lookup "
                           "fetches the license record and pre-fills both "
                           "fields from the FCC data. Status shows "
                           "<i>Found: &lt;name&gt; — &lt;city&gt; (name didn't match)</i> "
                           "because there was no contact name to verify against."),
        ("Callsign + Name", "The name-match gate runs (see section 16). "
                             "A match earns a <i>✓ Verified</i> status line; "
                             "a mismatch shows <i>Found … (name didn't match)</i>. "
                             "Location is filled from FCC if still empty."),
        ("Callsign + Location", "Name field is blank; Location is already "
                                 "set. The lookup fills Name from FCC. "
                                 "The FCC location is shown in the status line "
                                 "so you can compare against what you typed."),
    ])
    b.p("The status line beneath the form uses color to communicate the "
        "outcome: green for verified, amber for found-but-not-verified, "
        "red for not found or error, gray for offline or in-progress. "
        "The button disables when the app is offline and while a lookup "
        "is running.")
    b.p("Click <b>OK</b> to append the new contact to "
        "<font face=\"Courier\">contacts.json</font>; the target "
        "dropdown is rebuilt and any historical RX lines mentioning that "
        "callsign retroactively gain the amber-pill highlight. The "
        "originating pill is removed automatically. <b>Cancel</b> leaves "
        "the pill in place so you can come back to it later.")


def build_keyboard(b: Builder):
    b.h1("10. Keyboard shortcuts &amp; mnemonics")
    b.h3("Global shortcuts")
    b.table(
        ["Action", "Shortcut"],
        [
            ["Toggle Listen", "Ctrl+L"],
            ["Transmit message", "Ctrl+Return / Ctrl+Enter"],
            ["Send standalone station ID", "Ctrl+I"],
            ["Clear chat (with confirmation)", "Ctrl+K"],
            ["Open Configuration dialog", "Ctrl+,"],
            ["Open Contacts dialog", "Ctrl+B"],
            ["Send quick message preset 1–9", "Alt+1 … Alt+9"],
            ["Toggle Waterfall panel", "Ctrl+Shift+W"],
            ["Toggle Callsigns Detected panel", "Ctrl+Shift+A"],
            ["Generate Session Journal", "Ctrl+J"],
            ["View Session Journals", "Ctrl+Shift+J"],
            ["Toggle Station panel", "Ctrl+Shift+S"],
            ["Toggle Pending Stations panel", "Ctrl+Shift+P"],
            ["Toggle Quick Messages panel", "Ctrl+Shift+Q"],
            ["Focus / re-show Transmit panel", "Ctrl+Shift+T"],
            ["Reset layout to default", "Ctrl+Shift+0"],
            ["Cycle keyboard focus across docks", "F6 / Shift+F6"],
        ],
        col_widths=[3.6 * inch, 2.4 * inch],
    )
    b.h3("Main-window mnemonics")
    b.table(
        ["Widget", "Mnemonic"],
        [
            ["GMRS radio", "Alt+G"],
            ["FRS radio", "Alt+F"],
            ["Clear chat button", "Alt+C"],
            ["Listen button", "Alt+L"],
            ["Listen only toggle (RX-only safety)", "Alt+O"],
            ["Monitor toggle (audio monitor, Listen-only only)", "Alt+M"],
            ["Transmit button", "Alt+T"],
            ["This is button", "Alt+I"],
            ["Dismiss all (pending pills)", "Alt+D"],
            ["Settings menu", "Alt+S"],
        ],
        col_widths=[3.6 * inch, 2.4 * inch],
    )
    b.h3("Settings menu mnemonics")
    b.table(
        ["Item", "Mnemonic"],
        [
            ["Configuration…", "Alt+S, Alt+C"],
            ["Contacts…", "Alt+S, Alt+N"],
            ["Quick Messages…", "Alt+S, Alt+Q"],
            ["Clear chat", "Alt+S, Alt+R"],
        ],
        col_widths=[3.6 * inch, 2.4 * inch],
    )
    b.h3("Configuration dialog mnemonics")
    b.table(
        ["Field", "Mnemonic"],
        [
            ["Callsign", "Alt+C"],
            ["Name", "Alt+N"],
            ["Location", "Alt+L"],
            ["Voice Model", "Alt+V"],
            ["Test voice", "Alt+T"],
            ["Speech Rate", "Alt+R"],
            ["Input Device", "Alt+I"],
            ["Output Device", "Alt+O"],
            ["VAD Threshold", "Alt+D"],
            ["Time Format", "Alt+F"],
            ["Filter profanity", "Alt+Y"],
            ["Fuzzy callsigns", "Alt+U"],
            ["Callsigns Detected", "Alt+D"],
            ["PTT Mode", "Alt+P"],
            ["Serial Port", "Alt+S"],
            ["Control Line", "Alt+E"],
        ],
        col_widths=[3.6 * inch, 2.4 * inch],
    )
    b.h3("Tab order in the main window")
    b.p("Listen → Target dropdown → Message box → "
        "Transmit → This is. The order is explicitly set so "
        "keyboard-only operators get a predictable traversal.")


def build_service_mode(b: Builder):
    b.h1("11. GMRS vs FRS service mode")
    b.p("The top-of-window toggle controls which Part 95 subpart the app "
        "treats as canonical. GMRS (Subpart A) is licensed and "
        "callsign-bearing; FRS (Subpart B) is unlicensed and has no "
        "callsign requirement. Switching modes is instantaneous; saved "
        "contacts and the saved callsign are preserved across mode "
        "changes so switching back to GMRS restores prior state.")
    b.table(
        ["Feature", "GMRS (default)", "FRS"],
        [
            ["Header line", "Station: CALL | Operator | Location",
             "FRS Mode | Operator | Location"],
            ["Outgoing TX preface", "[CALL] [name] calling [target]",
             "No preface — message is spoken as-is"],
            ["15-minute ID rule", "Enforced", "Skipped"],
            ["This is button", "Enabled", "Disabled (tooltip explains)"],
            ["Target dropdown", "Visible", "Hidden"],
            ["Contacts menu / icon", "Enabled",
             "Disabled (tooltip explains)"],
            ["Pending-station pills", "Detected and displayed",
             "Detection suppressed"],
            ["Callsign chat highlighting", "Amber pills, FCC ✓",
             "Suppressed"],
            ["Online / Offline indicator", "Visible (gates verification)",
             "Hidden (no online features apply)"],
            ["FCC callsign verification", "On (opt-in via connectivity)",
             "Not applicable"],
        ],
        col_widths=[1.8 * inch, 2.5 * inch, 2.4 * inch],
    )
    b.note(
        "<b>Why FRS turns features off:</b> FRS operators are anonymous "
        "by regulation. Surfacing the 15-minute ID button or callsign "
        "verification on an FRS channel would be misleading at best "
        "and FCC-incorrect at worst. The toggle is therefore a hard "
        "behavioral switch, not a cosmetic relabel."
    )


def build_ptt(b: Builder):
    b.h1("12. PTT (Push-to-Talk) modes")
    b.p("Selectable from Configuration → PTT Mode. The choice "
        "determines how the radio is keyed around each transmission.")

    b.h3("Manual")
    b.p("Default. You press PTT on the radio yourself, the app plays "
        "audio through the configured output device, and you release "
        "PTT when the audio finishes. The app makes no attempt to key "
        "the radio.")
    b.p("Use when: you have a desk mic with a foot switch, you're "
        "operating a handheld and physically pressing the PTT button, "
        "or you're testing the app without any radio connected.")

    b.h3("VOX (Voice-Operated Transmit)")
    b.p("Your radio is set to auto-key whenever it hears audio on its "
        "mic input. The app appends a short tail of silence after each "
        "transmission so the last syllable survives the VOX hang "
        "dropout.")
    b.p("Use when: your radio has a VOX setting and you've already "
        "tuned VOX sensitivity / hang time to your setup. Simplest "
        "wiring — just a cable from the output device to the "
        "radio's mic input.")

    b.h3("USB FTDI / Serial")
    b.p("The app keys PTT through a USB-serial adapter's RTS or DTR "
        "line. The line drives an external transistor or opto-isolator "
        "wired to the radio's PTT pin. Short lead-in and tail silence "
        "are inserted around each transmission so the radio's keying "
        "ramp doesn't clip the audio.")
    b.bullets([
        ("Serial Port", "Device path — e.g. "
                        "<font face=\"Courier\">/dev/ttyUSB0</font> on "
                        "Linux or <font face=\"Courier\">COM3</font> on "
                        "Windows. Field is enabled only when this PTT "
                        "mode is selected."),
        ("Control Line", "RTS or DTR. Choose whichever your interface "
                         "uses. Most FTDI-based DIY PTT cables use RTS; "
                         "Signalink-style boxes vary."),
    ])
    b.warn(
        "<b>Cable safety:</b> never wire a serial line directly to a "
        "radio's PTT pin. Use an opto-isolator or NPN transistor between "
        "the adapter and the radio so a stuck line or a host crash "
        "can't dump TTL voltage onto the radio."
    )


def build_rx(b: Builder):
    b.h1("13. Receive (Rx) pipeline")
    b.p("Pressing Listen starts a background thread that captures audio, "
        "gates it through Silero VAD, conditions each utterance through "
        "a DSP chain, and hands the result to faster-whisper for "
        "transcription. The pipeline is designed to skip kerchunks, "
        "static, and Whisper hallucinations so the chat log shows only "
        "genuine speech.")
    b.h3("Audio capture")
    b.bullets([
        "On Linux with PipeWire the app prefers "
        "<font face=\"Courier\">parec</font> over PortAudio because "
        "PortAudio's PipeWire-via-ALSA bridge can silently deliver "
        "flat-zero audio on PipeWire 1.4. If "
        "<font face=\"Courier\">parec</font> is missing the app falls "
        "back to PortAudio.",
        "Anywhere else (or if you've selected a specific input device "
        "index in Configuration), PortAudio is used directly.",
    ])
    b.h3("Squelch-open pre-trigger")
    b.p("A peak-amplitude edge detector watches every captured chunk so "
        "the leading syllables of a transmission survive Silero VAD's "
        "onset latency. The moment a remote operator's carrier opens — "
        "audio jumps above the noise floor for two consecutive ~32 ms "
        "chunks — the app starts buffering chunks in a rolling deque "
        "capped at roughly 2 s. When VAD then fires on real speech, the "
        "entire pre-voice buffer is prepended to the utterance before "
        "bandpass, denoise, and Whisper. When the carrier instead closes "
        "again (peak below threshold for ~500 ms) without VAD ever "
        "firing — a kerchunk, accidental key, or stray noise burst — "
        "the buffer is discarded and nothing reaches the chat.")
    b.p("The detector's thresholds and hysteresis are tuned defaults, "
        "not user-configurable. Operators should not need to think about "
        "this stage; it exists so the first word of a transmission "
        "isn't clipped.")
    b.h3("Voice activity detection (VAD)")
    b.bullets([
        ("Silero VAD", "Neural VAD. Only audio it scores as speech is "
                       "forwarded for transcription — kerchunks and "
                       "static are dropped."),
        ("Threshold", "Tunable from 0.10 (very sensitive) to 0.95 (very "
                      "strict) in Configuration. Default 0.50."),
        ("Auto-rebaseline", "After roughly 30 s of continuous silence "
                            "the VAD is rebaselined so detection stays "
                            "responsive on long-quiet channels."),
        ("TX auto-pause", "While the app is transmitting, the listener "
                          "is paused so your own TTS isn't transcribed "
                          "back. Listening resumes immediately on "
                          "unkey, with VAD state reset so no in-progress "
                          "speech bleeds across the boundary."),
    ])
    b.h3("DSP conditioning")
    b.bullets([
        ("300–3000 Hz bandpass", "Matches the narrowband-FM voice "
                                       "band. Strips hum and out-of-band "
                                       "hiss. Applied both to the live "
                                       "monitor stream and per utterance "
                                       "before denoising."),
        ("Noise reduction", "Spectral gating applied per utterance "
                            "after bandpass and before transcription."),
        ("RMS normalization", "After denoising, each utterance is "
                              "normalized to &minus;20 dBFS so weak "
                              "or distant stations reach Whisper at a "
                              "consistent input level."),
        ("Hallucination filter", "Drops utterances shorter than ~400 ms "
                                  "and common Whisper hallucinations on "
                                  "silence (“Thank you”, "
                                  "“Subtitles by…”, etc.)."),
    ])
    b.h3("Transcription")
    b.bullets([
        ("Engine", "faster-whisper (CTranslate2 backend). int8 CPU "
                   "inference by default."),
        ("Default model", "<font face=\"Courier\">small.en</font>. "
                          "Trade quality / speed via "
                          "<font face=\"Courier\">bootstrap_models.py "
                          "--model base.en|medium.en</font>."),
        ("Profanity masking", "When <b>Filter profanity</b> is on, "
                              "strong language in the transcript is "
                              "masked with asterisks before it lands "
                              "in the chat log."),
    ])
    b.h3("Streaming transcription for long utterances")
    b.p("Short transmissions are transcribed in one shot — the operator "
        "sees a single RX line drop into the chat at the unkey. Anything "
        "that runs longer than about 5 s is sliced and transcribed "
        "incrementally so the chat doesn't sit blank during a long "
        "monologue:")
    b.bullets([
        "Once the captured speech crosses ~5 s, the capture loop scans "
        "the next 500 ms for the quietest point and cuts there — slice "
        "boundaries land between words, not mid-syllable.",
        "Each slice is handed to a background Whisper thread under a "
        "shared utterance id so the capture loop never blocks waiting "
        "for inference.",
        "Partials arrive in order and the chat renders them as a single "
        "growing line — "
        "<font face=\"Courier\">[RX 14:32:01]: hello bob how are you "
        "today&hellip;</font> — rather than as separate messages.",
        "Every partial still rides the full bandpass + denoise + "
        "hallucination-filter chain. Callsign-discovery scanning runs "
        "once over the full accumulated text — at the final segment, "
        "or immediately when the utterance is abandoned (PTT pressed "
        "mid-reception, Listen toggled off, or a new utterance "
        "starting before the previous one completes) — so the "
        "callsigns-detected panel always reflects what the chat shows.",
    ])
    b.note(
        "Slice length and the cut-search window are tuned constants, "
        "not configuration knobs. The operator-facing contract is "
        "simple: short utterances arrive whole at unkey, long ones "
        "stream in as they're spoken."
    )
    b.h3("Audio monitor")
    b.p("The <b>Monitor</b> toggle (Alt+M, on the listen strip) routes "
        "incoming radio audio to the configured output device in "
        "real-time, letting a deaf or HoH operator hear the channel "
        "through speakers simultaneously with the transcription pipeline.")
    b.bullets([
        ("When available", "Monitor is only enabled when <b>Listen-only</b> "
                           "mode is on. Enabling it on a full-duplex "
                           "session would risk audio feedback from the "
                           "output device back into the radio mic, so the "
                           "button is greyed out whenever Listen only is "
                           "off. Turning Listen only off automatically "
                           "stops the monitor stream."),
        ("Audio processing", "Before reaching the output device, audio "
                             "passes through a 300&ndash;3000 Hz bandpass "
                             "filter (matching the narrowband-FM voice "
                             "band) and is upsampled from 16 kHz to 48 kHz "
                             "via a polyphase sinc resampler so the device "
                             "receives its native rate rather than relying "
                             "on driver-level interpolation. TX mute and "
                             "unmute transitions apply a 5 ms linear fade "
                             "to eliminate clicks at keying boundaries."),
        ("Ring buffer", "A thread-safe bounded deque (~1 s) absorbs "
                        "burst-capture spikes. When the buffer would "
                        "exceed capacity, the oldest samples are dropped "
                        "so playback never lags behind live audio."),
        ("Persistence", "The toggle state is saved to "
                        "<font face=\"Courier\">monitor_enabled</font> in "
                        "<font face=\"Courier\">config.json</font>. When "
                        "the app starts with this flag set, the Monitor "
                        "toggle activates automatically the next time "
                        "Listen-only mode is turned on."),
        ("Configuration default", "Settings &rarr; Configuration &rarr; "
                                  "<b>Monitor audio</b> sets the power-on "
                                  "default; the in-strip toggle controls "
                                  "the live state."),
    ])

    b.h3("13.9 STT calibration wizard")
    b.p("Tools &rarr; <b>Calibrate STT</b> (enabled while Listen is active) "
        "finds the most accurate STT settings for your radio and channel "
        "conditions in four steps:")
    b.bullets([
        ("1. Reference passage", "The wizard shows a fixed passage (the "
                                 "opening of the Declaration of "
                                 "Independence). Arrange for another "
                                 "station to read it over the air, or read "
                                 "it yourself on a loopback input."),
        ("2. Recording", "Click <b>Start recording</b>, have the passage "
                         "read, then <b>Stop and analyze</b>. At least a "
                         "few seconds of audio are required; the capture "
                         "is bounded at three minutes."),
        ("3. Analyzing", "Every staged Whisper model &times; gain mode "
                         "&times; noise profile combination transcribes "
                         "the recording and is scored by word-error-rate "
                         "against the passage. The progress bar reads "
                         "\"combination N of M\"; on CPU a multi-model "
                         "sweep takes minutes."),
        ("4. Results", "Combinations are ranked best-first with the "
                       "recommended row preselected. <b>Apply selected</b> "
                       "writes the model, gain mode, and noise profile to "
                       "the configuration; a model change takes effect the "
                       "next time Listen starts. Escape cancels cleanly at "
                       "any step."),
    ])


def build_tx(b: Builder):
    b.h1("14. Transmit (Tx) pipeline")
    b.p("Each transmission (typed message, quick preset, or This is) "
        "passes through the same pipeline.")
    b.bullets([
        ("1. Placeholder substitution", "Curly-brace tokens in quick "
                                         "presets are filled by "
                                         "prompting the user."),
        ("2. Shorthand expansion", "TTY and ham-radio shorthand is "
                                    "rewritten to full words before "
                                    "TTS — GA → Go ahead, "
                                    "SKSK → end of conversation, "
                                    "73 → best regards, QTH "
                                    "→ location, etc. Matching is "
                                    "case-insensitive and word-bounded, "
                                    "longest-key-first, so QSO → "
                                    "radio contact while a lone Q "
                                    "inside another word passes "
                                    "through."),
        ("3. Profanity masking", "When the filter is on (default), "
                                  "strong language is asterisk-masked "
                                  "before TTS sees it. Mild PG-13 words "
                                  "(damn, hell, crap, bare ass) pass "
                                  "through unchanged. Word-bounded so "
                                  "substrings like classroom or "
                                  "Scunthorpe are never false-positives."),
        ("4. FCC framing (GMRS only)", "Prepends "
                                        "<font face=\"Courier\">[CALL] "
                                        "[name] calling [target]</font> "
                                        "when targeting a specific "
                                        "station; appends a station ID "
                                        "if more than 15 minutes have "
                                        "passed since last identification. "
                                        "<i>All</i>-targeted "
                                        "transmissions skip the preface "
                                        "but still pick up the ID "
                                        "append when the rule triggers. "
                                        "FRS skips both."),
        ("5. Spoken-callsign formatting", "Digits inside callsigns are "
                                           "split with spaces so TTS "
                                           "reads them as individual "
                                           "digits (WSLZ 2 3 3 rather "
                                           "than two hundred "
                                           "thirty-three)."),
        ("6. PTT key-down", "Manual mode: no-op. VOX: append silence "
                             "tail. USB FTDI: assert the configured "
                             "control line and pad with lead-in / tail "
                             "silence."),
        ("7. STT auto-pause", "The listener is paused so your own "
                               "audio isn't transcribed back."),
        ("8. Piper synthesis", "TTS audio is rendered offline through "
                                "the selected Piper voice at the "
                                "configured length scale and played to "
                                "the configured output device."),
        ("9. Unkey and resume", "PTT releases (in serial mode) after a "
                                 "tail of silence; STT resumes with VAD "
                                 "state reset."),
    ])


def build_callsign_detection(b: Builder):
    b.h1("15. Callsign detection &amp; FCC verification")
    b.h3("Recognized formats")
    b.bullets([
        "GMRS modern: <font face=\"Courier\">WSLZ233</font>.",
        "GMRS legacy: <font face=\"Courier\">KAE1234</font>.",
        "US amateur: <font face=\"Courier\">K1ABC</font>, "
        "<font face=\"Courier\">KD9XYZ</font>, "
        "<font face=\"Courier\">W1AW</font>.",
        "Compact: <font face=\"Courier\">WSLZ233</font>.",
        "Spaced: <font face=\"Courier\">W S L Z 2 3 3</font>.",
        "Separated: <font face=\"Courier\">W.S.L.Z.233</font>, "
        "<font face=\"Courier\">WSLZ-233</font>, "
        "<font face=\"Courier\">WSLZ, 233</font>.",
        "NATO phonetic: <font face=\"Courier\">Whiskey Sierra Lima "
        "Zulu Two Three Three</font> (also accepts <i>X-ray</i> and "
        "<i>X ray</i>).",
    ])
    b.h3("Pending pills")
    b.p("Unknown stations earn a yellow pill on the Pending Stations panel. The "
        "“unknown” check considers all three callsign fields "
        "on every contact (<font face=\"Courier\">callsign</font>, "
        "<font face=\"Courier\">gmrs_callsign</font>, "
        "<font face=\"Courier\">ham_callsign</font>), so a HAM call "
        "detected over the air won't pill if the operator's GMRS call "
        "is already saved (and vice versa).")
    b.h3("FCC verification (online, opt-in)")
    b.p("When the connectivity probe says the app is online, contacts "
        "are cross-referenced against the public FCC license database "
        "via the ke8rxnwx crossref API. A row earns a green ✓ in "
        "the Verified column when both conditions hold:")
    b.bullets([
        "The callsign is in the active FCC database, AND",
        "The contact's name matches a token in the licensee's name "
        "(“Tim” matches “Surname, Timothy L”).",
    ])
    b.p("Verified lookups also persist <font face=\"Courier\">"
        "gmrs_callsign</font> and <font face=\"Courier\">ham_callsign"
        "</font> fields on the contact, pulled from the FCC "
        "<font face=\"Courier\">related</font> cross-reference list "
        "(service codes <font face=\"Courier\">ZA</font> for GMRS and "
        "<font face=\"Courier\">HA</font> / <font face=\"Courier\">HV"
        "</font> for Amateur). For an operator licensed for both "
        "services, a HAM call entered as the primary will resolve its "
        "associated GMRS call and vice versa.")
    b.p("Cross-references are <b>only</b> written when the contact's "
        "name matches the licensee. A family-member row on a shared "
        "GMRS call (whose name doesn't match) keeps its own GMRS / HAM "
        "fields untouched because those callsigns describe the "
        "licensee, not the family member.")
    b.p("A verified lookup also backfills the contact's <font "
        "face=\"Courier\">location</font> field with the FCC city "
        "(title-cased) when the row had no location of its own. Any "
        "value the operator already typed is left alone.")
    b.note(
        "<b>Caching:</b> rows whose <font face=\"Courier\">verified"
        "</font> flag is True with unchanged callsign and name are "
        "treated as cached. Both Verify all and OK skip them, so "
        "opening and closing Contacts doesn't churn the "
        "<font face=\"Courier\">verified_at</font> timestamp. Newly "
        "added rows, in-dialog edits, and previously-failed lookups "
        "all earn a fresh round trip."
    )
    b.h3("15.4 Fuzzy callsign matching (opt-in)")
    b.p("Whisper occasionally mishears a single character of a "
        "callsign — <font face=\"Courier\">WSLZ233</font> arriving as "
        "<font face=\"Courier\">WSLZ235</font>, or "
        "<font face=\"Courier\">WSIZ233</font> with an "
        "<i>L</i>/<i>I</i> swap. The <b>Fuzzy callsigns</b> checkbox in "
        "Configuration (Alt+U; off by default) rewrites these near-"
        "misses to the canonical contact callsign so the chat doesn't "
        "fragment a single operator into half a dozen near-duplicates.")
    b.p("Match rules:")
    b.bullets([
        "Same length as a saved contact's callsign.",
        "Exactly one character differs.",
        "The differing characters are the same class — letter-for-"
        "letter or digit-for-digit. A digit misheard as a letter "
        "(or vice-versa) is rejected because it usually indicates a "
        "genuinely different callsign rather than a transcription "
        "slip.",
        "Unambiguous — if two saved contacts are equally one "
        "character away, the detected token is left alone so the "
        "operator can resolve it manually.",
    ])
    b.p("Effects when a rewrite fires:")
    b.bullets([
        "The chat line shows the canonical callsign and picks up the "
        "amber contact pill, FCC ✓ check, and hover tooltip.",
        "The pending-station pill is suppressed — no spurious "
        "“+ Add” prompt for a near-miss of a known operator.",
        "Toggling the checkbox mid-session retroactively rewrites "
        "near-misses in chat lines already on screen. Toggling it back "
        "off does not undo prior rewrites; the canonical form is "
        "already visible and accurate.",
    ])
    b.note(
        "Fuzzy matching only ever rewrites <i>toward</i> a callsign "
        "you've already saved. It cannot invent a new callsign or "
        "merge two contacts. The opt-in default keeps the app's "
        "received-text contract literal by default — turn it on only "
        "if your STT environment regularly chews a single character."
    )


def build_compliance(b: Builder):
    b.h1("16. FCC Part 95 compliance features")
    b.p("GMRS-TTY makes Part 95 GMRS compliance the default behavior:")
    b.bullets([
        "Outbound messages always carry your callsign and name when "
        "targeting a specific station.",
        "The 15-minute ID rule is enforced automatically — your "
        "callsign and name are appended when more than 15 minutes have "
        "passed since the last identification.",
        "Identification is appended even on short messages if the rule "
        "triggers.",
        "The standalone <b>This is</b> button (Alt+I or Ctrl+I) sends a "
        "complete station ID and resets the 15-minute timer.",
        "The PG-13 profanity filter (default on) masks strong language "
        "in both RX and TX so transmissions stay within Part 95 "
        "obscenity expectations. Toggle in Configuration if you operate "
        "on a private repeater with different norms.",
        "FRS mode (Subpart B) intentionally skips Part 95 Subpart A "
        "station-ID rules. FRS is unlicensed and has no callsign "
        "requirement, so callsign framing, the 15-minute timer, and "
        "the standalone-ID button are all disabled.",
    ])
    b.warn(
        "<b>You are still responsible for legal operation.</b> This "
        "software does not replace a valid FCC GMRS license, and the "
        "operator remains accountable for content, channel choice, and "
        "any local repeater rules. The app's compliance features are a "
        "convenience, not a guarantee."
    )


def build_accessibility(b: Builder):
    b.h1("17. Accessibility (WCAG 2.1 AA)")
    b.p("The application exists for users with disabilities, so "
        "accessibility is a hard design constraint. The UI targets WCAG "
        "2.1 Level AA — the practical baseline DOJ and Section 508 "
        "reference for software ADA compliance.")
    b.bullets([
        ("Color contrast", "Text colors meet ≥4.5:1 against the "
                            "chat background (RX green #15803D, TX blue "
                            "#1D4ED8, errors #B91C1C, warnings #92400E). "
                            "UI borders such as the pending-station "
                            "pills meet ≥3:1."),
        ("State never by color alone", "Every RX line is prefixed "
                                        "<font face=\"Courier\">[RX "
                                        "HH:MM:SS]:</font>, TX lines "
                                        "<font face=\"Courier\">[TX to "
                                        "&hellip;]:</font> or "
                                        "<font face=\"Courier\">[TX "
                                        "ID]:</font>, errors say "
                                        "<i>Error:</i> or <i>Failed:</i> "
                                        "in the text. Color is "
                                        "supplemental, never the only "
                                        "cue."),
        ("Full keyboard operation", "Explicit tab order (Listen "
                                     "→ Target → Message "
                                     "→ Transmit → This is). "
                                     "Mnemonics on every actionable "
                                     "label. Global shortcuts listed in "
                                     "section 10."),
        ("Screen reader support", "Every non-decorative widget has an "
                                   "accessibleName and (where useful) "
                                   "accessibleDescription for the Qt "
                                   "accessibility bridge — NVDA, "
                                   "JAWS, Orca, VoiceOver."),
        ("Font scaling", "No hard-coded font-size in stylesheets. "
                          "Bold uses Qt's relative QFont API so the OS "
                          "font-scale setting carries through."),
        ("Resizable layout", "Main window minimum 720×520 so "
                              "high-DPI / large-font setups don't clip. "
                              "All dialogs are resizable."),
        ("Focus visible", "Relies on the Fusion style's default focus "
                           "indicator — Qt does not strip outlines "
                           "and neither does the app."),
    ])


def build_offgrid(b: Builder):
    b.h1("18. Off-grid operation")
    b.p("Once the dependencies and models are in place, the radio "
        "workflow does not need a network. RX transcription, TX "
        "synthesis, PTT keying, and contact management all run "
        "locally.")
    b.bullets([
        ("Whisper STT", "Loaded from "
                        "<font face=\"Courier\">Models/STT/&lt;model&gt;/"
                        "</font>. Pre-staged via "
                        "<font face=\"Courier\">bootstrap_models.py"
                        "</font> or bundled by the installer; never "
                        "re-fetched at runtime."),
        ("Silero VAD", "Ships as a local ONNX file inside the wheel."),
        ("Piper TTS", "Voices live under "
                      "<font face=\"Courier\">Voices/</font>; you "
                      "supply them once."),
        ("Online features", "Strictly opt-in via the connectivity "
                             "probe. When offline: the Verify all "
                             "button disables, save-time verification "
                             "is skipped, the online indicator turns "
                             "amber, and previously-earned verified "
                             "checks are preserved untouched. The radio "
                             "workflow keeps running."),
    ])
    b.note(
        "<b>Pre-built installers are already fully air-gapped for the "
        "radio workflow.</b> The Whisper STT and speaker ID models are "
        "bundled inside the .deb / .msi — no bootstrap step, no network "
        "access needed after install. The only online feature ever used "
        "is FCC callsign verification, which is strictly opt-in."
    )
    b.p("Recommended deployment for a <i>source</i> install on an "
        "air-gapped target: clone the repo, install dependencies, and "
        "run <font face=\"Courier\">bootstrap_models.py</font> on an "
        "internet-connected machine. Then copy the entire source tree, "
        "<font face=\"Courier\">Models/</font>, and "
        "<font face=\"Courier\">Voices/</font> to the offline target. "
        "Reuse the same virtual environment if it's portable across "
        "the architecture, otherwise rebuild the venv from the same "
        "<font face=\"Courier\">requirements.txt</font> on the target.")


def build_troubleshooting(b: Builder):
    b.h1("19. Troubleshooting")

    b.h3("Pre-built installer issues")
    b.bullets([
        ("<font face=\"Courier\">gmrs-tty</font> command not found "
         "(Linux .deb)", "The postinst may not have completed. Try "
         "<font face=\"Courier\">sudo dpkg --configure gmrs-tty</font> "
         "to re-run the postinst, then check that "
         "<font face=\"Courier\">/usr/bin/gmrs-tty</font> exists."),
        ("Python venv missing at "
         "<font face=\"Courier\">/opt/gmrs-tty/.venv</font>",
         "Reinstall the package: "
         "<font face=\"Courier\">sudo apt reinstall gmrs-tty</font>. "
         "The postinst will recreate and repopulate the venv from "
         "the bundled wheels."),
        ("App launches but the voice dropdown is empty", "No Piper voice "
         "files are present in "
         "<font face=\"Courier\">/opt/gmrs-tty/Voices/</font>. See "
         "section 3.1.3 for how to add voices."),
        ("Windows MSI: shortcut opens a console window", "The shortcut "
         "targets <font face=\"Courier\">pythonw.exe</font> which "
         "suppresses the console. If you see one, the shortcut may have "
         "been modified — use the Desktop shortcut created at install "
         "time, or recreate it to point at "
         "<font face=\"Courier\">pythonw.exe main.py</font> in the "
         "install directory."),
    ])

    b.h3("Listen does nothing or fails immediately")
    b.bullets([
        ("“STT model not found” in chat", "Run "
         "<font face=\"Courier\">python bootstrap_models.py --model "
         "&lt;name&gt;</font> with the model named in the message."),
        ("Listen toggles but the level meter stays at zero", "The app "
         "isn't getting audio. Check the Input Device dropdown in "
         "Configuration, your microphone privacy permissions, and the "
         "physical cable. On PipeWire installs, confirm "
         "<font face=\"Courier\">pulseaudio-utils</font> is installed "
         "so <font face=\"Courier\">parec</font> is on PATH."),
        ("Lots of false starts on a noisy channel", "Raise VAD "
         "Threshold (try 0.65–0.75). Conversely, on a very quiet "
         "channel where speech is being missed, lower it (try 0.30)."),
    ])

    b.h3("Transmit is silent or clipped")
    b.bullets([
        ("Nothing audible at all", "Check Output Device. If you're "
         "feeding the radio directly, make sure you didn't accidentally "
         "leave Output Device on System Default — you'd hear it "
         "through the laptop speakers instead."),
        ("First syllable clipped on VOX", "VOX hang/sensitivity needs "
         "tuning on the radio; lengthen the radio's VOX attack if "
         "available."),
        ("Last syllable cut off on serial PTT", "Increase the "
         "tail-silence padding (recompile with longer pad) or switch "
         "to VOX where the tail is already extended."),
    ])

    b.h3("FCC verification problems")
    b.bullets([
        ("Verify all is disabled", "Status bar shows Offline. "
         "Reconnect; the indicator refreshes every 30 s."),
        ("Row stays unverified even though the callsign is real",
         "Check that the Name field matches a token in the licensee's "
         "name. Hover the empty Verified cell — if the tooltip "
         "lists a licensee, the row was rejected for name-mismatch on "
         "purpose (family-shared GMRS call)."),
    ])

    b.h3("Quick messages")
    b.bullets([
        ("Strip is invisible", "You have no presets saved. Open the "
         "Quick Messages dialog and add at least one phrase."),
        ("Alt+1…Alt+9 fire the wrong preset", "Use Move Up / "
         "Move Down in the Quick Messages dialog to reorder — the "
         "shortcuts follow the saved order."),
    ])


def build_files(b: Builder):
    b.h1("20. File reference")

    b.h3("config.json")
    b.p("Lives in the working directory next to "
        "<font face=\"Courier\">main.py</font>. Plain UTF-8 JSON.")
    b.code(
        '{\n'
        '    "callsign": "WSLZ233",\n'
        '    "name": "Benjamin",\n'
        '    "location": "Lansing, MI",\n'
        '    "voice": "Voices/en_US-ryan-high.onnx",\n'
        '    "tts_length_scale": 1.0,\n'
        '    "input_device": -1,\n'
        '    "output_device": -1,\n'
        '    "whisper_model": "small.en",\n'
        '    "system_monitor_sink": "",\n'
        '    "vad_threshold": 0.5,\n'
        '    "time_format": "24h",\n'
        '    "filter_profanity": true,\n'
        '    "fuzzy_callsign": false,\n'
        '    "listen_only": false,\n'
        '    "monitor_enabled": false,\n'
        '    "monitor_passthrough": false,\n'
        '    "attendance": { "enabled": false },\n'
        '    "gemini_api_key": "",\n'
        '    "ptt_mode": "manual",\n'
        '    "ptt_serial_port": "",\n'
        '    "ptt_serial_line": "RTS",\n'
        '    "radio_service": "GMRS",\n'
        '    "touch_mode": false,\n'
        '    "quick_messages": [\n'
        '        "Radio check",\n'
        '        "Loud and clear",\n'
        '        "Standing by",\n'
        '        "Acknowledged",\n'
        '        "Say again",\n'
        '        "QSY to channel {N}",\n'
        '        "Clear",\n'
        '        "Monitoring",\n'
        '        "Net check-in",\n'
        '        "Emergency traffic"\n'
        '    ]\n'
        '}'
    )
    b.bullets([
        ("input_device / output_device", "-1 means system default. Any "
                                          "other integer is the PortAudio "
                                          "device index. The string "
                                          "<font face=\"Courier\">"
                                          "\"system_monitor\"</font> selects "
                                          "System Audio Output (loopback) — "
                                          "pair with "
                                          "<font face=\"Courier\">"
                                          "system_monitor_sink</font> to "
                                          "target a specific output device."),
        ("system_monitor_sink", "Which audio output to capture when "
                                "<font face=\"Courier\">input_device</font> "
                                "is "
                                "<font face=\"Courier\">\"system_monitor\""
                                "</font>. Empty string (default) uses the OS "
                                "default playback device. On Linux, the "
                                "PulseAudio/PipeWire sink name "
                                "(e.g. "
                                "<font face=\"Courier\">"
                                "alsa_output.pci-0000.analog-stereo"
                                "</font>). On Windows, the output device "
                                "index as a string (e.g. "
                                "<font face=\"Courier\">\"3\"</font>). "
                                "Set via the Monitor Sink dropdown in "
                                "Configuration."),
        ("tts_length_scale", "0.70–1.50. Higher is slower."),
        ("vad_threshold", "0.10–0.95. Higher is stricter."),
        ("listen_only", "Boolean. When true the app blocks every TX "
                        "path at launch (matches the Alt+O toggle on the "
                        "Listen strip). Microphone capture and "
                        "transcription still run."),
        ("monitor_enabled", "Boolean. Default false. When true the "
                            "Monitor toggle (Alt+M) activates automatically "
                            "each time Listen-only mode is turned on. "
                            "Has no effect when Listen only is off (the "
                            "button is disabled in that state)."),
        ("monitor_passthrough", "Boolean. Default false. When true the "
                                "Passthrough toggle is pre-enabled when "
                                "Monitor turns on, sending audio to the "
                                "speaker without the bandpass filter. "
                                "Does not affect VAD or Whisper "
                                "transcription."),
        ("fuzzy_callsign", "Boolean. Off by default. When true a "
                            "detected callsign that differs from a "
                            "saved contact by exactly one same-class "
                            "character is rewritten to the canonical "
                            "form in chat. See section 15.4."),
        ("attendance", "Nested object. <font face=\"Courier\">"
                       "{\"enabled\": &lt;bool&gt;}</font>. Default "
                       "false. Controls the Callsigns Detected dock. Nested so "
                       "future per-session options can land here "
                       "without churning the top-level schema."),
        ("gemini_api_key", "String. Your Google Gemini API key. Empty "
                           "string (default) disables journal generation. "
                           "Set via Settings → Configuration → Gemini "
                           "API Key."),
        ("ptt_mode", "<font face=\"Courier\">manual</font>, <font "
                     "face=\"Courier\">vox</font>, or <font face="
                     "\"Courier\">usb_ftdi</font>."),
        ("ptt_serial_line", "<font face=\"Courier\">RTS</font> or "
                            "<font face=\"Courier\">DTR</font>. Only "
                            "used when "
                            "<font face=\"Courier\">ptt_mode</font> is "
                            "<font face=\"Courier\">usb_ftdi</font>."),
        ("time_format", "<font face=\"Courier\">24h</font> or <font "
                        "face=\"Courier\">12h</font>."),
        ("touch_mode", "Boolean. Default false. When true the app "
                      "launches directly into touch-screen mode (section 5.12). "
                      "The ⊞/⊟ toggle on the service toolbar writes this "
                      "key automatically."),
        ("radio_service", "<font face=\"Courier\">GMRS</font> or "
                          "<font face=\"Courier\">FRS</font>. Default "
                          "GMRS if missing or unknown."),
        ("quick_messages", "Ordered list of phrase strings; first nine "
                            "get Alt+1…Alt+9."),
    ])

    b.h3("contacts.json")
    b.p("Lives alongside <font face=\"Courier\">config.json</font>. "
        "Array of contact objects. The synthetic <i>All</i> row is "
        "always pinned at the top of the in-app dropdown and is "
        "preserved across saves.")
    b.code(
        '[\n'
        '    { "callsign": "All", "name": "Everyone" },\n'
        '    {\n'
        '        "callsign": "WSLZ233",\n'
        '        "name": "Tim",\n'
        '        "location": "Lansing, MI",\n'
        '        "gmrs_callsign": "WSLZ233",\n'
        '        "ham_callsign": "KD9XYZ",\n'
        '        "verified": true,\n'
        '        "verified_at": "2026-05-16T14:32:11Z",\n'
        '        "license_name": "SURNAME, TIMOTHY L"\n'
        '    }\n'
        ']'
    )
    b.bullets([
        ("callsign", "Required. Uppercased on save."),
        ("name", "Free-form."),
        ("location", "Free-form. Auto-backfilled from FCC city on "
                     "successful verification if originally empty."),
        ("gmrs_callsign / ham_callsign", "Cross-references. "
                                          "Auto-populated by FCC "
                                          "verification when the name "
                                          "matches; hand-editable "
                                          "otherwise."),
        ("verified", "Boolean. True only when callsign is active in "
                     "the FCC database AND name matches the licensee."),
        ("verified_at", "ISO-8601 UTC timestamp of the last successful "
                        "lookup."),
        ("license_name", "Raw licensee name returned by the FCC — "
                         "stored so the Verified-cell tooltip can show "
                         "<i>FCC license is held by &hellip;</i>."),
    ])


def build_glossary(b: Builder):
    b.h1("21. Glossary")
    glossary = [
        ("FCC Part 95", "The section of US federal regulations covering "
                       "the Personal Radio Services. Subpart A is "
                       "GMRS; Subpart B is FRS."),
        ("FRS", "Family Radio Service. Unlicensed, no callsign, lower "
                "power, fixed antennas only on most channels."),
        ("GMRS", "General Mobile Radio Service. Licensed (one license "
                 "covers an immediate family), callsign required, up "
                 "to 50 W on repeater inputs."),
        ("kerchunk", "A brief unmodulated key-up with no voice. "
                    "Common when checking repeater access. Silero VAD "
                    "is designed to ignore these."),
        ("NATO phonetic", "The ICAO/NATO spelling alphabet (Alfa, "
                          "Bravo, Charlie&hellip;). Used over voice "
                          "radio to make letters unambiguous."),
        ("Piper", "An offline neural TTS engine using ONNX voices."),
        ("PTT", "Push-to-Talk. The control line that keys the radio "
                "into transmit mode."),
        ("QSL / QSO / QTH / QRZ", "Ham-radio Q-signals. QSL = "
                                  "acknowledge. QSO = radio contact. "
                                  "QTH = location. QRZ = who is calling "
                                  "me?"),
        ("Silero VAD", "An open-source neural voice-activity detector. "
                       "Decides which audio chunks contain speech."),
        ("STT", "Speech-to-text. The Whisper transcription stage."),
        ("TTS", "Text-to-speech. The Piper synthesis stage."),
        ("TTY", "Teletypewriter — the device, and by extension "
                "the abbreviation style (GA, SK, 73, ILY), that "
                "deaf operators have used over phone and radio for "
                "decades."),
        ("VAD", "Voice activity detection. See Silero VAD."),
        ("VOX", "Voice-operated transmit. A radio's auto-key on "
                "detected audio."),
        ("Whisper", "OpenAI's speech-recognition model. faster-whisper "
                    "is the CTranslate2-accelerated CPU runtime used "
                    "by this app."),
    ]
    rows = [[term, definition] for term, definition in glossary]
    b.table(["Term", "Definition"], rows,
            col_widths=[1.3 * inch, 5.45 * inch])


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_manual(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc = make_doc(path)
    styles = build_styles()
    flow = []
    b = Builder(styles=styles, flow=flow)

    build_cover(b)
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())

    sections = [
        build_toc,
        build_about,
        build_requirements,
        build_install,
        build_first_run,
        build_main_window,
        build_journals,
        build_touch_mode,
        build_config_dialog,
        build_contacts_dialog,
        build_quick_messages_dialog,
        build_add_station_dialog,
        build_keyboard,
        build_service_mode,
        build_ptt,
        build_rx,
        build_tx,
        build_callsign_detection,
        build_compliance,
        build_accessibility,
        build_offgrid,
        build_troubleshooting,
        build_files,
        build_glossary,
    ]
    for i, section in enumerate(sections):
        section(b)
        if i < len(sections) - 1:
            flow.append(PageBreak())

    doc.build(flow)


def main(argv):
    out = OUTPUT_PATH
    if len(argv) > 1:
        out = argv[1]
    build_manual(out)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main(sys.argv)
