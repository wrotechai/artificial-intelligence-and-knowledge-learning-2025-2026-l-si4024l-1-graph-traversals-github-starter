#!/usr/bin/env python3
"""
Autograder for AI&KE Assignment #1 — Graph Traversals
=====================================================

Runs the student's solution via run_task1.sh / run_task2.sh, parses stdout/stderr,
and validates against expected results. Exit code 0 = pass, 1 = fail.

Usage:
    python3 tests/autograder.py <TEST_ID>

Test IDs: T1_BASIC, T1_PARENT_STATION, T1_DWELL, T1_CALENDAR, T1_TRANSFERS_ZERO,
          T1_TRANSFERS_MULTI, T2_BASIC, T2_3STOPS, T2_TRANSFERS
"""

import subprocess
import sys
import re
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TIMEOUT = 300  # seconds per test


# ── Output Parsing ────────────────────────────────────────────

TIME_RE = re.compile(r'(\d{1,2}:\d{2}(?::\d{2})?)')
LINE_NAME_RE = re.compile(r'\b(D\d+|KD\s+\w+)\b', re.IGNORECASE)


def time_to_minutes(t: str) -> float:
    """Convert HH:MM or HH:MM:SS to minutes since midnight."""
    parts = t.split(':')
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return h * 60 + m + s / 60


def parse_stdout(stdout: str) -> dict:
    """Parse student's stdout into structured segment data.

    Returns dict with:
        segments:       list of raw segment lines (lines containing >=2 time patterns)
        all_lines_used: set of route/line names found (e.g. {'D6', 'D1'})
        first_dep:      first departure time as minutes (or None)
        last_arr:       last arrival time as minutes (or None)
        last_arr_str:   last arrival time as original string (or None)
        station_names:  all text in segment lines (for substring station checks)
    """
    segments = []
    all_lines_used = set()
    all_text = []

    for line in stdout.strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        times = TIME_RE.findall(line)
        if len(times) >= 2:
            segments.append({'raw': line, 'times': times})
            for m in LINE_NAME_RE.finditer(line):
                all_lines_used.add(m.group(1).strip())
            all_text.append(line)

    first_dep = None
    last_arr = None
    last_arr_str = None
    if segments:
        first_dep = time_to_minutes(segments[0]['times'][0])
        last_arr_str = segments[-1]['times'][-1]
        last_arr = time_to_minutes(last_arr_str)

    return {
        'segments': segments,
        'all_lines_used': all_lines_used,
        'first_dep': first_dep,
        'last_arr': last_arr,
        'last_arr_str': last_arr_str,
        'full_text': '\n'.join(all_text),
        'raw_stdout': stdout,
    }


def parse_stderr(stderr: str) -> dict:
    """Extract criterion value and computation time from stderr.

    Looks for numeric values. Returns best-guess criterion value.
    """
    numbers = re.findall(r'(\d+\.?\d*)', stderr)
    return {
        'raw': stderr,
        'numbers': [float(n) for n in numbers],
    }


# ── Solution Runner ───────────────────────────────────────────

def run_solution(task: int, args: list[str], date: str = '2026-03-04') -> tuple[str, str, int]:
    """Run the student's solution and return (stdout, stderr, returncode)."""
    script = os.path.join(REPO_ROOT, f'run_task{task}.sh')
    if not os.path.isfile(script):
        print(f"FAIL: {script} not found. Create it to tell the autograder how to run your solution.")
        sys.exit(1)

    env = os.environ.copy()
    env['GTFS_DATE'] = date

    try:
        result = subprocess.run(
            ['bash', script] + args,
            capture_output=True, text=True, timeout=TIMEOUT,
            cwd=REPO_ROOT, env=env,
        )
    except subprocess.TimeoutExpired:
        print(f"FAIL: Solution timed out after {TIMEOUT}s")
        sys.exit(1)
    except Exception as e:
        print(f"FAIL: Could not run solution: {e}")
        sys.exit(1)

    if result.returncode != 0 and not result.stdout.strip():
        print(f"FAIL: Solution exited with code {result.returncode}")
        if result.stderr.strip():
            # Show first 500 chars of stderr for debugging
            print(f"stderr: {result.stderr[:500]}")
        sys.exit(1)

    return result.stdout, result.stderr, result.returncode


# ── Assertion Helpers ─────────────────────────────────────────

class TestFailure(Exception):
    pass


def assert_has_output(parsed):
    if not parsed['segments']:
        raise TestFailure(
            "No route segments found in stdout. Expected lines with departure/arrival times.\n"
            f"Raw stdout:\n{parsed['raw_stdout'][:300]}"
        )


def assert_station_in_output(parsed, station_name, label=""):
    text = parsed['full_text'].lower()
    # Try exact match first, then partial (first word)
    if station_name.lower() in text:
        return
    # Try first significant word (skip "Wrocław" which appears everywhere)
    words = station_name.split()
    if len(words) > 1 and words[-1].lower() in text:
        return
    raise TestFailure(
        f"Station '{station_name}' not found in output segments{' (' + label + ')' if label else ''}.\n"
        f"Output:\n{parsed['full_text'][:300]}"
    )


