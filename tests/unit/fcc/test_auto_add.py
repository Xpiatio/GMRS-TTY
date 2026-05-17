"""``CallsignLookupWorker`` is a thin background-thread wrapper around
``verify_callsign``. The point of these tests is to lock in the contract the
UI layer relies on:

* ``run()`` invokes ``verify_callsign`` with the worker's callsign + name.
* The signal emits the original callsign / transcript-derived name + location
  plus the ``VerificationResult`` so the receiver doesn't have to maintain
  per-lookup state.
* The class can be instantiated without spinning up an actual QThread (so
  MainWindow tests can swap in a synchronous fake).
"""
import os
from unittest.mock import patch

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gmrs_tty.fcc import auto_add  # noqa: E402
from gmrs_tty.fcc.crossref import VerificationResult  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    # Other UI tests in this suite use ``QApplication``. Reusing the same
    # subclass keeps a single process-wide instance — Qt aborts if a test
    # constructs ``QCoreApplication`` after ``QApplication`` exists.
    return QApplication.instance() or QApplication([])


class TestCallsignLookupWorker:
    def test_run_invokes_verify_with_callsign_and_name(self, qapp):
        worker = auto_add.CallsignLookupWorker("WSLZ233", "Benjamin", "Jenison")
        fake = VerificationResult(status="verified", license_name="Zomberg, Benjamin J")
        with patch.object(auto_add, "verify_callsign", return_value=fake) as vc:
            received = []
            worker.result_ready.connect(
                lambda cs, n, loc, r: received.append((cs, n, loc, r))
            )
            worker.run()  # synchronous to keep the test deterministic
        vc.assert_called_once_with("WSLZ233", "Benjamin")
        assert received == [("WSLZ233", "Benjamin", "Jenison", fake)]

    def test_result_signal_carries_original_transcript_metadata(self, qapp):
        """The receiver builds the contact dict from these fields, so they
        must survive even when the lookup result has its own license_name."""
        worker = auto_add.CallsignLookupWorker("KE8RXN", "Collin", "Grand Rapids")
        fake = VerificationResult(
            status="verified",
            license_name="Hoekema, Collin J",
            license_city="GRAND RAPIDS",
        )
        with patch.object(auto_add, "verify_callsign", return_value=fake):
            captured = []
            worker.result_ready.connect(
                lambda cs, n, loc, r: captured.append((cs, n, loc, r.license_name))
            )
            worker.run()
        assert captured == [("KE8RXN", "Collin", "Grand Rapids", "Hoekema, Collin J")]
