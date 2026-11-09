"""Memory allocation algorithms for the OS Lab."""


def allocate_memory(blocks, processes, strategy="first_fit"):
    if any(b <= 0 for b in blocks):
        raise ValueError("Memory blocks must be positive.")
    if any(p <= 0 for p in processes):
        raise ValueError("Process sizes must be positive.")

    if strategy not in ("first_fit", "best_fit", "worst_fit"):
        raise ValueError("Invalid allocation strategy.")

    available = list(blocks)
    results = []

    for index, size in enumerate(processes):
        candidates = [
            i for i, remaining in enumerate(available)
            if remaining >= size
        ]

        if not candidates:
            results.append({
                "process": f"P{index + 1}",
                "size": size,
                "block": None,
                "status": "NOT ALLOCATED",
                "fragment": None,
            })
            continue

        if strategy == "first_fit":
            chosen = candidates[0]
        elif strategy == "best_fit":
            chosen = min(candidates, key=lambda i: available[i])
        else:
            chosen = max(candidates, key=lambda i: available[i])

        available[chosen] -= size

        results.append({
            "process": f"P{index + 1}",
            "size": size,
            "block": f"B{chosen + 1}",
            "status": "ALLOCATED",
            "fragment": available[chosen],
        })

    return {
        "strategy": strategy,
        "allocations": results,
        "remaining_memory": available,
        "total_free_memory": sum(available),
    }
