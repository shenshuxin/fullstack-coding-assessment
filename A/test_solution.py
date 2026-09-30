"""Tests for Task A - Inventory Reservation Ledger.

Run: python -m pytest A/ -q   (from the repository root)
Covered: the spec example, idempotent replay (incl. replay of a REJECTED
event), boundary validation, malformed input, and open-reservation output.
"""

import time

from solution import Ledger, run


# --- spec example -----------------------------------------------------------

def test_spec_example():
    lines = [
        "10 6",
        "RESERVE e1 o100 4",
        "RESERVE e2 o200 7",
        "SHIP e3 o100 2",
        "RELEASE e4 o100 2",
        "RESTOCK e5 3",
        "RESERVE e2 o999 1",
    ]
    assert run(lines) == [
        "OK 10 4",
        "REJECTED 10 4",
        "OK 8 2",
        "OK 8 0",
        "OK 11 0",
        "DUPLICATE 11 0",
        "OPEN 0",
    ]


# --- idempotency / replay ---------------------------------------------------

def test_replay_of_successful_event_returns_duplicate_without_state_change():
    lines = ["5 3", "RESERVE e1 o1 2", "RESTOCK e2 5", "RESERVE e1 o1 2"]
    assert run(lines) == ["OK 5 2", "OK 10 2", "DUPLICATE 10 2", "OPEN 1", "o1 2"]


def test_rejected_business_operation_is_still_processed():
    # e1 is rejected (not enough stock); replaying it must be DUPLICATE.
    lines = ["3 2", "RESERVE e1 o1 5", "RESERVE e1 o1 1"]
    assert run(lines) == ["REJECTED 3 0", "DUPLICATE 3 0", "OPEN 0"]


def test_duplicate_does_not_change_state_even_with_different_arguments():
    lines = ["9 3", "RESERVE e1 o1 4", "SHIP e2 o1 4", "SHIP e2 o1 1"]
    assert run(lines) == ["OK 9 4", "OK 5 0", "DUPLICATE 5 0", "OPEN 0"]


# --- business rules ---------------------------------------------------------

def test_release_and_ship_cannot_exceed_order_reservation():
    lines = [
        "10 4",
        "RESERVE e1 o1 3",
        "RELEASE e2 o1 4",   # more than reserved for o1
        "SHIP e3 o2 1",      # unknown order
        "SHIP e4 o1 3",      # exactly reserved -> OK
    ]
    assert run(lines) == ["OK 10 3", "REJECTED 10 3", "REJECTED 10 3", "OK 7 0", "OPEN 0"]


def test_reserve_uses_available_not_on_hand():
    # on_hand=10, reserved=8 -> available=2, so reserving 3 must fail.
    lines = ["10 3", "RESERVE e1 o1 8", "RESERVE e2 o2 3", "RESERVE e3 o2 2"]
    assert run(lines) == ["OK 10 8", "REJECTED 10 8", "OK 10 10", "OPEN 2", "o1 8", "o2 2"]


def test_ship_reduces_on_hand_release_does_not():
    lines = ["10 3", "RESERVE e1 o1 5", "RELEASE e2 o1 2", "SHIP e3 o1 1"]
    # release frees availability; ship removes stock entirely
    assert run(lines) == ["OK 10 5", "OK 10 3", "OK 9 2", "OPEN 1", "o1 2"]


# --- validation: malformed input is rejected without state changes ----------

def test_malformed_lines_are_rejected_and_not_recorded():
    lines = [
        "5 7",
        "RESERVE e1 o1",          # wrong arity
        "RESERVE e1 o1 0",        # non-positive qty
        "RESERVE e1 o1 -3",       # negative qty
        "RESERVE e1 o1 2x",       # non-integer qty
        "FLY e2 o1 1",            # unknown verb
        "RESTOCK e3 5",           # valid control
        "RESERVE e1 o1 2",        # e1 was never recorded -> processed normally
    ]
    assert run(lines) == [
        "REJECTED 5 0",
        "REJECTED 5 0",
        "REJECTED 5 0",
        "REJECTED 5 0",
        "REJECTED 5 0",
        "OK 10 0",
        "OK 10 2",
        "OPEN 1",
        "o1 2",
    ]


def test_zero_initial_stock():
    lines = ["0 2", "RESERVE e1 o1 1", "RESTOCK e2 4"]
    assert run(lines) == ["REJECTED 0 0", "OK 4 0", "OPEN 0"]


# --- open reservations output ----------------------------------------------

def test_open_reservations_sorted_by_order_id():
    lines = [
        "20 3",
        "RESERVE e1 o300 3",
        "RESERVE e2 o100 2",
        "RESERVE e3 o200 1",
    ]
    assert run(lines)[-4:] == ["OPEN 3", "o100 2", "o200 1", "o300 3"]


def test_partial_release_keeps_order_open():
    lines = ["10 2", "RESERVE e1 o1 5", "RELEASE e2 o1 2"]
    assert run(lines)[-2:] == ["OPEN 1", "o1 3"]


# --- performance sanity ------------------------------------------------------

def test_200k_commands_run_fast():
    n = 200_000
    lines = [f"{n} {n}"]
    for i in range(n // 2):
        lines.append(f"RESERVE ev{i} ord{i % 1000} 1")
        lines.append(f"SHIP es{i} ord{i % 1000} 1")
    start = time.perf_counter()
    out = run(lines)
    elapsed = time.perf_counter() - start
    assert out[-1] == "OPEN 0"
    assert elapsed < 5.0  # generous bound; typically well under 2s
