import random

from classpartai.config import set_seed


def test_set_seed_makes_runs_repeatable():
    set_seed(7)
    first = [random.random() for _ in range(3)]
    set_seed(7)
    assert [random.random() for _ in range(3)] == first
