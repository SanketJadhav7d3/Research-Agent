"""Development client for the sandbox service.

The sandbox has no route to the host, so it cannot be curled from a browser or
a terminal on your machine. This runs inside the backend container, which is
the only thing that can reach it — and is the same path the agent will use.

    # inline
    docker compose exec -T backend python dev_sandbox.py "print(2 + 2)"

    # from stdin, for anything multi-line
    docker compose exec -T backend python dev_sandbox.py <<'EOF'
    import plotly.express as px
    emit_chart(px.line(x=[1, 2, 3], y=[4, 5, 6]), "demo")
    EOF

    # with data, which arrives as the `findings` variable
    docker compose exec -T backend python dev_sandbox.py --data '[{"v": 1}]' "print(findings)"

    # built-in example, end to end
    docker compose exec -T backend python dev_sandbox.py --demo
"""

import argparse
import json
import sys

import httpx

SANDBOX_URL = "http://sandbox:8080/execute"

DEMO_DATA = [
    {
        "title": "ACME Corp quarterly revenue",
        "url": "https://example.com/acme",
        "rows": [
            {"quarter": "2025-Q1", "revenue_m": 412, "margin": 0.18},
            {"quarter": "2025-Q2", "revenue_m": 455, "margin": 0.21},
            {"quarter": "2025-Q3", "revenue_m": 431, "margin": 0.19},
            {"quarter": "2025-Q4", "revenue_m": 502, "margin": 0.24},
            {"quarter": "2026-Q1", "revenue_m": 548, "margin": 0.26},
        ],
    }
]

DEMO_CODE = '''
import plotly.graph_objects as go

rows = findings[0]["rows"]
quarters = [r["quarter"] for r in rows]
revenue = [r["revenue_m"] for r in rows]

growth = (revenue[-1] / revenue[0] - 1) * 100
print(f"revenue grew {growth:.1f}% across {len(rows)} quarters")
print("best quarter:", max(rows, key=lambda r: r["revenue_m"])["quarter"])

fig = go.Figure(go.Bar(x=quarters, y=revenue))
fig.update_layout(title="ACME quarterly revenue (€m)")
emit_chart(fig, "ACME quarterly revenue")
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="Python to run. Omit to read stdin.")
    parser.add_argument("--data", help="JSON exposed to the code as `findings`.")
    parser.add_argument("--demo", action="store_true", help="Run the built-in example.")
    parser.add_argument("--raw", action="store_true", help="Print the whole JSON response.")
    args = parser.parse_args()

    if args.demo:
        code, data = DEMO_CODE, DEMO_DATA
    else:
        code = args.code if args.code else sys.stdin.read()
        data = json.loads(args.data) if args.data else []

    if not code.strip():
        parser.error("no code given (pass it as an argument, or pipe it in)")

    try:
        response = httpx.post(
            SANDBOX_URL, json={"code": code, "data": data}, timeout=120.0
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"could not reach the sandbox: {exc}")
        print("is it up? docker compose ps sandbox")
        return 1

    result = response.json()

    if args.raw:
        print(json.dumps(result, indent=2)[:8000])
        return 0

    if result.get("stdout"):
        print("--- output ---")
        print(result["stdout"].rstrip())

    if result.get("error"):
        print(f"--- failed: {result['error']} ---")
        print((result.get("stderr") or "").rstrip())
    elif result.get("stderr"):
        print("--- notes ---")
        print(result["stderr"].rstrip())

    charts = result.get("charts") or []
    if charts:
        print(f"--- {len(charts)} chart(s) ---")
        for i, chart in enumerate(charts, 1):
            if chart["format"] == "plotly":
                spec = chart["spec"]
                traces = spec.get("data", [])
                kinds = ", ".join(t.get("type", "scatter") for t in traces) or "none"
                points = sum(len(t.get("y", []) or []) for t in traces)
                size = len(json.dumps(spec))
                print(f"  {i}. {chart['title']!r} — plotly, {kinds}, "
                      f"{points} points, {size / 1000:.1f}kB")
            else:
                size = len(chart.get("data", "")) * 3 // 4
                print(f"  {i}. {chart['title']!r} — png, {size / 1000:.0f}kB")

    if result.get("truncated"):
        print("(output was truncated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
