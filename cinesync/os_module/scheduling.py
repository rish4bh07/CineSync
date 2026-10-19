"""CPU scheduling simulator: FCFS, SJF (non-preemptive), Priority (non-preemptive, lower = higher), Round Robin.
Booking requests are modelled as processes: arrival = request time, burst = processing time."""
from collections import deque

ALGORITHMS = ("FCFS", "SJF", "PRIORITY", "RR")


def _normalize(processes):
    if not isinstance(processes, list) or not processes:
        raise ValueError("Add at least one process.")
    if len(processes) > 20:
        raise ValueError("Maximum 20 processes allowed.")
    out, seen = [], set()
    for i, p in enumerate(processes, 1):
        pid = str(p.get("pid") or f"P{i}").strip()
        if pid in seen:
            raise ValueError(f"Duplicate process id '{pid}'.")
        seen.add(pid)
        try:
            arrival = int(p.get("arrival", 0))
            burst = int(p.get("burst", 1))
            priority = int(p.get("priority", 0) or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Process {pid}: arrival, burst and priority must be whole numbers.")
        if arrival < 0 or burst <= 0:
            raise ValueError(f"Process {pid}: arrival must be >= 0 and burst must be > 0.")
        out.append({"pid": pid, "arrival": arrival, "burst": burst, "priority": priority, "order": i})
    return out


def _non_preemptive(procs, key, log):
    time, gantt = 0, []
    remaining = sorted(procs, key=lambda p: (p["arrival"], p["order"]))
    for p in remaining:
        log.append((p["arrival"], p["pid"], "NEW", "READY"))
    while remaining:
        ready = [p for p in remaining if p["arrival"] <= time]
        if not ready:
            nxt = min(p["arrival"] for p in remaining)
            gantt.append({"pid": "IDLE", "start": time, "end": nxt})
            time = nxt
            continue
        p = min(ready, key=key)
        log.append((time, p["pid"], "READY", "RUNNING"))
        gantt.append({"pid": p["pid"], "start": time, "end": time + p["burst"]})
        time += p["burst"]
        log.append((time, p["pid"], "RUNNING", "COMPLETED"))
        remaining.remove(p)
    return gantt


def _round_robin(procs, quantum, log):
    if quantum <= 0:
        raise ValueError("Time quantum must be greater than 0.")
    pending = sorted(procs, key=lambda p: (p["arrival"], p["order"]))
    rem = {p["pid"]: p["burst"] for p in pending}
    n, idx, time = len(pending), 0, 0
    queue, gantt = deque(), []

    def admit(upto):
        nonlocal idx
        while idx < n and pending[idx]["arrival"] <= upto:
            queue.append(pending[idx])
            log.append((pending[idx]["arrival"], pending[idx]["pid"], "NEW", "READY"))
            idx += 1

    while idx < n or queue:
        admit(time)
        if not queue:
            nxt = pending[idx]["arrival"]
            gantt.append({"pid": "IDLE", "start": time, "end": nxt})
            time = nxt
            continue
        p = queue.popleft()
        run = min(quantum, rem[p["pid"]])
        log.append((time, p["pid"], "READY", "RUNNING"))
        gantt.append({"pid": p["pid"], "start": time, "end": time + run})
        time += run
        rem[p["pid"]] -= run
        admit(time)                      # newcomers join the queue BEFORE the preempted process
        if rem[p["pid"]] > 0:
            queue.append(p)
            log.append((time, p["pid"], "RUNNING", "READY"))
        else:
            log.append((time, p["pid"], "RUNNING", "COMPLETED"))
    return gantt


def _merge(gantt):
    merged = []
    for seg in gantt:
        if merged and merged[-1]["pid"] == seg["pid"] and merged[-1]["end"] == seg["start"]:
            merged[-1]["end"] = seg["end"]
        else:
            merged.append(dict(seg))
    return merged


def schedule(algorithm, processes, quantum=2):
    algo = str(algorithm or "FCFS").upper().replace(" ", "").replace("ROUNDROBIN", "RR")
    if algo not in ALGORITHMS:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Choose one of {', '.join(ALGORITHMS)}.")
    procs = _normalize(processes)
    log = []
    if algo == "FCFS":
        gantt = _non_preemptive(procs, lambda p: (p["arrival"], p["order"]), log)
    elif algo == "SJF":
        gantt = _non_preemptive(procs, lambda p: (p["burst"], p["arrival"], p["order"]), log)
    elif algo == "PRIORITY":
        gantt = _non_preemptive(procs, lambda p: (p["priority"], p["arrival"], p["order"]), log)
    else:
        gantt = _round_robin(procs, int(quantum), log)
    gantt = _merge(gantt)

    first, last = {}, {}
    for g in gantt:
        if g["pid"] == "IDLE":
            continue
        first.setdefault(g["pid"], g["start"])
        last[g["pid"]] = g["end"]

    table = []
    for p in procs:
        ct = last[p["pid"]]
        tat = ct - p["arrival"]
        table.append({"pid": p["pid"], "arrival": p["arrival"], "burst": p["burst"], "priority": p["priority"],
                      "completion": ct, "turnaround": tat, "waiting": tat - p["burst"],
                      "response": first[p["pid"]] - p["arrival"]})
    n = len(table)
    total_time = gantt[-1]["end"] if gantt else 0
    busy = sum(g["end"] - g["start"] for g in gantt if g["pid"] != "IDLE")
    log.sort(key=lambda e: e[0])
    return {
        "algorithm": algo,
        "quantum": int(quantum) if algo == "RR" else None,
        "gantt": gantt,
        "table": table,
        "avg_waiting": round(sum(r["waiting"] for r in table) / n, 2),
        "avg_turnaround": round(sum(r["turnaround"] for r in table) / n, 2),
        "avg_response": round(sum(r["response"] for r in table) / n, 2),
        "cpu_utilization": round(100 * busy / total_time, 1) if total_time else 0,
        "states": [{"time": t, "pid": pid, "from": a, "to": b} for t, pid, a, b in log],
    }
