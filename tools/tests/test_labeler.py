import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backtest.labeler import OutcomeLabeler


class TestOutcomeLabeler:
    def test_good_entry_label(self):
        label = OutcomeLabeler.label_entry(r_multiple=2.0)
        assert label == "GOOD_ENTRY"

    def test_bad_entry_label(self):
        label = OutcomeLabeler.label_entry(r_multiple=-1.0)
        assert label == "BAD_ENTRY"

    def test_neutral_entry_positive(self):
        label = OutcomeLabeler.label_entry(r_multiple=0.8)
        assert label == "NEUTRAL"

    def test_neutral_entry_small_loss(self):
        label = OutcomeLabeler.label_entry(r_multiple=-0.3)
        assert label == "NEUTRAL"

    def test_good_exit_price_reversed(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=500.0,
            price_after_exit_moved=-200.0,
        )
        assert label == "GOOD_EXIT"

    def test_early_exit_price_continued(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=500.0,
            price_after_exit_moved=800.0,
        )
        assert label == "EARLY_EXIT"

    def test_expected_loss_at_stop(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=-200.0,
            price_after_exit_moved=0.0,
            exited_at_planned_stop=True,
        )
        assert label == "EXPECTED_LOSS"

    def test_bad_exit_below_stop(self):
        label = OutcomeLabeler.label_exit(
            exit_pnl=-500.0,
            price_after_exit_moved=0.0,
            exited_at_planned_stop=False,
        )
        assert label == "BAD_EXIT"

    def test_compute_r_multiple_long_winner(self):
        r = OutcomeLabeler.compute_r_multiple(entry_price=100.0, exit_price=110.0, stop_price=95.0)
        assert r == 2.0

    def test_compute_r_multiple_long_loser(self):
        r = OutcomeLabeler.compute_r_multiple(entry_price=100.0, exit_price=95.0, stop_price=95.0)
        assert r == -1.0

    def test_compute_r_multiple_zero_risk(self):
        r = OutcomeLabeler.compute_r_multiple(entry_price=100.0, exit_price=105.0, stop_price=100.0)
        assert r == 0.0
