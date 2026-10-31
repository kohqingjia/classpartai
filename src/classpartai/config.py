"""Shared settings: environment variables and the random seed every experiment uses."""

import os
import random

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("SEED", "42"))


def set_seed(seed: int = SEED) -> None:
    """Seed every random source in use so runs are reproducible.

    Add numpy/torch seeding here when those libraries join the project.
    """
    random.seed(seed)
