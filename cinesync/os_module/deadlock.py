"""Wait-for-graph deadlock detection and recovery.
Edge  Pi -> Pj  means  "Pi is waiting for a resource (seat lock) held by Pj"."""


def build_wait_for_graph(holds, requests):
    """holds: {pid: [resource,...]}   requests: {pid: [resource,...]}  ->  wait-for graph."""
    owner = {}
    for pid, resources in (holds or {}).items():
        for r in resources:
            owner[r] = pid
    nodes = set(holds or {}) | set(requests or {})
    graph = {p: set() for p in nodes}
    for pid, resources in (requests or {}).items():
        for r in resources:
            holder = owner.get(r)
            if holder and holder != pid:
                graph[pid].add(holder)
    return {p: sorted(v) for p, v in graph.items()}


def _clean(graph):
    if not isinstance(graph, dict) or not graph:
        raise ValueError("Provide at least one wait-for edge, e.g. P1 -> P2.")
    g = {}
    for k, v in graph.items():
        g.setdefault(str(k), set()).update(str(x) for x in (v or []))
    for targets in list(g.values()):
        for t in targets:
            g.setdefault(t, set())
    if len(g) > 30:
        raise ValueError("Maximum 30 processes allowed.")
    return {k: sorted(v) for k, v in g.items()}


def _find_cycles(graph):
    cycles, color, stack = [], {n: 0 for n in graph}, []

    def dfs(u):
        color[u] = 1
        stack.append(u)
        for v in graph[u]:
            if color[v] == 0:
                dfs(v)
            elif color[v] == 1:
                cycles.append(stack[stack.index(v):])
        stack.pop()
        color[u] = 2

    for n in sorted(graph):
        if color[n] == 0:
            dfs(n)
    unique, seen = [], set()
    for c in cycles:
        i = c.index(min(c))
        canon = tuple(c[i:] + c[:i])
        if canon not in seen:
            seen.add(canon)
            unique.append(list(canon))
    return unique


def _pick_victim(cycles):
    count = {}
    for c in cycles:
        for p in c:
            count[p] = count.get(p, 0) + 1
    # most cycles broken first; ties -> highest id (treated as the "youngest"/cheapest to roll back)
    return sorted(count, key=lambda p: (-count[p], [-ord(ch) for ch in p]))[0]


def detect_deadlock(graph):
    graph = _clean(graph)
    cycles = _find_cycles(graph)
    result = {"deadlock": bool(cycles), "graph": graph, "cycles": cycles,
              "deadlocked_processes": sorted({p for c in cycles for p in c}),
              "victims": [], "graph_after": graph, "recovery": [], "prevention": []}
    if not cycles:
        result["explanation"] = "No cycle found in the wait-for graph, so no process is deadlocked. Every waiting process will eventually get its lock."
        return result

    work = {k: list(v) for k, v in graph.items()}
    victims, cyc = [], cycles
    while cyc:
        v = _pick_victim(cyc)
        victims.append(v)
        work.pop(v)
        work = {k: [x for x in t if x != v] for k, t in work.items()}
        cyc = _find_cycles(work) if work else []
    result["victims"] = victims
    result["graph_after"] = work
    result["explanation"] = ("Deadlock detected: " + "; ".join(" -> ".join(c + [c[0]]) for c in cycles) +
                             ". Each process in the cycle holds a seat lock that the next one needs, so none can proceed "
                             "(mutual exclusion + hold-and-wait + no preemption + circular wait).")
    result["recovery"] = [
        f"Abort victim process {', '.join(victims)}: the booking transaction is ROLLED BACK, which releases every seat lock it held.",
        "The remaining processes acquire the freed seats and complete; the wait-for graph becomes acyclic (see graph after recovery).",
        "The victim is restarted later (the user simply retries the booking).",
        "Alternative: resource preemption - forcibly take one seat lock from a victim and roll it back to a safe state.",
    ]
    result["prevention"] = [
        "CineSync locks seats in ascending seat_id order inside one transaction, which removes circular wait.",
        "MySQL InnoDB also detects deadlocks itself and rolls back one transaction (error 1213).",
    ]
    return result
