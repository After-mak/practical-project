import random
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "finops" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_krr_dummy_history import chronos_periodic_cpu


def test_chronos_dummy_profile_contains_repeatable_baseline_spike_and_recovery():
    baseline = chronos_periodic_cpu(2 * 60, random.Random(42))
    spike = chronos_periodic_cpu(13 * 60, random.Random(42))
    recovery = chronos_periodic_cpu(19 * 60, random.Random(42))

    assert 0.05 <= baseline <= 0.11
    assert 1.1 <= spike <= 1.3
    assert 0.05 <= recovery <= 0.2
