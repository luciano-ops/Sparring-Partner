"""Judgment SDK tracing -- optional, no-op when credentials are missing.

Provides:
  - get_tracer()   -> returns the Judgeval tracer (or None)
  - observe()      -> lazy decorator forwarding to tracer.observe()
  - wrap_client()  -> auto-instrument an LLM client via tracer.wrap()
  - flush_and_shutdown() -> flush buffered spans and shut down the tracer

Tracing activates when JUDGMENT_API_KEY is set and `judgeval` is installed.
Otherwise every helper is a silent no-op so the rest of the codebase runs
unchanged.
"""

import atexit
import functools
import os

_tracer = None
_initialized = False


def _ensure_init():
    """Initialize on first access."""
    global _tracer, _initialized
    if _initialized:
        return
    _initialized = True

    api_key = os.environ.get("JUDGMENT_API_KEY")
    if not api_key:
        return

    try:
        from judgeval import Judgeval
    except ImportError:
        print("[tracing] judgeval package not installed -- tracing disabled")
        return

    try:
        jclient = Judgeval(project_name="Internal-Health-Agent")
        _tracer = jclient.tracer.create()
        # Register automatic flush on process exit so CLI runs never lose traces
        atexit.register(_atexit_flush)
    except Exception as exc:
        print(f"[tracing] Judgment SDK init failed: {type(exc).__name__}: {exc}")


def _atexit_flush():
    """Best-effort flush when the process exits."""
    if _tracer is not None:
        try:
            _tracer.force_flush(timeout_millis=10_000)
            _tracer.shutdown(timeout_millis=5_000)
        except Exception:
            pass


def get_tracer():
    """Return the active tracer, or None if tracing is disabled."""
    _ensure_init()
    return _tracer


def flush():
    """Flush all buffered spans without killing the tracer.

    Use this between runs in a long-lived process so the tracer stays alive
    for the next run.
    """
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
    except Exception as exc:
        print(f"[tracing] flush error: {exc}")


def flush_and_shutdown():
    """Flush all buffered spans and shut down the tracer.

    Only call this when the process is about to exit (CLI mode).
    For long-lived processes, use flush() instead.
    """
    if _tracer is None:
        return
    try:
        _tracer.force_flush(timeout_millis=15_000)
        _tracer.shutdown(timeout_millis=5_000)
    except Exception as exc:
        print(f"[tracing] flush/shutdown error: {exc}")


# ---------------------------------------------------------------------------
# Lazy decorator
# ---------------------------------------------------------------------------

def observe(span_type: str = "function"):
    """Decorator that forwards to ``tracer.observe()`` when available.

    Resolution is *lazy* -- the tracer is looked up on the first call, not at
    decoration time, so module-level decorators work even before env vars or
    the ``judgeval`` package are ready.
    """
    def decorator(func):
        _cache: dict = {}  # mutable container -- caches the observed fn

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if "fn" not in _cache:
                t = get_tracer()
                _cache["fn"] = (
                    t.observe(span_type=span_type)(func) if t else None
                )
            observed = _cache["fn"]
            if observed is not None:
                return observed(*args, **kwargs)
            return func(*args, **kwargs)

        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Client auto-instrumentation
# ---------------------------------------------------------------------------

def wrap_client(client_instance):
    """Try to auto-instrument an LLM client via ``tracer.wrap()``.

    Returns the wrapped client on success, or the original on failure /
    when tracing is disabled.
    """
    _ensure_init()
    t = _tracer
    if t is None:
        return client_instance
    try:
        return t.wrap(client_instance)
    except Exception:
        # wrap() may not support this client type -- fall back silently
        return client_instance