def assert_line_used(parsed, line_name):
    if line_name not in parsed['all_lines_used']:
        raise TestFailure(
            f"Expected line '{line_name}' in output, found: {parsed['all_lines_used'] or '(none)'}.\n"
            f"Output:\n{parsed['full_text'][:300]}"
        )


def assert_arrival_time(parsed, expected_hhmm, tolerance_min=5):
    """Check that last arrival time is within tolerance of expected."""
    if parsed['last_arr'] is None:
        raise TestFailure("No arrival time found in output.")
    expected_min = time_to_minutes(expected_hhmm)
    actual_min = parsed['last_arr']
    diff = abs(actual_min - expected_min)
    if diff > tolerance_min:
        raise TestFailure(
            f"Arrival time {parsed['last_arr_str']} (={actual_min:.0f} min), "
            f"expected ~{expected_hhmm} (={expected_min:.0f} min), "
            f"difference {diff:.0f} min exceeds tolerance of {tolerance_min} min."
        )


def assert_max_transfers(parsed, max_transfers):
    """Check that number of distinct lines used implies <= max_transfers."""
    n_lines = len(parsed['all_lines_used'])
    if n_lines == 0:
        return  # Can't determine
    transfers = n_lines - 1
    if transfers > max_transfers:
        raise TestFailure(
            f"Found {n_lines} distinct lines ({parsed['all_lines_used']}), "
            f"implying {transfers} transfers, but expected at most {max_transfers}."
        )


def assert_min_transfers(parsed, min_transfers):
    """Check that the route uses enough lines to imply >= min_transfers."""
    n_lines = len(parsed['all_lines_used'])
    if n_lines == 0:
        return
    transfers = n_lines - 1
    if transfers < min_transfers:
        raise TestFailure(
            f"Found {n_lines} distinct lines ({parsed['all_lines_used']}), "
            f"implying {transfers} transfers, but expected at least {min_transfers}."
        )


def assert_travel_time_range(parsed, start_time_str, min_minutes, max_minutes):
    """Check total travel time is within an expected range."""
    if parsed['last_arr'] is None:
        raise TestFailure("No arrival time found in output.")
    start_min = time_to_minutes(start_time_str)
    travel = parsed['last_arr'] - start_min
    if travel < min_minutes or travel > max_minutes:
        raise TestFailure(
            f"Travel time {travel:.0f} min, expected between {min_minutes} and {max_minutes} min."
        )


def assert_visits_all_stops(parsed, stop_names):
    """Check that all required stops appear in the output (for TSP)."""
    text = parsed['full_text'].lower()
    missing = []
    for stop in stop_names:
        if stop.lower() not in text:
            # Try partial match (last word of multi-word name)
            words = stop.split()
            if not any(w.lower() in text for w in words if len(w) > 3):
                missing.append(stop)
    if missing:
        raise TestFailure(
            f"TSP route does not visit all required stops. Missing: {missing}\n"
            f"Output:\n{parsed['full_text'][:500]}"
        )


def assert_outputs_differ(parsed1, parsed2, label1, label2):
    """Check that two runs produce different results (e.g., different dates)."""
    # Compare arrival times
    if parsed1['last_arr'] is not None and parsed2['last_arr'] is not None:
        if abs(parsed1['last_arr'] - parsed2['last_arr']) > 1:
            return  # They differ — good
    # Compare full text
    if parsed1['full_text'].strip() != parsed2['full_text'].strip():
        return  # They differ — good
    raise TestFailure(
        f"Expected different results for {label1} vs {label2}, but outputs are identical.\n"
        f"This suggests calendar/date filtering is not working.\n"
        f"{label1} arrival: {parsed1['last_arr_str']}\n"
        f"{label2} arrival: {parsed2['last_arr_str']}"
    )


# ── Test Definitions ──────────────────────────────────────────

def test_t1_basic():
    """S1.1: Wrocław Główny → Jelenia Góra, criterion=t, 06:00, Wednesday.
    Expects: direct D6 train, arrival ~08:26, 0 transfers."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Jelenia Góra", "t", "06:00:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Jelenia Góra", "destination")
    assert_line_used(parsed, "D6")
    assert_arrival_time(parsed, "08:26", tolerance_min=5)
    assert_max_transfers(parsed, 0)
    print("PASS: Direct connection found (D6, arrival ~08:26, 0 transfers)")


def test_t1_parent_station():
    """S1.2: Wrocław Główny → Legnica, criterion=t, 07:40, Wednesday.
    Expects: D1 at ~07:45, verifies parent_station handling."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Legnica", "t", "07:40:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Legnica", "destination")
    assert_line_used(parsed, "D1")
    # D1 departs 07:45, arrival at Legnica ~09:00-09:15
    assert_travel_time_range(parsed, "07:40:00", 60, 120)
    print("PASS: Multi-platform station handled correctly (D1 to Legnica)")


