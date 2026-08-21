"""Runs one snippet under resource limits and returns what it produced.

Everything here exists because the code being run is adversarial by
construction: it was written by a model that read arbitrary web pages, and a
page can try to talk that model into doing something hostile.

The controls are layered, and the ordering is deliberate — a wall-clock
timeout alone stops none of the interesting attacks. A fork bomb spawns
faster than it can be killed, a memory balloon takes the whole container
down with it, and neither shows up as a slow request until it is too late.
"""

import json
import logging
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from preamble import PREAMBLE

log = logging.getLogger(__name__)

# Wall clock. Generous enough for a pandas parse over a few MB, short enough
# that a stuck run does not hold an instance open.
TIMEOUT_SECONDS = 30

# CPU seconds. Lower than the wall clock: a snippet that spins is the case this
# is for, and it should die before the wall-clock kill has to step in.
CPU_SECONDS = 25

# Address space, not resident memory. The distinction matters: OpenBLAS
# reserves a large virtual arena per thread when numpy loads, so a limit tuned
# to plausible *usage* stops numpy importing at all. Pinned to one thread below,
# which keeps the reservation small, and set below the container's ceiling so a
# runaway allocation raises MemoryError in the snippet rather than triggering a
# cgroup OOM kill that would take the whole service down with it.
MAX_MEMORY = 1536 * 1024 * 1024
MAX_PROCESSES = 64                  # fork bombs
MAX_FILE_SIZE = 32 * 1024 * 1024    # per file written

# Output caps. Applied while reading, not after — a snippet that prints in a
# loop would otherwise fill this process's memory before we ever truncate.
MAX_OUTPUT_CHARS = 20_000
MAX_TRACEBACK_CHARS = 2_000


def _apply_limits() -> None:
    """Applied in the child, after fork, before exec.

    Anything raising here kills the child rather than the service, which is the
    behaviour we want — a snippet that somehow prevents its own sandboxing must
    not run.
    """
    # Soft below hard on purpose. At the soft limit the kernel sends SIGXCPU,
    # which terminates with a signal we can name; if soft and hard are equal it
    # follows straight up with SIGKILL and the exit code is indistinguishable
    # from an out-of-memory kill.
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 5))
    resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY, MAX_MEMORY))
    resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_FILE_SIZE, MAX_FILE_SIZE))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    # New session, so a kill reaches everything the snippet spawned rather than
    # just the interpreter that spawned it.
    os.setsid()


def _clip(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    half = limit // 2
    return f"{text[:half]}\n\n[... {len(text) - limit} characters omitted ...]\n\n{text[-half:]}", True


def _extract_error(stderr: str) -> tuple[str | None, str]:
    """Pull the exception name out of a traceback, if there is one.

    The model gets the last frames rather than the first: the top of a
    traceback is usually our preamble, and the useful part is at the bottom.
    """
    if "Traceback (most recent call last)" not in stderr:
        # A SyntaxError is raised at compile time and prints no traceback
        # header, so it would otherwise come back as a bare exit code. The
        # model fixes a named error far more reliably than a numbered one.
        for line in reversed(stderr.strip().splitlines()):
            match = re.match(r"^(\w*(?:Error|Exception|Warning)):", line.strip())
            if match:
                clipped, _ = _clip(stderr[-MAX_TRACEBACK_CHARS:], MAX_TRACEBACK_CHARS)
                return match.group(1), clipped
        return None, stderr

    tail = stderr.rstrip().splitlines()
    name = None
    for line in reversed(tail):
        stripped = line.strip()
        if stripped and not line.startswith(" "):
            name = stripped.split(":", 1)[0]
            break

    clipped, _ = _clip(stderr[-MAX_TRACEBACK_CHARS:], MAX_TRACEBACK_CHARS)
    return name, clipped


def execute(code: str, data: list | dict | None = None) -> dict:
    """Run one snippet. Never raises — failures are part of the result."""
    workdir = Path(tempfile.mkdtemp(prefix="run-", dir="/tmp"))
    result_path = workdir / "charts.json"

    try:
        # The snippet reads its data from a fixed path, so the model does not
        # have to be told a different filename every call.
        data_dir = Path("/data")
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "findings.json").write_text(
            json.dumps(data if data is not None else [], default=str),
            encoding="utf-8",
        )

        script = workdir / "snippet.py"
        script.write_text(PREAMBLE + "\n\n" + code, encoding="utf-8")

        env = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": str(workdir),
            "TMPDIR": str(workdir),
            "SANDBOX_RESULT_PATH": str(result_path),
            "MPLCONFIGDIR": str(workdir / "mpl"),
            "PYTHONDONTWRITEBYTECODE": "1",
            # One BLAS thread. Cuts the virtual arena numpy reserves at import
            # to something that fits under RLIMIT_AS, and stops a snippet
            # spinning up a thread per core on a shared instance.
            "OPENBLAS_NUM_THREADS": "1",
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
            # Unbuffered, so output survives a kill mid-run.
            "PYTHONUNBUFFERED": "1",
        }

        timed_out = False
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(script)],
                cwd=workdir,
                env=env,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=TIMEOUT_SECONDS,
                preexec_fn=_apply_limits,
            )
            stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            returncode = -1

        stdout, truncated = _clip(stdout, MAX_OUTPUT_CHARS)

        charts = []
        if result_path.exists():
            try:
                charts = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("unreadable chart output: %s", exc)

        if timed_out:
            error = "Timeout"
            stderr = (
                f"Execution exceeded {TIMEOUT_SECONDS}s and was killed. Work on a "
                f"smaller slice of the data, or avoid loops over every row."
            )
        elif returncode != 0:
            error, stderr = _extract_error(stderr)
            # A limit breach kills by signal, so there is no traceback to read.
            if error is None:
                error = _signal_error(returncode)
                stderr = stderr or _signal_hint(returncode)
        else:
            error = None
            stderr, _ = _clip(stderr, MAX_TRACEBACK_CHARS)

        log.info(
            "executed: rc=%s error=%s charts=%d stdout=%dch",
            returncode, error, len(charts), len(stdout),
        )
        return {
            "stdout": stdout,
            "stderr": stderr,
            "error": error,
            "charts": charts,
            "truncated": truncated,
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _signal_error(returncode: int) -> str:
    if returncode == -9:
        return "Killed"
    if returncode == -24:      # SIGXCPU
        return "CPULimitExceeded"
    if returncode == -25:      # SIGXFSZ
        return "FileSizeLimitExceeded"
    return f"ExitCode{returncode}"


def _signal_hint(returncode: int) -> str:
    if returncode == -24:
        return (
            f"The code used more than {CPU_SECONDS}s of CPU and was stopped. "
            f"Vectorise the work or process fewer rows."
        )
    if returncode == -9:
        return (
            f"The process was killed without a traceback — most often the "
            f"{MAX_MEMORY // 1024 // 1024}MB memory limit. Load less data at once."
        )
    if returncode == -25:
        return "The code tried to write a file above the size limit."
    return "The process exited abnormally without a traceback."
