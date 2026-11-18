"""v0.7 Stage 2: local prices formed from supply and demand.

Each settlement posts one price per good at the start of every decision cycle.
Every retail purchase or sale, merchant consignment and wage judgment in that
cycle uses the posted price, so everyone plans from the same public numbers.

The rule is explicit and illustrative, not a calibrated model of real markets:

    coverage = (stored + accessible + incoming + expected production)
               / (expected annual use + customary reserve)
    target   = base price / coverage, kept between 1/4 and 4 times the base
    posted   = the previous posted price moved toward the target by at most 25%

A town expecting to produce what it uses and holding its customary reserve
therefore posts the base price. The market sells at its posted price and buys
at 80 percent of it. Every exchange transfers existing goods and coins.
"""
from .actions import PRICES

GOODS = ('food', 'wood', 'iron')
BASE_PRICES = {good: PRICES[good] for good in GOODS}
# The same per-resident stock targets councils already use to judge import needs.
RESERVE_PER_RESIDENT = {'food': 1.12, 'wood': .25, 'iron': .12}
# Annual aggregate eating and the household wood and iron sinks.
USE_PER_RESIDENT = {'food': 1., 'wood': .05, 'iron': .015}
BID_SHARE = .8          # the market buys from sellers at 80% of its posted price
PRICE_FLOOR = .25       # multiples of the base price
PRICE_CEILING = 4.
MAX_STEP = 1.25         # a posted price moves at most 25% per cycle
WAGE_SHARE = .6         # employers offer 60% of the local price per unit of output
CONSIGNMENT_LIMIT = 12  # units per merchant shipment


def expected_use(resource, population):
    return max(1, population) * USE_PER_RESIDENT[resource]


def coverage(resource, *, population, stock, accessible=0., incoming=0., production=None):
    """Expected supply over expected need. Unknown production assumes a town makes what it uses."""
    use = expected_use(resource, population)
    reserve = max(1, population) * RESERVE_PER_RESIDENT[resource]
    produced = use if production is None else production
    supply = max(0., stock) + max(0., accessible) + max(0., incoming) + max(0., produced)
    return supply / (use + reserve)


def bounds(resource):
    base = BASE_PRICES[resource]
    return round(base * PRICE_FLOOR, 2), round(base * PRICE_CEILING, 2)


def target_price(resource, cover):
    low, high = bounds(resource)
    if cover <= 0:
        return high
    return min(high, max(low, BASE_PRICES[resource] / cover))


def next_price(resource, previous, target):
    """Move toward the target by at most MAX_STEP; posted prices are whole hundredths of a coin."""
    low, high = bounds(resource)
    if previous is None:
        return min(high, max(low, round(target, 2)))
    step = min(MAX_STEP, max(1 / MAX_STEP, target / previous))
    return min(high, max(low, round(previous * step, 2)))


def bid_price(ask):
    return round(ask * BID_SHARE, 2)


def offered_wage(price):
    """The wage an employer offers per unit: a share of the local price, within the job limits."""
    return round(min(5., max(.1, price * WAGE_SHARE)), 2)
