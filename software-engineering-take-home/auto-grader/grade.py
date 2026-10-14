"""Run the public acceptance checks and report evidence, not a hiring decision."""
import json
import subprocess
import sys
import tempfile
import threading
from types import SimpleNamespace
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CATEGORIES = {
    "infrastructure": {"weight": 3, "test_files": ["tests/test_infrastructure.py", "tests/test_ui.py", "tests/test_multimodal.py"]},
    "agent_loop": {"weight": 6, "test_files": ["tests/test_agent_loop.py"]},
    "rag": {"weight": 4, "test_files": ["tests/test_rag.py"]},
    "accuracy": {"weight": 4, "test_files": ["tests/test_accuracy.py"]},
    "guardrails": {"weight": 3, "test_files": ["tests/test_guardrails.py"]},
}
MANUAL_WEIGHT = 80
# 35 sequential requests, each with a 120-second HTTP timeout, plus startup.
ACCURACY_TIMEOUT = 35 * 120 + 60


def read_results(path):
    """Count testcase outcomes once, independently of console summary ordering."""
    counts = dict(passed=0, failed=0, skipped=0, errors=0)
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome = "passed"
        for tag, name in [("error", "errors"), ("failure", "failed"), ("skipped", "skipped")]:
            if case.find(tag) is not None:
                outcome = name
                break
        counts[outcome] += 1
    return counts


def run_pytest(command, *, cwd, timeout):
    """Stream progress while retaining output for the JSON report."""
    lines = []
    with subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace') as process:
        def relay():
            for line in process.stdout:
                lines.append(line)
                print(line, end='', flush=True)
        reader = threading.Thread(target=relay, daemon=True)
        reader.start()
        try:
            returncode = process.wait(timeout=timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join()
    return SimpleNamespace(stdout=''.join(lines), stderr='', returncode=returncode)


def run_category(name, test_files):
    if isinstance(test_files, str):
        test_files = [test_files]
    counts = dict(passed=0, failed=0, skipped=0, errors=0)
    problem = None
    output = ""
    returncode = None
    with tempfile.TemporaryDirectory(prefix="triage-grader-") as directory:
        report = Path(directory) / "pytest.xml"
        try:
            run = run_pytest(
                [sys.executable, "-m", "pytest", *test_files, "-q", "-s", "--tb=short", f"--junitxml={report}"],
                cwd=ROOT, timeout=ACCURACY_TIMEOUT if name == "accuracy" else 900,
            )
            output, returncode = run.stdout + run.stderr, run.returncode
            counts = read_results(report)
            if returncode not in (0, 1):
                problem = f"pytest exited with infrastructure/collection status {returncode}"
            elif returncode == 1 and not (counts["failed"] or counts["errors"]):
                problem = "pytest failed without a recorded failed/error testcase"
        except (OSError, ET.ParseError, subprocess.TimeoutExpired) as exc:
            problem = f"Evaluation did not complete: {type(exc).__name__}: {exc}"
    total = sum(counts.values())
    if total == 0:
        problem = problem or "No tests were evaluated"
    complete = not problem and counts["skipped"] == 0 and counts["errors"] == 0
    return {
        "name": name, **counts, "total": total,
        "score_pct": round(100 * counts["passed"] / total, 4) if total and not problem else 0,
        "complete": bool(complete), "problem": problem, "returncode": returncode, "output": output,
    }


def main():
    auto_weight = sum(c["weight"] for c in CATEGORIES.values())
    assert auto_weight + MANUAL_WEIGHT == 100
    results = {}
    for name, category in CATEGORIES.items():
        print(f"Running {name}...", flush=True)
        results[name] = run_category(name, category["test_files"])
        r = results[name]
        print(f"  {r['passed']}/{r['total']} passed; {r['failed']} failed; {r['errors']} errors; {r['skipped']} skipped")
        if r["problem"]:
            print(f"  {r['problem']}")
    auto_score = sum(results[n]["score_pct"] * c["weight"] / 100 for n, c in CATEGORIES.items())
    complete = all(r["complete"] for r in results.values())
    report = {
        "status": "complete" if complete else "incomplete",
        "auto_score": round(auto_score, 2), "max_auto_score": auto_weight,
        "max_manual_score": MANUAL_WEIGHT, "max_total_score": 100,
        "manual_score": None,
        "note": "Diagnostic only, not a hiring rating or pass/fail threshold. Manual review and live discussion remain required. Skipped/error cases are not passes.",
        "categories": {
            name: {**result, "weight": CATEGORIES[name]["weight"],
                   "weighted_score": round(result["score_pct"] * CATEGORIES[name]["weight"] / 100, 2)}
            for name, result in results.items()
        },
    }
    directory = ROOT / "results"
    directory.mkdir(exist_ok=True)
    (directory / "grade_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{report['status'].upper()}: {auto_score:.2f}/{auto_weight} automated; manual review pending ({MANUAL_WEIGHT}).")
    print(report["note"])
    print(f"Report: {directory / 'grade_report.json'}")
    if not complete:
        return 2
    return 1 if any(r["failed"] for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
