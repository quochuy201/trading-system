import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.load_universe import _default_daily_end


def test_default_daily_end_is_yesterday():
    assert _default_daily_end() == (date.today() - timedelta(days=1)).isoformat()
