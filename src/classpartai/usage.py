"""Usage ledger and trace events: every model call with its tokens, latency and estimated cost.

The call sites (the OpenAI driver, Research's chat model, the embedder) report each call here.
Who made it comes from a context that whoever is running sets: ``tracking(run_id=..., agent=...)``.
Events go to a sink (``Records.log_event`` stores them in SQLite) and this module never raises:
monitoring must not be able to break a run.

An event is a dict: ``id, ts, run_id, session_id, agent, kind, name, provider, model,
input_tokens, output_tokens, cached_tokens, reasoning_tokens, latency_ms, cost_usd, status,
detail``. ``kind`` is "model" (a chat call), "embedding", "tool" (a step an agent took) or "error".
Output tokens include reasoning tokens, as OpenAI bills them.

Costs are estimates from ``data/model_prices.json`` (USD per million tokens), not an invoice. A
model with no price has ``cost_usd = None`` and shows as "no price", never as zero.
"""

from __future__ import annotations

import contextvars
import json
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache, wraps

Sink = Callable[[dict], None]
Started = tuple[str, float]  # (start time, perf counter)

_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "usage_context", default=None
)
_default_sink: Sink | None = None
LOCAL_PROVIDERS = {"ollama", "local"}


def configure(sink: Sink | None) -> None:
    """Where events go when the running code has not set its own sink (the app sets this)."""
    global _default_sink
    _default_sink = sink


def current() -> dict:
    return _context.get() or {}


@contextmanager
def tracking(**fields):
    """Everything reported inside belongs to these fields (run_id, session_id, agent, sink)."""
    token = _context.set({**current(), **{k: v for k, v in fields.items() if v is not None}})
    try:
        yield
    finally:
        _context.reset(token)


def update(**fields) -> None:
    """Add fields (a run's ID, once it exists) to the context this code is already running in."""
    ctx = _context.get()
    if ctx is not None:
        ctx.update({k: v for k, v in fields.items() if v is not None})


def tracked(agent: str):
    """Decorator: calls made inside the function are attributed to this agent."""

    def decorate(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with tracking(agent=agent):
                return fn(*args, **kwargs)

        return wrapper

    return decorate


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def begin() -> Started:
    return now_iso(), time.perf_counter()


# --- Prices -----------------------------------------------------------------------------------


@lru_cache(maxsize=1)
def prices() -> dict:
    from classpartai import config

    try:
        return json.loads(config.MODEL_PRICES.read_text(encoding="utf-8")).get("models", {})
    except (OSError, ValueError):
        return {}


def price_for(model: str | None) -> dict | None:
    """The price entry whose name is the longest prefix of the model (dated names still match)."""
    matches = [name for name in prices() if model and model.startswith(name)]
    return prices()[max(matches, key=len)] if matches else None


def extract(usage) -> dict:
    """Token counts from a provider's usage object (or None). Missing numbers stay None."""

    def number(obj, name):
        value = getattr(obj, name, None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return {
        "input": number(usage, "prompt_tokens") or number(usage, "input_tokens"),
        "output": number(usage, "completion_tokens") or number(usage, "output_tokens"),
        "cached": number(getattr(usage, "prompt_tokens_details", None), "cached_tokens"),
        "reasoning": number(getattr(usage, "completion_tokens_details", None), "reasoning_tokens"),
    }


def cost_usd(model: str | None, provider: str, tokens: dict) -> float | None:
    if provider in LOCAL_PROVIDERS:
        return 0.0
    price = price_for(model)
    if price is None or tokens.get("input") is None:
        return None
    cached = tokens.get("cached") or 0
    fresh = tokens["input"] - cached
    cost = fresh * price["input"] + cached * price.get("cached_input", price["input"])
    cost += (tokens.get("output") or 0) * price.get("output", 0)
    return cost / 1_000_000


# --- Reporting --------------------------------------------------------------------------------


def _emit(event: dict) -> None:
    ctx = current()
    sink = ctx.get("sink") or _default_sink
    if sink is None:
        return
    try:
        sink(event)
    except Exception:  # monitoring must never break a run
        pass


def _event(started: Started, kind: str, name: str, status: str, detail: dict | None, **extra):
    ts, t0 = started
    ctx = current()
    return {
        "id": uuid.uuid4().hex,
        "ts": ts,
        "run_id": ctx.get("run_id"),
        "session_id": ctx.get("session_id"),
        "agent": ctx.get("agent") or "unknown",
        "kind": kind,
        "name": name,
        "provider": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
        "reasoning_tokens": None,
        "latency_ms": round((time.perf_counter() - t0) * 1000),
        "cost_usd": None,
        "status": status,
        "detail": detail or {},
        **extra,
    }


def record_model_call(
    started: Started,
    *,
    model: str,
    provider: str = "openai",
    usage=None,
    calls: list[str] | None = None,
    status: str = "ok",
    error: str | None = None,
    kind: str = "model",
) -> None:
    """One chat (or embedding) call. ``calls`` are the tool names the model asked for."""
    tokens = extract(usage)
    detail: dict = {}
    if calls:
        detail["calls"] = calls
    if error:
        detail["error"] = error[:500]
    _emit(
        _event(
            started,
            kind,
            model,
            status,
            detail,
            provider=provider,
            model=model,
            input_tokens=tokens["input"],
            output_tokens=tokens["output"],
            cached_tokens=tokens["cached"],
            reasoning_tokens=tokens["reasoning"],
            cost_usd=cost_usd(model, provider, tokens),
        )
    )


def record_step(started: Started, name: str, status: str = "ok", detail: dict | None = None):
    """A step an agent took (a tool call), for the trace."""
    _emit(_event(started, "tool", name, status, _short(detail)))


def record_error(name: str, error: BaseException) -> None:
    _emit(
        _event(
            begin(),
            "error",
            name,
            "error",
            {"error": f"{type(error).__name__}: {error}"[:500]},
        )
    )


def _short(detail: dict | None, limit: int = 1500) -> dict:
    """Trace details are for reading, so long values are cut."""
    out = {}
    for key, value in (detail or {}).items():
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        out[key] = text if len(text) <= limit else text[:limit] + "…"
    return out


# --- Summaries (used by the dashboard; plain functions so they are easy to test) ---------------


def summarise(rows: list[dict], key: str | None = None) -> list[dict]:
    """Totals for chat and embedding events, grouped by a field (agent, model, day, ...).

    ``priced`` is False when any call in the group has no price, so a cost shown for it is a
    lower bound rather than the whole bill."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        if row["kind"] not in ("model", "embedding"):
            continue
        label = "all" if key is None else str(row.get(key) or "unknown")
        groups.setdefault(label, []).append(row)
    out = []
    for label, items in sorted(groups.items()):
        latencies = sorted(r["latency_ms"] for r in items if r["latency_ms"] is not None)
        out.append(
            {
                "group": label,
                "calls": len(items),
                "input_tokens": sum(r["input_tokens"] or 0 for r in items),
                "cached_tokens": sum(r["cached_tokens"] or 0 for r in items),
                "output_tokens": sum(r["output_tokens"] or 0 for r in items),
                "reasoning_tokens": sum(r["reasoning_tokens"] or 0 for r in items),
                "cost_usd": sum(r["cost_usd"] or 0.0 for r in items),
                "priced": all(r["cost_usd"] is not None for r in items),
                "avg_ms": round(sum(latencies) / len(latencies)) if latencies else None,
                "p95_ms": latencies[min(len(latencies) - 1, int(0.95 * len(latencies)))]
                if latencies
                else None,
                "errors": sum(r["status"] == "error" for r in items),
            }
        )
    return out
