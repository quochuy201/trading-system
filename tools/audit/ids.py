"""Deterministic identifiers for derived rows.

> Facts get generated IDs. Derived rows get IDs derived from the facts they
> came from.

`fills` and `orders` are facts written once. `round_trips` is a *cache* that
gets truncated and recomputed, so its id cannot be random: a UUID makes the
rebuild invariant unpassable by construction and dangles every external
reference on every rebuild.

The rules these helpers enforce, each of which is a real bug if broken:

1. **Deterministic** — same inputs, same id, on any machine, in any process.
2. **No ambient inputs** — never the wall clock, `random`, PID, locale, or a
   memory address. Only the facts.
3. **Canonicalise before hashing** — UTC ISO-8601 for times, fixed decimal
   places for floats (never `repr`, whose output is platform- and
   version-sensitive), sorted collections (set/dict order is not a contract).
4. **Always delimit, and escape the delimiter** — bare concatenation collides:
   `"ab" + "c" == "a" + "bc"`.
"""

import hashlib
from datetime import datetime, timezone

# Width of a derived id. 16 hex chars = 64 bits; collision risk is negligible
# at any plausible trade count and it stays readable in a log line.
ID_WIDTH = 16

_DELIM = "|"
_ESCAPE = "\\"

# Decimal places used when a float enters a hash. Fixed, because repr() differs
# across platforms and Python versions, and 0.1+0.2 must not change an id.
FLOAT_PLACES = 8


def _escape(part: str) -> str:
    """Escape the delimiter so joined parts can never be re-split ambiguously."""
    return part.replace(_ESCAPE, _ESCAPE * 2).replace(_DELIM, _ESCAPE + _DELIM)


def canon_float(value: float, places: int = FLOAT_PLACES) -> str:
    """Canonical decimal form of a float.

    Args:
        value: Any real number.
        places: Decimal places to fix at; must be >= 0.

    Returns:
        Fixed-point string, e.g. "150.25000000". Never `repr`, which varies by
        platform and would make ids machine-dependent. -0.0 normalises to 0.
    """
    if value == 0:  # kills the -0.0 / 0.0 split
        value = 0.0
    return f"{value:.{places}f}"


def canon_dt(value: datetime | str) -> str:
    """Canonical UTC ISO-8601 form of a timestamp.

    Args:
        value: A datetime, or an ISO-8601 string (a trailing "Z" is accepted).
            A naive datetime is treated as UTC — the convention everywhere in
            this codebase.

    Returns:
        "YYYY-MM-DDTHH:MM:SS.ffffff+00:00". Two instants that are equal are
        rendered identically regardless of the timezone they arrived in, so a
        feed that switches from "Z" to "+00:00" cannot change an id.

    Raises:
        ValueError: the string is not ISO-8601.
    """
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def hash_parts(*parts: str, width: int = ID_WIDTH) -> str:
    """Hash an ordered sequence of already-canonical parts.

    Args:
        *parts: Canonical strings. Order is significant.
        width: Hex characters to keep; must be 1..64.

    Returns:
        The leading `width` hex characters of the SHA-256 of the
        delimiter-joined, delimiter-escaped parts.
    """
    joined = _DELIM.join(_escape(p) for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:width]


def round_trip_id(first_entry_fill_id: str, last_exit_fill_id: str) -> str:
    """Stable IDENTITY of a round trip.

    Bounded by the first entry and last exit fill, so no two trips can share
    both. A fill discovered later *in the middle* of a trip therefore leaves
    the id untouched — external references survive — while `content_hash`
    changes so the amendment is still detectable.

    Args:
        first_entry_fill_id: Broker activity id of the earliest entry fill.
        last_exit_fill_id: Broker activity id of the latest exit fill.

    Returns:
        16 hex characters, reproducible from the same two fills forever.

    Raises:
        ValueError: either id is empty — a trip with no boundary fill has no
            identity, and hashing "" would silently collide such trips.
    """
    if not first_entry_fill_id or not last_exit_fill_id:
        raise ValueError(
            "round_trip_id needs both boundary fill ids; refusing to mint an "
            f"id from ({first_entry_fill_id!r}, {last_exit_fill_id!r})"
        )
    return hash_parts(first_entry_fill_id, last_exit_fill_id)


def content_hash(fill_ids) -> str:
    """Hash of everything a round trip is made of — detects AMENDMENT.

    Args:
        fill_ids: Every composing fill id, in any order and any container.
            Sorted internally, because iteration order is not a contract.

    Returns:
        16 hex characters. Changes whenever the composing set changes, even
        when `round_trip_id` stays the same.

    Raises:
        ValueError: the collection is empty.
    """
    ids = sorted(fill_ids)
    if not ids:
        raise ValueError("content_hash needs at least one fill id")
    return hash_parts(*ids)
