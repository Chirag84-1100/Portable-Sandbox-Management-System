"""CPU Scheduling algorithms for the OS Lab."""


def fcfs(processes):
    """First Come First Serve scheduling."""
    return _calculate(processes, sorted(processes, key=lambda p: p["arrival"]))


def sjf(processes):
    """Non-preemptive Shortest Job First scheduling."""
    remaining = list(processes)
    ordered = []
    time = 0

    while remaining:
        available = [p for p in remaining if p["arrival"] <= time]

        if not available:
            time = min(p["arrival"] for p in remaining)
            continue

        selected = min(available, key=lambda p: (p["burst"], p["arrival"]))
        ordered.append(selected)
        remaining.remove(selected)
        time += selected["burst"]

    return _calculate(processes, ordered)


def round_robin(processes, quantum):
    """Round Robin scheduling."""
    if quantum <= 0:
        raise ValueError("Time quantum must be greater than zero.")

    remaining = {p["pid"]: p["burst"] for p in processes}
    arrival = {p["pid"]: p["arrival"] for p in processes}
    completed = {}
    queue = []
    timeline = []
    time = 0
    pending = sorted(processes, key=lambda p: p["arrival"])
    index = 0

    while len(completed) < len(processes):
        while index < len(pending) and pending[index]["arrival"] <= time:
            queue.append(pending[index]["pid"])
            index += 1

        if not queue:
            time = pending[index]["arrival"]
            continue

        pid = queue.pop(0)
        duration = min(quantum, remaining[pid])
        start = time
        time += duration
        remaining[pid] -= duration
        timeline.append({"pid": pid, "start": start, "end": time})

        while index < len(pending) and pending[index]["arrival"] <= time:
            queue.append(pending[index]["pid"])
            index += 1

        if remaining[pid] > 0:
            queue.append(pid)
        else:
            completed[pid] = time

    results = []
    for p in processes:
        completion = completed[p["pid"]]
        turnaround = completion - p["arrival"]
        waiting = turnaround - p["burst"]
        results.append({
            "pid": p["pid"],
            "arrival": p["arrival"],
            "burst": p["burst"],
            "completion": completion,
            "turnaround": turnaround,
            "waiting": waiting,
        })

    return _summary(results, timeline)


def _calculate(processes, ordered):
    time = 0
    timeline = []
    results = []

    for p in ordered:
        start = max(time, p["arrival"])
        completion = start + p["burst"]
        time = completion
        timeline.append({"pid": p["pid"], "start": start, "end": completion})

        turnaround = completion - p["arrival"]
        waiting = turnaround - p["burst"]

        results.append({
            "pid": p["pid"],
            "arrival": p["arrival"],
            "burst": p["burst"],
            "completion": completion,
            "turnaround": turnaround,
            "waiting": waiting,
        })

    return _summary(results, timeline)


def _summary(results, timeline):
    count = len(results)
    return {
        "processes": results,
        "timeline": timeline,
        "average_waiting_time": round(
            sum(p["waiting"] for p in results) / count, 2
        ) if count else 0,
        "average_turnaround_time": round(
            sum(p["turnaround"] for p in results) / count, 2
        ) if count else 0,
    }


def validate_processes(processes):
    if not processes:
        raise ValueError("At least one process is required.")

    ids = [p["pid"] for p in processes]
    if len(ids) != len(set(ids)):
        raise ValueError("Process IDs must be unique.")

    for p in processes:
        if p["arrival"] < 0 or p["burst"] <= 0:
            raise ValueError("Arrival time must be non-negative and burst time positive.")
