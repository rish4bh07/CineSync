"""Critical-section / seat-lock simulator.
Shows what happens when concurrent booking requests compete for the same seat
WITH a mutex (seat lock) and WITHOUT one (race condition -> double booking)."""
from collections import defaultdict

_STATE_ORDER = {"READY": 0, "WAITING": 1, "RUNNING": 2, "COMPLETED": 3}


def _normalize(requests):
    if not isinstance(requests, list) or not requests:
        raise ValueError("Add at least one booking request.")
    if len(requests) > 20:
        raise ValueError("Maximum 20 requests allowed.")
    out, seen = [], set()
    for i, r in enumerate(requests, 1):
        pid = str(r.get("pid") or f"P{i}").strip()
        if pid in seen:
            raise ValueError(f"Duplicate process id '{pid}'.")
        seen.add(pid)
        seat = str(r.get("seat", "")).strip().upper()
        if not seat:
            raise ValueError(f"Process {pid}: seat is required.")
        try:
            arrival, hold = int(r.get("arrival", 0)), int(r.get("hold", 1))
        except (TypeError, ValueError):
            raise ValueError(f"Process {pid}: arrival and hold must be whole numbers.")
        if arrival < 0 or hold < 1:
            raise ValueError(f"Process {pid}: arrival must be >= 0 and hold >= 1.")
        out.append({"pid": pid, "seat": seat, "arrival": arrival, "hold": hold, "order": i})
    return out


def simulate_seat_lock(requests, use_lock=True):
    reqs = _normalize(requests)
    by_seat = defaultdict(list)
    for r in reqs:
        by_seat[r["seat"]].append(r)
    events, results, conflicts = [], [], []

    for seat, lst in sorted(by_seat.items()):
        lst.sort(key=lambda r: (r["arrival"], r["order"]))
        owner = None
        if use_lock:
            free_at, holder = 0, None
            for r in lst:
                pid = r["pid"]
                events.append((r["arrival"], pid, "READY", f"{pid} requests seat {seat}"))
                start = max(r["arrival"], free_at)
                if start > r["arrival"]:
                    events.append((r["arrival"], pid, "WAITING", f"{pid} blocks - lock on {seat} is held by {holder}"))
                events.append((start, pid, "RUNNING", f"{pid} acquires the lock on {seat} and enters the critical section"))
                finish = start + r["hold"]
                if owner is None:
                    owner, outcome = pid, "BOOKED"
                    msg = f"{pid} confirms the booking of {seat} and releases the lock"
                else:
                    outcome = "REJECTED"
                    msg = f"{pid} sees {seat} is already booked by {owner}, releases the lock"
                events.append((finish, pid, "COMPLETED", msg))
                results.append({"pid": pid, "seat": seat, "arrival": r["arrival"], "start": start,
                                "finish": finish, "wait": start - r["arrival"], "outcome": outcome})
                free_at, holder = finish, pid
        else:
            commits, winners = [], []
            for r in lst:
                pid = r["pid"]
                seen_booked = any(c <= r["arrival"] for c in commits)
                finish = r["arrival"] + r["hold"]
                events.append((r["arrival"], pid, "RUNNING",
                               f"{pid} reads seat {seat}: {'already BOOKED' if seen_booked else 'looks FREE'} (no lock taken)"))
                if seen_booked:
                    outcome, msg = "REJECTED", f"{pid} stops - seat {seat} is taken"
                else:
                    commits.append(finish)
                    winners.append(pid)
                    outcome = "BOOKED"
                    msg = f"{pid} writes the booking for {seat}"
                    if len(winners) > 1:
                        msg += "  ** DOUBLE BOOKING **"
                events.append((finish, pid, "COMPLETED", msg))
                results.append({"pid": pid, "seat": seat, "arrival": r["arrival"], "start": r["arrival"],
                                "finish": finish, "wait": 0, "outcome": outcome})
            if len(winners) > 1:
                conflicts.append({"seat": seat, "processes": winners})

    events.sort(key=lambda e: (e[0], _STATE_ORDER[e[2]]))
    if conflicts:
        summary = "Race condition: " + "; ".join(f"seat {c['seat']} was sold to {' and '.join(c['processes'])}" for c in conflicts) + \
                  ". Without mutual exclusion two processes read 'free' before either wrote."
    elif use_lock:
        summary = "Mutual exclusion held: each seat was sold at most once; late requesters waited, then were rejected safely."
    else:
        summary = "No overlap occurred in this scenario, so no conflict appeared. Increase hold time or make arrivals closer to see a race."
    return {"use_lock": bool(use_lock),
            "events": [{"time": t, "pid": p, "state": s, "message": m} for t, p, s, m in events],
            "results": results, "conflicts": conflicts, "summary": summary}
