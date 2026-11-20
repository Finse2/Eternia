"""v0.7 Stage 4: measuring inequality among the individually simulated people.

These measures cover the named people (eighteen lineages), never the aggregate
population, whose members have no individual holdings.

    wealth         coins, plus goods at the home market's buying price, plus
                   structures at the cost of their materials at home prices
    income         coins received in a period: wages, sales to a market or a
                   neighbor, and merchant consignment payments
    food insecure  cannot cover three meals from food held plus coins at the
                   home food price
    poor           wealth below half the group's median
    mobility       1 minus the rank correlation of lineage wealth between two
                   dates: 0 means everyone kept their rank, 1 means no relation

Observers use these numbers. People in the world never see anyone else's wealth.
"""
from .actions import RECIPES
from .market import BASE_PRICES, bid_price

MEALS = 3


def gini(values):
    """0 when everyone holds the same; (n - 1) / n when one person holds everything."""
    values = sorted(max(0., float(v)) for v in values)
    count, total = len(values), sum(values)
    if count == 0 or total <= 0:
        return 0.
    ranked = sum((rank + 1) * value for rank, value in enumerate(values))
    return round(2 * ranked / (count * total) - (count + 1) / count, 6)


def structure_value(structure, prices):
    recipe = RECIPES.get(structure, {})
    return (recipe.get('coins', 0.) + recipe.get('wood', 0.) * prices['wood']
            + recipe.get('iron', 0.) * prices['iron'])


def person_wealth(person, prices):
    goods = sum(person.inventory.get(r, 0.) * bid_price(prices[r]) for r in ('food', 'wood', 'iron'))
    buildings = sum(count * structure_value(kind, prices) for kind, count in person.structures.items())
    coins = person.inventory.get('coins', 0.)
    return dict(coins=round(coins, 6), goods=round(goods, 6), structures=round(buildings, 6),
                total=round(coins + goods + buildings, 6))


def food_insecure(person, prices):
    return person.inventory.get('food', 0.) + person.inventory.get('coins', 0.) / prices['food'] < MEALS


def _median(values):
    values = sorted(values)
    if not values:
        return 0.
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def describe(rows):
    """Summary of one group of people: rows carry wealth, income and need flags."""
    wealth = [row['wealth'] for row in rows]
    count = len(rows)
    if not count:
        return dict(people=0)
    total, median = sum(wealth), _median(wealth)
    top = sorted(wealth, reverse=True)[:max(1, count // 3)]
    poorest = sorted(wealth)[:max(1, count // 3)]
    return dict(people=count, wealth_gini=gini(wealth), income_gini=gini(row['income'] for row in rows),
                mean_wealth=round(total / count, 4), median_wealth=round(median, 4),
                top_third_share=round(sum(top) / total, 4) if total > 0 else 0.,
                poorest_third_mean=round(sum(poorest) / len(poorest), 4),
                poverty_share=round(sum(w < median / 2 for w in wealth) / count, 4),
                food_insecure_share=round(sum(row['food_insecure'] for row in rows) / count, 4),
                hungry_share=round(sum(row['hungry'] for row in rows) / count, 4),
                mean_income=round(sum(row['income'] for row in rows) / count, 4))


def incomes(world, since):
    """Coins each named person received from tick ``since`` on."""
    received = {}
    for record in getattr(world, 'work_history', ()):
        if record['tick'] >= since and record.get('mode') in ('paid', 'paid_sale') and record.get('coins'):
            received[record['actor']] = received.get(record['actor'], 0.) + record['coins']
    for record in getattr(world, 'trade_history', ()):
        if record['tick'] >= since and record.get('kind') == 'delivery' and record.get('coins'):
            received[record['actor']] = received.get(record['actor'], 0.) + record['coins']
    return received


def people_rows(world, since=None):
    since = world.tick - world.ticks_per_year if since is None else since
    received = incomes(world, since)
    rows = []
    for person in sorted(world.agents, key=lambda a: a.id):
        prices = getattr(world, 'market_prices', {}).get(person.home, BASE_PRICES)
        holdings = person_wealth(person, prices)
        rows.append(dict(id=person.id, lineage=person.lineage, home=person.home, role=person.role,
                         wealth=holdings['total'], coins=holdings['coins'], goods=holdings['goods'],
                         structures=holdings['structures'], income=round(received.get(person.id, 0.), 6),
                         food_insecure=food_insecure(person, prices), hungry=person.hunger >= 65))
    return rows


def snapshot(world):
    """Region and per-town distributions now, with last year's incomes."""
    rows = people_rows(world)
    towns = {town.id: describe([r for r in rows if r['home'] == town.id]) for town in world.settlements}
    return dict(region=describe(rows), towns=towns,
                wealth={r['lineage']: r['wealth'] for r in rows},
                people=[{k: r[k] for k in ('id', 'lineage', 'home', 'role', 'wealth', 'income')} for r in rows])


def _ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        for index in order[position:end + 1]:
            ranks[index] = (position + end) / 2 + 1  # ties share their average rank
        position = end + 1
    return ranks


def rank_mobility(before, after):
    """1 - Spearman rank correlation between two {lineage: wealth} tables; None if undefined."""
    common = sorted(set(before) & set(after))
    if len(common) < 3:
        return None
    a, b = _ranks([before[k] for k in common]), _ranks([after[k] for k in common])
    mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
    covariance = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
    spread = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** .5
    if spread == 0:
        return None
    return round(1 - covariance / spread, 4)


def trajectory(snapshots, key='wealth_gini', town=None):
    """One measure over the recorded years, for the region or one town."""
    series = []
    for snap in snapshots:
        data = snap.get('inequality')
        if not data:
            continue
        group = data['region'] if town is None else data['towns'].get(town, data['towns'].get(str(town), {}))
        if key in group:
            series.append(dict(year=snap['year'], value=group[key]))
    return series


def decade_mobility(snapshots, span=10):
    """Rank mobility of lineage wealth over every complete span of years in the record."""
    by_year = {snap['year']: snap['inequality']['wealth'] for snap in snapshots if snap.get('inequality')}
    return [dict(start=year, end=year + span, mobility=rank_mobility(by_year[year], by_year[year + span]))
            for year in sorted(by_year) if year + span in by_year]
