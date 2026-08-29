"""The reader-fallback alert is a contract across three files, pinned here.

reader.py prints one stderr line when a read degrades to the deterministic
score; monitoring.sh builds a log-based metric over exactly those bytes and
an alert policy over the metric. Nothing at runtime checks that the printed
line and the metric filter still agree — a rewording on either side leaves
the alert green while counting nothing, which is the silent-reader failure
(#274) wearing the fix's clothes. So the agreement is pinned by test, the
same posture as test_deploy_gcp.py's identity pins.
"""

from pathlib import Path

from doug import reader

API_DIR = Path(__file__).resolve().parents[1]
MONITORING = (API_DIR / "deploy" / "monitoring.sh").read_text()
REVIEW = (API_DIR / "doug" / "review.py").read_text()
API_PY = (API_DIR / "doug" / "api.py").read_text()


def test_the_fallback_token_is_the_same_bytes_in_code_and_alert():
    """monitoring.sh matches on the literal token, so the literal must appear
    there verbatim: once where the audit resolves the metric is not needed
    (the shell variable), and its FALLBACK_TOKEN assignment must equal the
    Python constant byte for byte."""
    assert f'FALLBACK_TOKEN="{reader.FALLBACK_LOG_TOKEN}"' in MONITORING


def test_both_readererror_catch_sites_print_the_token_line():
    """The two places a review degrades to the deterministic score are
    review.py's _read and api.py's score/read route. Each must emit the
    stderr line the metric counts — via the constant, never a re-typed
    string, so the token cannot fork."""
    for source, name in ((REVIEW, "review.py"), (API_PY, "api.py")):
        catch = source.split("except reader.ReaderError as e:", 1)
        assert len(catch) == 2, f"{name} no longer catches ReaderError?"
        # The print belongs to the catch block: it must appear before the
        # fallback verdict is returned, in the first few lines after the
        # except.
        block = catch[1][:400]
        assert "reader.FALLBACK_LOG_TOKEN" in block, (
            f"{name} degrades to deterministic without printing the line "
            "the reader-fallback alert counts"
        )
        assert "file=sys.stderr" in block


def test_verify_and_apply_watch_the_same_metric_namespace():
    """The audit resolves the metric by its filter and requires the policy to
    watch logging.googleapis.com/user/<name>; the creator writes the same
    namespace. Both halves must name it or verify and apply drift — one
    greening on a policy the other would never create."""
    assert MONITORING.count("logging.googleapis.com/user/") >= 2


def test_the_metric_filter_is_scoped_to_doug_api():
    """A metric counting the token from every service would fire on a future
    worker's dogfooding noise; the audit and the creator both pin the
    doug-api service."""
    creator = MONITORING.split("creating log-based metric", 1)[1]
    assert 'service_name=\\"doug-api\\"' in creator
