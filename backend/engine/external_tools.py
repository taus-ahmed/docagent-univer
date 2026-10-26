# -*- coding: utf-8 -*-
"""Every external program the engine starts, with a deadline.

The engine shells out to two programs: Poppler's `pdftoppm` (through
pdf2image) to render pages, and Tesseract (through pytesseract) to read them.
Neither library bounds what it starts unless asked, and neither asks for its
VERSION PROBE at all: pdf2image runs `pdftoppm -v` before EVERY render with no
timeout, and pytesseract runs `tesseract --version` once per process with none.
One `pdftoppm -v` that never returned (MiKTeX's build, on PATH on the
development machine) froze an OCR pool worker, the pool, and the whole suite
for an hour — a hang, which is worse than any failure, because nothing reports
it.

So, for every program the engine starts:

* it has a HARD timeout (`timeout_s`, from the environment, OPERATIONS.md §11);
* on timeout it is KILLED WITH ITS CHILDREN (`kill_tree`: some Windows builds
  are launchers that start the real binary) and the call raises `ToolTimeout`,
  which names the program and the setting — a per-page or per-file failure the
  caller records, never a hang;
* the version probes run ONCE per process, with a timeout, and the parent hands
  its answers to pool workers (`snapshot` / `seed`), so a worker never probes.

`install()` patches the two libraries' module globals (pdf2image's `Popen` and
`_get_poppler_version`; pytesseract's `kill` and `get_tesseract_version`). The
command lines are untouched, so a page renders to the same bytes as before.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

#: (environment variable, default seconds). Read at call time, so a test or an
#: operator changes them without a restart of anything but the process.
TIMEOUTS = {
    "probe": ("OCR_PROBE_TIMEOUT_S", 15.0),        # a `-v` / `--version` call
    "render": ("OCR_RENDER_TIMEOUT_S", 120.0),     # one pdftoppm call, per page
    "tesseract": ("OCR_TESSERACT_TIMEOUT_S", 120.0),  # one tesseract call
    "page": ("OCR_PAGE_TIMEOUT_S", 300.0),         # pool: waiting on one page
    "pool": ("OCR_POOL_TIMEOUT_S", 1800.0),        # pool: one file in total
}

#: A failed probe is remembered this long, then asked again: a transient stall
#: must not switch OCR off until the next deploy, and must not be re-paid on
#: every page either.
FAILURE_TTL_S = 300.0


class ToolTimeout(RuntimeError):
    """An external program did not finish in time and was killed."""


class ToolUnavailable(RuntimeError):
    """An external program could not be asked (missing, or its probe failed)."""


def timeout_s(kind: str) -> float:
    var, default = TIMEOUTS[kind]
    raw = (os.environ.get(var) or "").strip()
    try:
        value = float(raw) if raw else default
    except ValueError:
        return default
    return value if value > 0 else default


def _children_linux(pid: int) -> list:
    out, todo = [], [pid]
    while todo:
        p = todo.pop()
        try:
            for task in os.listdir(f"/proc/{p}/task"):
                with open(f"/proc/{p}/task/{task}/children") as fh:
                    kids = [int(k) for k in fh.read().split()]
                out += kids
                todo += kids
        except OSError:
            continue
    return out


def _parents_nt() -> dict:
    """{pid: parent pid} for every process, from one Toolhelp snapshot.

    Windows does not re-parent an orphan: a child keeps its dead parent's id,
    so a snapshot still finds what a worker started after the worker itself
    was terminated (ProcessPoolExecutor terminates the rest of a broken pool
    on its own, which `taskkill /T` then cannot walk)."""
    import ctypes
    from ctypes import wintypes

    class Entry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_void_p),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260)]
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)          # TH32CS_SNAPPROCESS
    out = {}
    entry = Entry()
    entry.dwSize = ctypes.sizeof(Entry)
    try:
        ok = k32.Process32First(snap, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = entry.th32ParentProcessID
            ok = k32.Process32Next(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return out


def _terminate_nt(pid: int) -> None:
    import ctypes
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x0001, False, pid)          # PROCESS_TERMINATE
    if handle:
        k32.TerminateProcess(handle, 1)
        k32.CloseHandle(handle)


def descendants(roots) -> list:
    """Every process started (transitively) by `roots`, deepest last."""
    roots = [r for r in roots if r]
    if os.name == "nt":
        parents = _parents_nt()
        children: dict = {}
        for pid, ppid in parents.items():
            children.setdefault(ppid, []).append(pid)
        out, todo, seen = [], list(roots), set(roots)
        while todo:
            for kid in children.get(todo.pop(), ()):
                if kid not in seen:
                    seen.add(kid)
                    out.append(kid)
                    todo.append(kid)
        return out
    out = []
    for r in roots:
        out += _children_linux(r)
    return out


def kill_tree(*pids: int) -> None:
    """Kill every pid given and every process they started. Never raises."""
    pids = [p for p in pids if p]
    if not pids:
        return
    try:
        everyone = descendants(pids)
    except Exception:
        everyone = []
    for p in list(reversed(everyone)) + pids:
        try:
            if os.name == "nt":
                _terminate_nt(p)
            else:
                os.kill(p, signal.SIGKILL)
        except Exception:
            pass


def _die_with_parent():                            # pragma: no cover - Linux
    """Linux: the tool is killed when the process that started it dies, so
    a pool worker killed from outside cannot leave its pdftoppm running
    (Linux re-parents an orphan, and a tree walk then cannot find it)."""
    import ctypes
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGKILL)


class ToolPopen(subprocess.Popen):
    """`subprocess.Popen` whose `kill()` takes the children with it."""

    def __init__(self, *args, **kwargs):
        if sys.platform.startswith("linux") and "preexec_fn" not in kwargs:
            kwargs["preexec_fn"] = _die_with_parent
        super().__init__(*args, **kwargs)

    def kill(self):
        kill_tree(self.pid)
        try:
            super().kill()
        except OSError:
            pass


def _popen(*args, **kwargs):
    # Looked up at call time, so a test can substitute the class.
    return ToolPopen(*args, **kwargs)


def run(cmd, kind: str = "probe", **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run` with the `kind` deadline; ToolTimeout after killing
    the tree. stdout/stderr are captured as bytes."""
    limit = timeout_s(kind)
    proc = _popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                  stdin=subprocess.DEVNULL, **kwargs)
    try:
        out, err = proc.communicate(timeout=limit)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.communicate(timeout=10)
        except Exception:
            pass
        raise ToolTimeout(_timeout_message(cmd, kind)) from None
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


