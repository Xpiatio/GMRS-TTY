"""Background FCC lookup used to auto-add unknown stations to contacts.

When the STT pipeline surfaces a callsign that isn't in the contact list AND
the transcript carried a plausible operator name, we'd like to ask the FCC
crossref API whether that name actually matches the licensee. A name match
means we can drop the contact straight into ``contacts.json`` with full GMRS
+ HAM cross-references; a mismatch (or any other non-``verified`` status)
leaves the pending '+ Add' pill in place so the operator can decide.

The lookup must not block the UI thread — ``verify_callsign`` can sit on a
five-second HTTP timeout. ``CallsignLookupWorker`` is a thin QThread wrapper
that hands the result back to the main thread via a Qt signal so the auto-add
plumbing can stay on the UI thread (where ``contacts.json`` and the
target-dropdown widgets live).
"""
from PySide6.QtCore import QThread, Signal

from gmrs_tty.fcc.crossref import verify_callsign


class CallsignLookupWorker(QThread):
    """Runs one ``verify_callsign`` call on a background thread.

    The transcript-derived ``name`` and ``location`` are passed through verbatim
    on the result signal so the receiver can build the contact dict without
    holding extra state per in-flight lookup.
    """

    # (callsign, transcript_name, transcript_location, VerificationResult).
    # The result is passed as ``object`` because PySide6 cannot statically
    # type-erase the dataclass; receivers downcast as needed.
    result_ready = Signal(str, str, str, object)

    def __init__(self, callsign, name, location, parent=None):
        super().__init__(parent)
        self.callsign = callsign
        self.name = name
        self.location = location

    def run(self):
        result = verify_callsign(self.callsign, self.name)
        self.result_ready.emit(self.callsign, self.name, self.location, result)
