"""Banker's Algorithm for deadlock avoidance and safe-state detection."""


def bankers_algorithm(available, allocation, maximum):
    n = len(allocation)

    if n == 0 or len(maximum) != n:
        raise ValueError("Allocation and maximum matrices must have equal non-zero rows.")

    resources = len(available)

    if any(len(row) != resources for row in allocation + maximum):
        raise ValueError("Matrix columns must match available resources.")

    if any(x < 0 for x in available):
        raise ValueError("Available resources cannot be negative.")

    if any(x < 0 for row in allocation + maximum for x in row):
        raise ValueError("Resource values cannot be negative.")

    if any(maximum[i][j] < allocation[i][j]
           for i in range(n) for j in range(resources)):
        raise ValueError("Maximum demand cannot be less than allocation.")

    need = [
        [maximum[i][j] - allocation[i][j] for j in range(resources)]
        for i in range(n)
    ]

    work = available.copy()
    finished = [False] * n
    safe_sequence = []

    while len(safe_sequence) < n:
        found = False

        for i in range(n):
            if not finished[i] and all(
                need[i][j] <= work[j] for j in range(resources)
            ):
                work = [
                    work[j] + allocation[i][j]
                    for j in range(resources)
                ]
                finished[i] = True
                safe_sequence.append(f"P{i}")
                found = True

        if not found:
            break

    return {
        "safe": all(finished),
        "safe_sequence": safe_sequence if all(finished) else [],
        "need_matrix": need,
        "available_resources": available,
    }
