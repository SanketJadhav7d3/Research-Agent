"""Code prepended to every snippet before execution.

Two jobs: give the model a chart API to call, and make the collected results
recoverable by the parent process after the subprocess exits.

Results go to a file rather than stdout because the snippet's own prints share
stdout, and a chart's JSON would be indistinguishable from something the model
decided to print.
"""

PREAMBLE = r'''
import json as _json
import os as _os
import sys as _sys

# Headless before pyplot is imported anywhere, or matplotlib looks for a display.
import matplotlib as _mpl
_mpl.use("Agg")

_CHARTS = []
_CHART_LIMIT = 4
_SPEC_LIMIT = 600_000     # bytes of serialised chart, per chart


def emit_chart(fig, title=""):
    """Add a figure to the report.

    Accepts a plotly figure (preferred — interactive in the report) or a
    matplotlib figure (rendered as a static image).
    """
    if len(_CHARTS) >= _CHART_LIMIT:
        print(f"[sandbox] chart ignored: limit of {_CHART_LIMIT} reached", file=_sys.stderr)
        return

    # Duck-typed rather than isinstance: plotly may not be imported by the
    # snippet, and importing it here to do the check costs ~300ms.
    if hasattr(fig, "to_plotly_json"):
        spec = fig.to_plotly_json()
        payload = _json.dumps(spec, default=str)
        if len(payload) > _SPEC_LIMIT:
            print(
                f"[sandbox] chart dropped: {len(payload) // 1000}kB exceeds the "
                f"{_SPEC_LIMIT // 1000}kB limit. Downsample the series and retry.",
                file=_sys.stderr,
            )
            return
        _CHARTS.append({"format": "plotly", "title": title, "spec": _json.loads(payload)})
        return

    if hasattr(fig, "savefig"):
        import base64 as _b64
        import io as _io
        buf = _io.BytesIO()
        fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", transparent=True)
        data = buf.getvalue()
        if len(data) > _SPEC_LIMIT:
            print("[sandbox] chart dropped: image too large", file=_sys.stderr)
            return
        _CHARTS.append({
            "format": "png",
            "title": title,
            "data": _b64.b64encode(data).decode(),
        })
        return

    raise TypeError(
        f"emit_chart expected a plotly or matplotlib figure, got {type(fig).__name__}"
    )


def _flush_charts():
    path = _os.environ.get("SANDBOX_RESULT_PATH")
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(_CHARTS, fh)
    except Exception as exc:
        print(f"[sandbox] could not write charts: {exc}", file=_sys.stderr)


# Runs even if the snippet raises, so charts produced before a later failure
# are not lost — the model often plots successfully and then trips on something
# afterwards.
import atexit as _atexit
_atexit.register(_flush_charts)


def _load_findings():
    """Every finding gathered in this run, untruncated."""
    with open("/data/findings.json", encoding="utf-8") as fh:
        return _json.load(fh)


findings = None
try:
    findings = _load_findings()
except Exception:
    pass
'''
