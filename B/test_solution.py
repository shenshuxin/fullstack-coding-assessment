"""Tests for Task B - Fulfilment Split Optimiser.

Run: python -m pytest B/ -q   (from the repository root)
Includes a brute-force oracle that cross-checks (warehouse count, total cost)
on hundreds of random small cases, plus the required edge cases.
"""

import itertools
import random

from solution import run, solve


# --- brute-force oracle (small cases only) ----------------------------------

def brute_force(warehouses, Q):
    """Exhaustive oracle: returns (count, cost, allocation_tuple) or None."""
    best = [None]  # list cell so the nested closure can mutate it

    def rec(subset, idx, remaining, alloc, cost):
        if idx == len(subset):
            if remaining == 0:
                cand = (len(subset), cost, tuple(sorted(alloc)))
                if best[0] is None or cand < best[0]:
                    best[0] = cand
            return
        wid, stock, _fixed, unit = subset[idx]
        fixed = subset[idx][2]
        for x in range(1, min(stock, remaining) + 1):
            rec(subset, idx + 1, remaining - x, alloc + [(wid, x)], cost + fixed + unit * x)

    for r in range(1, len(warehouses) + 1):
        for subset in itertools.combinations(warehouses, r):
            rec(subset, 0, Q, [], 0)
    return best[0]


# --- spec example ------------------------------------------------------------

def test_spec_example():
    text = "3 7\nAU 5 8 2\nCN 7 20 1\nUS 4 3 4\n"
    assert run(text) == "1 27\nCN 7"


# --- required edge cases ------------------------------------------------------

def test_impossible_order_prints_minus_one():
    text = "2 10\nAU 4 1 1\nUS 5 1 1\n"
    assert run(text) == "-1"


def test_zero_stock_warehouse_is_never_used():
    text = "2 3\nAU 0 0 0\nUS 3 5 1\n"
    assert run(text) == "1 8\nUS 3"


def test_fewest_warehouses_beats_cheaper_cost():
    # Splitting across AU+US would be cheaper (8+3*2=14 + 3+2*4=25)
    # than CN alone (20+5*1=25)? make CN clearly more expensive:
    text = "3 5\nAU 3 1 1\nCN 5 50 9\nUS 2 1 1\n"
    # one warehouse: only CN can do 5 -> cost 50+45=95; two warehouses cheaper
    # but must still pick the single-warehouse solution.
    assert run(text) == "1 95\nCN 5"


def test_equal_cost_tie_breaks_to_lexicographically_smallest_list():
    # AU and ZZ have identical economics; both can fulfil alone.
    text = "2 4\nAU 4 10 2\nZZ 4 10 2\n"
    assert run(text) == "1 18\nAU 4"


def test_lexicographic_prefers_including_earlier_id_over_skipping():
    # Single-warehouse solutions exist for both AU and CN at equal cost;
    # [(AU, ...)] < [(CN, ...)] regardless of quantity.
    text = "2 3\nAU 3 4 1\nCN 3 4 1\n"
    assert run(text) == "1 7\nAU 3"


def test_smaller_quantity_at_same_warehouse_wins_tie():
    # No single warehouse can fulfil Q=3, so exactly 2 must be used.
    # AU can take 1 or 2 (CN takes the rest) at identical cost (unit cost 0),
    # so the lexicographically smallest list picks AU's smaller quantity.
    text = "2 3\nAU 2 5 0\nCN 2 5 0\n"
    assert run(text) == "2 10\nAU 1\nCN 2"


def test_exact_stock_boundary():
    text = "1 2000\nW1 2000 0 0\n"
    assert run(text) == "1 0\nW1 2000"


# --- randomised cross-check against the oracle --------------------------------

def test_matches_brute_force_on_random_small_cases():
    rng = random.Random(20260930)
    for _ in range(300):
        w = rng.randint(1, 5)
        warehouses = []
        ids = rng.sample(
            ["AU", "CN", "US", "DE", "JP", "BR", "NZ", "ZA"], w)
        for wid in ids:
            warehouses.append((
                wid,
                rng.randint(0, 6),
                rng.randint(0, 8),
                rng.randint(0, 4),
            ))
        total_stock = sum(s for _, s, _, _ in warehouses)
        Q = rng.randint(1, max(1, total_stock + 2))
        expected = brute_force(warehouses, Q)
        got = solve(warehouses, Q)
        if expected is None:
            assert got is None, f"expected impossible, got {got}"
        else:
            assert got is not None, f"expected solution, got None; case={warehouses} Q={Q}"
            alloc, cost = got
            assert len(alloc) == expected[0], f"count mismatch: {got} vs {expected}"
            assert cost == expected[1], f"cost mismatch: {got} vs {expected}"
            assert tuple(alloc) == expected[2], f"alloc mismatch: {got} vs {expected}"


def test_large_case_performance():
    # W=30, Q=2000: the DP must finish comfortably.
    import time

    rng = random.Random(7)
    warehouses = [
        (f"W{i:02d}", rng.randint(0, 2000), rng.randint(0, 10**6), rng.randint(0, 10**6))
        for i in range(30)
    ]
    start = time.perf_counter()
    result = solve(warehouses, 2000)
    elapsed = time.perf_counter() - start
    assert result is not None
    assert elapsed < 30.0  # typical: a few seconds
