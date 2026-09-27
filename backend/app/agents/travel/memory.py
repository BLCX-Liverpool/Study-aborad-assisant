from app.schemas.travel import TravelMemoryCandidate, TravelPlanRequest


def build_travel_memory_candidates(request: TravelPlanRequest) -> list[TravelMemoryCandidate]:
    candidates = []
    if request.budget_amount is not None:
        candidates.append(
            TravelMemoryCandidate(
                content=f"Travel budget preference: {request.currency} {request.budget_amount:.2f}.",
                confirmed=request.memory_confirmed,
            )
        )
    if request.accommodation_needed:
        candidates.append(
            TravelMemoryCandidate(
                content="Travel preference: accommodation support is often needed.",
                confirmed=request.memory_confirmed,
            )
        )
    if request.constraints:
        candidates.append(
            TravelMemoryCandidate(
                content="Travel constraints: " + "; ".join(request.constraints[:5]),
                confirmed=request.memory_confirmed,
            )
        )
    return candidates