def _timeout_message(cmd, kind) -> str:
    name = os.path.basename(str(cmd[0] if isinstance(cmd, (list, tuple))
                                else cmd))
    var = TIMEOUTS[kind][0]
    return (f"{name} did not finish within {timeout_s(kind):g} s ({var}) "
            f"and was killed")


# ── version probes: once per process, answers handed to pool workers ────────

#: name -> ("ok", value) | ("error", message, monotonic time)
_PROBES: dict = {}


def _remembered(name):
    entry = _PROBES.get(name)
    if entry is None:
        return None
    if entry[0] == "error" and time.monotonic() - entry[2] > FAILURE_TTL_S:
        _PROBES.pop(name, None)
        return None
    return entry


def _probe(name, ask):
    entry = _remembered(name)
    if entry is None:
        try:
            entry = ("ok", ask())
        except Exception as exc:
            entry = ("error", f"{type(exc).__name__}: {exc}", time.monotonic())
        _PROBES[name] = entry
    if entry[0] == "ok":
        return entry[1]
    raise ToolUnavailable(f"{name} version probe failed: {entry[1]}")


def snapshot() -> dict:
    """This process's probe answers, for a pool initializer. Probes first."""
    for name, ask in (("pdftoppm", lambda: poppler_version("pdftoppm")),
                      ("tesseract", tesseract_version)):
        try:
            ask()
        except Exception:
            pass
    return {k: v[:2] for k, v in _PROBES.items()}


def seed(answers: dict) -> None:
    """Install the parent's probe answers in a worker: it never probes."""
    install()
    now = time.monotonic()
    for name, entry in (answers or {}).items():
        _PROBES[name] = entry if entry[0] == "ok" else ("error", entry[1], now)


_ORIGINAL_POPPLER_VERSION = None


