import os
import tempfile
import time

from sqlalchemy import event

# Set up temporary DB
db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

from doug import store  # noqa: E402
from doug.models import Band, Reason, Verdict  # noqa: E402


def setup_benchmark_data(num_verdicts=200, findings_per_verdict=5):
    # Initialize engine & tables
    store._get_engine()

    # Save verdicts with findings
    for i in range(num_verdicts):
        reasons = [
            Reason(
                rule=f"rule:{j}",
                label=f"Finding label {j} for PR {i}",
                weight=1.0,
                file=f"file_{j}.py",
                severity="high",
            )
            for j in range(findings_per_verdict)
        ]
        verdict = Verdict(
            score=0.5 + (i % 50) / 100.0,
            band=Band.FLAGGED if i % 2 == 0 else Band.CLEARED,
            threshold=0.30,
            reasons=reasons,
        )
        store.save_review(
            repo=f"org/repo_{i % 5}",
            pr_number=i,
            tier="reader",
            verdict=verdict,
            installation_id=100 + (i % 3),
            github_repo_id=1000 + (i % 5),
            head_sha=f"{i:040x}",
            source="app",
        )


def measure():
    engine = store._get_engine()
    query_count = 0

    def before_cursor_execute(
        conn, cursor, statement, parameters, context, executemany
    ):
        nonlocal query_count
        query_count += 1

    event.listen(engine, "before_cursor_execute", before_cursor_execute)

    # Warmup
    store.latest_reviews(limit=200)

    # Measure query count for a single call
    query_count = 0
    results = store.latest_reviews(limit=200)
    measured_queries = query_count

    event.remove(engine, "before_cursor_execute", before_cursor_execute)

    # Timings
    iterations = 50
    start_time = time.perf_counter()
    for _ in range(iterations):
        store.latest_reviews(limit=200)
    end_time = time.perf_counter()

    avg_time_ms = ((end_time - start_time) / iterations) * 1000

    print(f"Results fetched: {len(results)}")
    print(f"SQL Queries per call: {measured_queries}")
    print(
        f"Average execution time: {avg_time_ms:.3f} ms over {iterations} iterations"
    )

    # Cleanup DB
    os.remove(db_path)


if __name__ == "__main__":
    setup_benchmark_data()
    measure()
