"""Task B - Fulfilment Split Optimiser.

Allocate exactly Q units across warehouses, optimising in this order:
  1. minimise the number of warehouses used,
  2. then minimise total cost = sum(fixed_cost + qty * unit_cost),
  3. then take the lexicographically smallest allocation list
     (allocations sorted by warehouse_id).

Algorithm
---------
Suffix dynamic programming over warehouses sorted by id.

    suff[i][c][q] = minimum total shipping cost achievable using only
                    warehouses[i..W-1], exactly c of them, allocating
                    exactly q units.  INF if impossible.

Transition for warehouse i (id, stock, fixed, unit):
    skip it : suff[i+1][c][q]
    use it  : min over x in 1..min(stock, q) of
                  suff[i+1][c-1][q-x] + fixed + unit * x

The inner minimum is a sliding-window minimum over
    g[m] = suff[i+1][c-1][m] - unit * m,   m in [q - stock, q - 1]
so a monotone deque makes each (i, c) row O(Q) instead of O(Q * stock).

The answer is (c*, cost*) = argmin over c of suff[0][c][Q] ordered by
(c, cost). Reconstruction walks the warehouses in id order and, for each,
greedily chooses the lexicographically smallest feasible allocation:
taking the warehouse (x >= 1) always beats skipping it, because any
allocation that includes id_i has a strictly smaller next list element
than one whose next element is a larger id; among feasible x values the
smallest x wins (same id, smaller quantity). Feasibility of a candidate
choice is checked exactly against the suffix table, so the (c, cost)
optimum is preserved.

Complexity: time O(W^2 * Q), space O(W^2 * Q) integers.
With W <= 30, Q <= 2000 that is ~1.8M deque operations and ~15 MB
(stored in array('q')), well within limits. A subset brute force would
be O(2^W), which does not scale.

Run:  python solution.py < input.txt
"""

from __future__ import annotations

import sys
from array import array
from collections import deque

INF = 1 << 62  # fits in signed int64; real costs are <= ~6e13


def solve(warehouses: list[tuple[str, int, int, int]], Q: int):
    """warehouses: list of (id, stock, fixed_cost, unit_cost).

    Returns (allocations, total_cost) where allocations is a list of
    (warehouse_id, qty) sorted by id, or None if impossible.
    """
    warehouses = sorted(warehouses, key=lambda w: w[0])
    W = len(warehouses)

    # suff[i][c] -> array('q') of length Q+1
    base = [array("q", [INF]) * (Q + 1) for _ in range(W + 1)]
    base[0][0] = 0
    suff: list[list[array]] = [None] * (W + 1)  # type: ignore[list-item]
    suff[W] = base

    for i in range(W - 1, -1, -1):
        _wid, stock, fixed, unit = warehouses[i]
        nxt = suff[i + 1]
        cur = [array("q", nxt[c]) for c in range(W + 1)]  # "skip" is the default
        cap = min(stock, Q)
        if cap == 0:
            # zero-stock warehouse can only ever be skipped
            suff[i] = cur
            continue
        for c in range(1, W + 1):
            prev = nxt[c - 1]
            row = cur[c]
            dq: deque[tuple[int, int]] = deque()
            for q in range(1, Q + 1):
                m = q - 1
                pm = prev[m]
                gm = pm - unit * m if pm < INF // 2 else INF
                while dq and dq[-1][1] >= gm:
                    dq.pop()
                dq.append((m, gm))
                # window is m in [q - cap, q - 1]
                while dq and dq[0][0] < q - cap:
                    dq.popleft()
                best = dq[0][1]
                if best < INF // 2:
                    cand = best + unit * q + fixed
                    if cand < row[q]:
                        row[q] = cand
        suff[i] = cur

    # pick the optimum: fewest warehouses FIRST, then lowest cost.
    # c ascends, so the first feasible c is the minimal warehouse count,
    # and suff[0][c][Q] is already the minimal cost for that count.
    best_c, best_cost = -1, INF
    for c in range(1, W + 1):
        v = suff[0][c][Q]
        if v < INF // 2:
            best_c, best_cost = c, v
            break
    if best_c <= 0:
        return None

    # greedy lexicographic reconstruction, verified against the suffix table
    allocations: list[tuple[str, int]] = []
    c, q, cost = best_c, Q, best_cost
    for i in range(W):
        wid, stock, fixed, unit = warehouses[i]
        chosen = 0
        if c > 0 and q > 0:
            for x in range(1, min(stock, q) + 1):
                if suff[i + 1][c - 1][q - x] == cost - fixed - unit * x:
                    chosen = x
                    break
        if chosen:
            allocations.append((wid, chosen))
            c -= 1
            q -= chosen
            cost -= fixed + unit * chosen
    return allocations, best_cost


def run(text: str) -> str:
    tokens = text.split("\n")
    first = tokens[0].split()
    W, Q = int(first[0]), int(first[1])
    warehouses = []
    for line in tokens[1 : 1 + W]:
        wid, stock, fixed, unit = line.split()
        warehouses.append((wid, int(stock), int(fixed), int(unit)))

    result = solve(warehouses, Q)
    if result is None:
        return "-1"
    allocations, total = result
    out = [f"{len(allocations)} {total}"]
    out.extend(f"{wid} {qty}" for wid, qty in allocations)
    return "\n".join(out)


def main() -> None:
    sys.stdout.write(run(sys.stdin.read()) + "\n")


if __name__ == "__main__":
    main()