def poppler_version(command="pdftoppm", poppler_path=None, timeout=None):
    """pdf2image's own `-v` parse, run once per command, with a deadline."""
    install()

    def ask():
        from pdf2image.exceptions import PDFPopplerTimeoutError
        try:
            return _ORIGINAL_POPPLER_VERSION(command, poppler_path=poppler_path,
                                             timeout=timeout_s("probe"))
        except PDFPopplerTimeoutError:
            raise ToolTimeout(_timeout_message([command], "probe")) from None
    return _probe(command, ask)


def tesseract_version():
    """`tesseract --version`, parsed as pytesseract parses it, once."""
    def ask():
        import string
        from packaging.version import parse
        import ocr_source
        cmd = ocr_source._configure().pytesseract.tesseract_cmd
        try:
            done = run([cmd, "--version"], kind="probe")
        except OSError as exc:
            raise ToolUnavailable(f"tesseract not found ({exc})") from None
        raw = (done.stdout + done.stderr).decode("utf-8", "replace")
        word = raw.lstrip(string.printable[10:]).partition(" ")[0]
        return parse(word.partition("-")[0])
    return _probe("tesseract", ask)


def _tesseract_kill(process, code):
    kill_tree(process.pid)
    try:
        process.kill()
    except OSError:
        pass
    process.returncode = code


def _bounded_pdfinfo(original):
    """convert_from_path runs `pdfinfo` first, and passes it no timeout."""
    def pdfinfo_from_path(*args, **kwargs):
        from pdf2image.exceptions import PDFPopplerTimeoutError
        if not kwargs.get("timeout"):
            kwargs["timeout"] = timeout_s("render")
        try:
            return original(*args, **kwargs)
        except PDFPopplerTimeoutError:
            raise ToolTimeout(f"pdfinfo did not finish within "
                              f"{kwargs['timeout']:g} s (OCR_RENDER_TIMEOUT_S) "
                              f"and was killed") from None
    return pdfinfo_from_path


_INSTALLED = False


def install() -> None:
    """Patch pdf2image and pytesseract once per process (idempotent)."""
    global _INSTALLED, _ORIGINAL_POPPLER_VERSION
    if _INSTALLED:
        return
    _INSTALLED = True
    try:
        import pdf2image.pdf2image as p2i
        _ORIGINAL_POPPLER_VERSION = p2i._get_poppler_version
        p2i.Popen = _popen
        p2i._get_poppler_version = (
            lambda command, poppler_path=None, timeout=None:
            poppler_version(command, poppler_path))
        p2i.pdfinfo_from_path = _bounded_pdfinfo(p2i.pdfinfo_from_path)
    except ImportError:
        pass
    try:
        import pytesseract.pytesseract as pt
        pt.kill = _tesseract_kill
        pt.get_tesseract_version = tesseract_version
    except ImportError:
        pass


def tesseract(fn, *args, **kwargs):
    """Call a pytesseract `image_to_*` function with the tesseract deadline;
    its own timeout error becomes ToolTimeout."""
    install()
    try:
        return fn(*args, timeout=timeout_s("tesseract"), **kwargs)
    except RuntimeError as exc:
        if "timeout" in str(exc).lower() and not isinstance(exc, ToolTimeout):
            raise ToolTimeout(_timeout_message(["tesseract"], "tesseract")) \
                from None
        raise


def render(path, pages: int = 1, **kwargs):
    """pdf2image.convert_from_path with a deadline of `render` per page."""
    install()
    from pdf2image import convert_from_path
    from pdf2image.exceptions import PDFPopplerTimeoutError
    limit = timeout_s("render") * max(1, pages)
    try:
        return convert_from_path(str(path), timeout=limit, **kwargs)
    except PDFPopplerTimeoutError:
        raise ToolTimeout(f"pdftoppm did not finish within {limit:g} s "
                          f"(OCR_RENDER_TIMEOUT_S x {max(1, pages)} page(s)) "
                          f"and was killed") from None


install()

__all__ = ["ToolTimeout", "ToolUnavailable", "install", "kill_tree", "render",
           "run", "seed", "snapshot", "tesseract", "timeout_s", "sys"]
