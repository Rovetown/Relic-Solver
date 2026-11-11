from functools import cache

DIVINE_CHANCE = 1 / 25000

UNLOCK_D2_THRESHOLD = 3
UNLOCK_D3_THRESHOLD = 6
UNLOCK_D4_THRESHOLD = 10
UNLOCK_D5_THRESHOLD = 30

DEFAULT_RELIC_CAP = 5
MIN_RELIC_CAP = 5
MAX_RELIC_CAP = 36

NUM_RELIC_TYPES = 5

DEFAULT_TOTAL_RELIC_CHESTS = 0
DEFAULT_DIVINE_CHESTS = 0


@cache
def get_divine_relic_names() -> dict[int, str]:
    return {
        0: "Rainbow Floor Chance",
        1: "Supernova Multiplier",
        2: "Rainbow Floor Multi",
        3: "Fishing Ticks 5x Chance",
        4: "Rainbow Void Portal Chance",
    }


LABEL_TOTAL_RELIC_CHESTS = "Total Relic Chests"
LABEL_TOTAL_DIVINE_CHESTS = "Total Divine Chests"
LABEL_DIVINE_RELIC_CAP = "Divine Relic Cap"

COST_PER_REROLL = 200

RATE_LIMIT_SOLVE = "10/minute"
RATE_LIMIT_DEFAULT = "60/minute"

MAX_REQUEST_BYTES = 8 * 1024

SOLVE_MAX_SECONDS = 90
WORKER_TIMEOUT_SECONDS = 120
