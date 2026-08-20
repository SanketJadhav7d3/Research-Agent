"""Benchmark the agent across the question set.

The central experiment: does looping back on low confidence actually produce
better answers? Looping is disabled by setting max_iterations=1 — the gate then
sends every run straight to synthesize after one research round — so both arms
exercise identical code.

    uv run python ../evals/run_evals.py --max-iterations 1 --limit 5
    uv run python ../evals/run_evals.py --max-iterations 3 --limit 5
    uv run python ../evals/run_evals.py --report

Results append to evals/results.jsonl. Runs already recorded for a given
(question, max_iterations) pair are skipped, so the free-tier daily quota can
be spread across several days.
"""

import argparse
import csv
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from agent.graph import graph  # noqa: E402

QUESTIONS = Path(__file__).parent / "questions.csv"
RESULTS = Path(__file__).parent / "results.jsonl"


def load_questions() -> list[dict]:
    with open(QUESTIONS, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_results() -> list[dict]:
    if not RESULTS.exists():
        return []
    with open(RESULTS, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def citation_rate(report: str) -> float:
    """Fraction of substantive paragraphs carrying at least one [n] citation.

    A proxy for how well grounded the prose is. Headings, short lines and the
    appended Sources block are excluded.
    """
    body = report.split("## Sources")[0]
    paragraphs = [
        p.strip()
        for p in body.split("\n\n")
        if len(p.strip()) > 80 and not p.strip().startswith("#")
    ]
    if not paragraphs:
        return 0.0
    cited = sum(1 for p in paragraphs if re.search(r"\[\d+\]", p))
    return cited / len(paragraphs)


def run_one(question: dict, max_iterations: int) -> dict:
    started = time.time()
    record = {
        "id": question["id"],
        "domain": question["domain"],
        "question": question["question"],
        "max_iterations": max_iterations,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        final = graph.invoke(
            {
                "goal": question["question"],
                "iteration": 0,
                "max_iterations": max_iterations,
                "tool_calls": [],
                "findings": [],
                "provider": "",
                "model": "",
                "api_key": "",
            }
        )
    except Exception as exc:  # noqa: BLE001 - recorded, not raised
        record.update(
            {
                "ok": False,
                "error": str(exc)[:300],
                "duration_s": round(time.time() - started, 1),
            }
        )
        return record

    report = final.get("report", "")
    tools = Counter(c["tool"] for c in final.get("tool_calls", []))
    record.update(
        {
            "ok": True,
            "duration_s": round(time.time() - started, 1),
            "confidence": final.get("confidence", 0.0),
            "loops": final.get("iteration", 0),
            "tool_calls": len(final.get("tool_calls", [])),
            "tools_used": dict(tools),
            "findings": len(final.get("findings", [])),
            "citations": len(final.get("citations", [])),
            "citation_rate": round(citation_rate(report), 3),
            "report_words": len(report.split()),
            "gaps_remaining": len(final.get("gaps", [])),
        }
    )
    return record


def cmd_run(args) -> int:
    questions = load_questions()
    if args.limit:
        questions = questions[: args.limit]

    done = {(r["id"], r["max_iterations"]) for r in load_results() if r.get("ok")}
    todo = [q for q in questions if (q["id"], args.max_iterations) not in done]

    if not todo:
        print(
            f"Nothing to do - all {len(questions)} already run at "
            f"max_iterations={args.max_iterations}"
        )
        return 0

    print(f"Running {len(todo)} question(s) at max_iterations={args.max_iterations}")
    print(f"(skipping {len(questions) - len(todo)} already recorded)\n")

    with open(RESULTS, "a", encoding="utf-8") as f:
        for i, q in enumerate(todo, 1):
            print(f"[{i}/{len(todo)}] Q{q['id']} {q['question'][:58]}", flush=True)
            record = run_one(q, args.max_iterations)
            f.write(json.dumps(record) + "\n")
            f.flush()
            if record["ok"]:
                print(
                    f"        conf {record['confidence']:.2f} | "
                    f"{record['loops']} loop(s) | {record['tool_calls']} calls | "
                    f"cite {record['citation_rate']:.0%} | {record['duration_s']}s"
                )
            else:
                print(f"        FAILED: {record['error'][:100]}")
    return 0


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def cmd_report(args) -> int:
    all_results = load_results()
    results = [r for r in all_results if r.get("ok")]
    failed = [r for r in all_results if not r.get("ok")]
    if not results:
        print("No successful results yet. Run some first.")
        return 1

    by_arm = defaultdict(list)
    for r in results:
        by_arm[r["max_iterations"]].append(r)
    arms = sorted(by_arm)

    print("=" * 72)
    print("EVAL SUMMARY")
    print("=" * 72)
    header = f"{'metric':<22}" + "".join(f"{'max_iter=' + str(k):>16}" for k in arms)
    print(header)
    print("-" * 72)

    metrics = [
        ("runs", lambda rs: len(rs), "{:.0f}"),
        ("mean confidence", lambda rs: _mean([r["confidence"] for r in rs]), "{:.2f}"),
        (
            "median confidence",
            lambda rs: statistics.median([r["confidence"] for r in rs]),
            "{:.2f}",
        ),
        (
            "mean citation rate",
            lambda rs: _mean([r["citation_rate"] for r in rs]),
            "{:.0%}",
        ),
        ("mean loops", lambda rs: _mean([r["loops"] for r in rs]), "{:.2f}"),
        ("mean tool calls", lambda rs: _mean([r["tool_calls"] for r in rs]), "{:.1f}"),
        ("mean sources", lambda rs: _mean([r["citations"] for r in rs]), "{:.1f}"),
        ("mean words", lambda rs: _mean([r["report_words"] for r in rs]), "{:.0f}"),
        ("mean duration (s)", lambda rs: _mean([r["duration_s"] for r in rs]), "{:.0f}"),
    ]
    for label, fn, fmt in metrics:
        row = "".join(f"{fmt.format(fn(by_arm[k])):>16}" for k in arms)
        print(f"{label:<22}{row}")

    # Paired comparison: only questions that ran under both arms.
    if len(arms) >= 2:
        low, high = arms[0], arms[-1]
        idx = {a: {r["id"]: r for r in by_arm[a]} for a in (low, high)}
        shared = sorted(set(idx[low]) & set(idx[high]), key=int)
        if shared:
            print()
            print("=" * 72)
            print(
                f"PAIRED COMPARISON - max_iter={low} vs {high} "
                f"({len(shared)} questions run under both)"
            )
            print("=" * 72)
            print(
                f"{'Q':<4}{'conf ' + str(low):>10}{'conf ' + str(high):>10}"
                f"{'d-conf':>9}{'loops':>7}{'d-cite':>9}{'d-calls':>9}"
            )
            print("-" * 72)
            deltas, cite_deltas, extra_calls = [], [], []
            for qid in shared:
                a, b = idx[low][qid], idx[high][qid]
                d = b["confidence"] - a["confidence"]
                dc = b["citation_rate"] - a["citation_rate"]
                dcall = b["tool_calls"] - a["tool_calls"]
                deltas.append(d)
                cite_deltas.append(dc)
                extra_calls.append(dcall)
                print(
                    f"{qid:<4}{a['confidence']:>10.2f}{b['confidence']:>10.2f}"
                    f"{d:>+9.2f}{b['loops']:>7}{dc:>+9.0%}{dcall:>+9}"
                )
            print("-" * 72)
            improved = sum(1 for d in deltas if d > 0.01)
            worsened = sum(1 for d in deltas if d < -0.01)
            print(f"mean d-confidence  {_mean(deltas):+.3f}")
            print(f"mean d-citation    {_mean(cite_deltas):+.1%}")
            print(f"mean extra calls   {_mean(extra_calls):+.1f}")
            print(
                f"improved {improved} | unchanged "
                f"{len(deltas) - improved - worsened} | worse {worsened}"
            )

    if failed:
        print(f"\n{len(failed)} failed run(s):")
        for r in failed[:5]:
            print(
                f"  Q{r['id']} max_iter={r['max_iterations']}: "
                f"{r.get('error', '')[:90]}"
            )
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Run the research agent benchmark.")
    p.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="1 disables loop-back; 3 is the default agent behaviour",
    )
    p.add_argument("--limit", type=int, help="only the first N questions")
    p.add_argument("--report", action="store_true", help="summarise, run nothing")
    args = p.parse_args()
    return cmd_report(args) if args.report else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
