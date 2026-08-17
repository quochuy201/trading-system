"""Tests for derived-id determinism (go-live-metrics Task 5).

`round_trips` is a cache that gets truncated and recomputed, so its id must be
reproducible from the fills it came from. Every test here exists because the
corresponding mistake silently breaks the rebuild invariant — and a broken
rebuild is only visible as ids that quietly stop matching.
"""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from audit.ids import (
    ID_WIDTH,
    canon_dt,
    canon_float,
    content_hash,
    hash_parts,
    round_trip_id,
)


class TestDeterminism:
    def test_same_inputs_same_id(self):
        assert round_trip_id("a", "b") == round_trip_id("a", "b")

    def test_same_id_across_processes(self):
        """Not just within one interpreter: PYTHONHASHSEED randomises str hashing
        per process, so an id built on Python's `hash()` would differ per run.
        """
        here = round_trip_id("act-1", "act-9")
        code = (
            "import sys; sys.path.insert(0, %r);"
            "from audit.ids import round_trip_id;"
            "print(round_trip_id('act-1', 'act-9'))"
            % str(Path(__file__).parent.parent)
        )
        out = subprocess.run([sys.executable, "-c", code],
                             capture_output=True, text=True, check=True)
        assert out.stdout.strip() == here

    def test_id_does_not_move_with_the_wall_clock(self):
        first = round_trip_id("act-1", "act-2")
        assert round_trip_id("act-1", "act-2") == first

    def test_width(self):
        assert len(round_trip_id("a", "b")) == ID_WIDTH


class TestNoAmbientInputs:
    def test_collection_order_does_not_matter(self):
        """Set and dict iteration order is not a contract; sorting is."""
        assert content_hash(["c", "a", "b"]) == content_hash(["a", "b", "c"])
        assert content_hash({"b", "a"}) == content_hash(["a", "b"])

    def test_float_repr_does_not_leak_in(self):
        """0.1 + 0.2 != 0.3 in binary floating point. Fixed decimals hide that."""
        assert canon_float(0.1 + 0.2) == canon_float(0.3)
        assert canon_float(150.25) == "150.25000000"
        assert canon_float(-0.0) == canon_float(0.0)

    def test_timezone_representation_does_not_matter(self):
        """The feed sends "Z"; a datetime may carry an offset. Same instant,
        same canonical form — otherwise a feed format change rewrites ids."""
        z = canon_dt("2026-04-30T13:30:34.923781Z")
        offset = canon_dt("2026-04-30T13:30:34.923781+00:00")
        other = canon_dt(datetime(2026, 4, 30, 15, 30, 34, 923781,
                                 tzinfo=timezone(timedelta(hours=2))))
        assert z == offset == other

    def test_naive_datetime_is_treated_as_utc(self):
        naive = datetime(2026, 4, 30, 13, 30, 34, 923781)
        assert canon_dt(naive) == canon_dt(naive.replace(tzinfo=timezone.utc))


class TestDelimiting:
    def test_delimiter_prevents_the_concatenation_collision(self):
        """"ab"+"c" == "a"+"bc" is a real collision, not a hypothetical."""
        assert hash_parts("ab", "c") != hash_parts("a", "bc")

    def test_a_delimiter_inside_a_part_cannot_forge_a_boundary(self):
        assert hash_parts("a|b", "c") != hash_parts("a", "b|c")

    def test_an_escape_inside_a_part_cannot_forge_a_boundary(self):
        assert hash_parts("a\\", "b") != hash_parts("a", "\\b")


class TestIdentityVsAmendment:
    def test_late_middle_fill_keeps_the_id_but_changes_the_content_hash(self):
        """The property the whole scheme is built for: references survive an
        amendment, and the amendment is still detectable."""
        before_id = round_trip_id("entry-1", "exit-9")
        before_content = content_hash(["entry-1", "exit-9"])

        after_id = round_trip_id("entry-1", "exit-9")  # boundaries unchanged
        after_content = content_hash(["entry-1", "middle-5", "exit-9"])

        assert after_id == before_id
        assert after_content != before_content

    def test_different_boundaries_are_different_trips(self):
        assert round_trip_id("entry-1", "exit-9") != round_trip_id("entry-1", "exit-8")
        assert round_trip_id("entry-1", "exit-9") != round_trip_id("entry-2", "exit-9")

    def test_id_is_not_a_uuid(self):
        """No randomness anywhere in the derived path."""
        import re
        rt = round_trip_id("act-1", "act-2")
        assert not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", rt)
        assert re.fullmatch(r"[0-9a-f]{16}", rt)


class TestRefusals:
    def test_missing_boundary_fill_is_refused(self):
        """A trip with no boundary has no identity; hashing "" would silently
        collide every such trip onto one id."""
        with pytest.raises(ValueError, match="boundary fill ids"):
            round_trip_id("", "exit-1")
        with pytest.raises(ValueError, match="boundary fill ids"):
            round_trip_id("entry-1", "")

    def test_empty_content_is_refused(self):
        with pytest.raises(ValueError, match="at least one fill id"):
            content_hash([])