def test_t1_dwell():
    """S1.3: Trutnov hl. n. → Kamienna Góra, criterion=t, 13:30, Wednesday.
    Expects: arrival ~14:31, travel time ~61 min (NOT ~50 — that means dwell time bug)."""
    stdout, stderr, _ = run_solution(1, ["Trutnov hl. n.", "Kamienna Góra", "t", "13:30:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_arrival_time(parsed, "14:31", tolerance_min=5)
    # Key check: travel time must be ~61 min, not ~50
    assert_travel_time_range(parsed, "13:30:00", 55, 70)
    print("PASS: Dwell time handled correctly (arrival ~14:31, ~61 min travel)")


def test_t1_calendar():
    """S1.4: Wrocław Główny → Kąty Wrocławskie, criterion=t, 07:50.
    Compare Wednesday (2026-03-04) vs Saturday (2026-03-07) — results MUST differ."""
    stdout_wed, _, _ = run_solution(
        1, ["Wrocław Główny", "Kąty Wrocławskie", "t", "07:50:00"], date='2026-03-04'
    )
    stdout_sat, _, _ = run_solution(
        1, ["Wrocław Główny", "Kąty Wrocławskie", "t", "07:50:00"], date='2026-03-07'
    )
    parsed_wed = parse_stdout(stdout_wed)
    parsed_sat = parse_stdout(stdout_sat)

    assert_has_output(parsed_wed)
    assert_has_output(parsed_sat)
    assert_outputs_differ(parsed_wed, parsed_sat, "Wednesday", "Saturday")
    print("PASS: Calendar filtering works (Wednesday ≠ Saturday results)")


def test_t1_transfers_zero():
    """S1.5: Wrocław Główny → Jelenia Góra, criterion=p, 06:00, Wednesday.
    Expects: 0 transfers (direct D6 or D60 connection exists)."""
    stdout, stderr, _ = run_solution(1, ["Wrocław Główny", "Jelenia Góra", "p", "06:00:00"])
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Jelenia Góra", "destination")
    assert_max_transfers(parsed, 0)
    print("PASS: Transfer criterion finds 0-transfer route (direct connection)")


def test_t1_transfers_multi():
    """Szklarska Poręba Górna → Brzeg, criterion=p, 06:00, Wednesday.
    Expects: route found with ≥1 transfer (no direct connection)."""
    stdout, stderr, _ = run_solution(
        1, ["Szklarska Poręba Górna", "Brzeg", "p", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_station_in_output(parsed, "Brzeg", "destination")
    assert_min_transfers(parsed, 1)
    print("PASS: Multi-transfer route found for transfer criterion")


def test_t2_basic():
    """S2.1: TSP from Wrocław Główny visiting [Wrocław Grabiszyn, Kąty Wrocławskie].
    Both on line D6. Expects: visits both stops and returns."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Wrocław Grabiszyn;Kąty Wrocławskie", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Grabiszyn", "Kąty Wrocławskie"])
    print("PASS: TSP visits both stops on D6 line")


def test_t2_3stops():
    """S2.2: TSP from Wrocław Główny visiting [Jelenia Góra, Legnica, Brzeg].
    Three different directions. Expects: visits all 3 stops."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Jelenia Góra;Legnica;Brzeg", "t", "06:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Jelenia Góra", "Legnica", "Brzeg"])
    print("PASS: TSP visits all 3 stops in different directions")


def test_t2_transfers():
    """S2.5: TSP from Wrocław Główny visiting [Jelenia Góra, Legnica], criterion=p.
    Expects: route found, visits both stops, transfer count is reasonable."""
    stdout, stderr, _ = run_solution(
        2, ["Wrocław Główny", "Jelenia Góra;Legnica", "p", "08:00:00"]
    )
    parsed = parse_stdout(stdout)

    assert_has_output(parsed)
    assert_visits_all_stops(parsed, ["Jelenia Góra", "Legnica"])
    print("PASS: TSP with transfer criterion visits both stops")


# ── Test Registry ─────────────────────────────────────────────

TESTS = {
    'T1_BASIC':           test_t1_basic,
    'T1_PARENT_STATION':  test_t1_parent_station,
    'T1_DWELL':           test_t1_dwell,
    'T1_CALENDAR':        test_t1_calendar,
    'T1_TRANSFERS_ZERO':  test_t1_transfers_zero,
    'T1_TRANSFERS_MULTI': test_t1_transfers_multi,
    'T2_BASIC':           test_t2_basic,
    'T2_3STOPS':          test_t2_3stops,
    'T2_TRANSFERS':       test_t2_transfers,
}


# ── Main ──────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in TESTS:
        print(f"Usage: python3 tests/autograder.py <TEST_ID>")
        print(f"Available tests: {', '.join(TESTS.keys())}")
        sys.exit(1)

    test_id = sys.argv[1]
    test_fn = TESTS[test_id]

    try:
        test_fn()
        sys.exit(0)
    except TestFailure as e:
        print(f"FAIL [{test_id}]: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR [{test_id}]: Unexpected error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
