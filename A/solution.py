"""Task A - Inventory Reservation Ledger.

Deterministic command processor for a single SKU.

Design decisions:
- State is a single Ledger object (on_hand, reserved total, per-order reserved,
  processed event ids). All commands are validated *before* any mutation, so a
  rejected command never produces a partial state change.
- Idempotency: every syntactically valid command whose business outcome was
  decided (OK *or* REJECTED) records its event_id. Replaying that event_id
  returns DUPLICATE without touching state, matching the rule that "a rejected
  business operation is still considered processed".
- Syntactically malformed lines (unknown verb, wrong arity, non-ASCII ids,
  non-positive-integer qty) are REJECTED but NOT recorded: they were never a
  well-formed business operation, so there is nothing safe to deduplicate.
- All lookups are dict/set operations, so processing N commands is O(N).

Run:  python solution.py < input.txt
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

OK = "OK"
REJECTED = "REJECTED"
DUPLICATE = "DUPLICATE"

# command -> number of tokens expected on the line
_ARITY = {"RESERVE": 4, "RELEASE": 4, "SHIP": 4, "RESTOCK": 3}


def _is_ascii_token(s: str) -> bool:
    # event_id / order_id must be non-empty ASCII tokens
    return bool(s) and s.isascii()


def _parse_positive_int(token: str) -> int | None:
    """Return the int value of a positive-integer token, else None.

    str.isdigit() alone would accept unicode digits (e.g. superscripts), so we
    require ASCII digits explicitly. int() is wrapped because Python 3.11+
    rejects integer strings over ~4300 digits with ValueError — a malformed
    input must be REJECTED, not crash the processor.
    """
    if not token or not token.isascii() or not token.isdigit():
        return None
    try:
        value = int(token)
    except ValueError:
        return None
    return value if value > 0 else None


@dataclass
class Ledger:
    on_hand: int
    reserved: int = 0
    per_order: dict[str, int] = field(default_factory=dict)
    processed: set[str] = field(default_factory=set)

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    def _reduce_order(self, order_id: str, qty: int) -> None:
        remaining = self.per_order[order_id] - qty
        if remaining:
            self.per_order[order_id] = remaining
        else:
            del self.per_order[order_id]
        self.reserved -= qty

    # --- business operations; return True on success, False on rejection ---
    def reserve(self, order_id: str, qty: int) -> bool:
        if qty > self.available:
            return False
        self.reserved += qty
        self.per_order[order_id] = self.per_order.get(order_id, 0) + qty
        return True

    def release(self, order_id: str, qty: int) -> bool:
        if qty > self.per_order.get(order_id, 0):
            return False
        self._reduce_order(order_id, qty)
        return True

    def ship(self, order_id: str, qty: int) -> bool:
        if qty > self.per_order.get(order_id, 0):
            return False
        self._reduce_order(order_id, qty)
        self.on_hand -= qty
        return True

    def restock(self, qty: int) -> bool:
        self.on_hand += qty
        return True

    # --- command dispatch ---
    def process_line(self, line: str) -> str:
        """Process one command line; return OK / REJECTED / DUPLICATE."""
        tokens = line.split()
        if not tokens:
            return REJECTED
        cmd = tokens[0]
        if cmd not in _ARITY or len(tokens) != _ARITY[cmd]:
            return REJECTED

        event_id = tokens[1]
        if not _is_ascii_token(event_id):
            return REJECTED

        if cmd == "RESTOCK":
            qty = _parse_positive_int(tokens[2])
            if qty is None:
                return REJECTED
            if event_id in self.processed:
                return DUPLICATE
            ok = self.restock(qty)
        else:
            order_id = tokens[2]
            qty = _parse_positive_int(tokens[3])
            if not _is_ascii_token(order_id) or qty is None:
                return REJECTED
            if event_id in self.processed:
                return DUPLICATE
            if cmd == "RESERVE":
                ok = self.reserve(order_id, qty)
            elif cmd == "RELEASE":
                ok = self.release(order_id, qty)
            else:  # SHIP
                ok = self.ship(order_id, qty)

        # A decided business outcome (OK or REJECTED) is recorded so that a
        # replay of the same event_id is reported as DUPLICATE.
        self.processed.add(event_id)
        return OK if ok else REJECTED


def run(lines: list[str]) -> list[str]:
    """Process input lines, return output lines (pure, testable)."""
    out: list[str] = []
    if not lines:
        return out
    header = lines[0].split()
    if len(header) != 2:
        raise ValueError("first line must be: S N")
    s_val, n_val = header
    if not (s_val.isascii() and s_val.isdigit() and n_val.isascii() and n_val.isdigit()):
        raise ValueError("S and N must be non-negative integers")
    ledger = Ledger(on_hand=int(s_val))
    n = int(n_val)

    for line in lines[1 : 1 + n]:
        status = ledger.process_line(line)
        out.append(f"{status} {ledger.on_hand} {ledger.reserved}")

    open_orders = sorted(ledger.per_order.items())
    out.append(f"OPEN {len(open_orders)}")
    for order_id, qty in open_orders:
        out.append(f"{order_id} {qty}")
    return out


def main() -> None:
    lines = sys.stdin.read().splitlines()
    sys.stdout.write("\n".join(run(lines)) + "\n")


if __name__ == "__main__":
    main()
