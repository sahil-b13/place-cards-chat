"""Cost estimate from editable assumptions in costs.json. Every figure is code-computed; nothing from the AI."""
import json
import math
import os
from typing import Optional

from ..schemas import TripCost

COSTS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "costs.json")


def load_costs(path: str = COSTS_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sym(costs: dict) -> str:
    return "₹" if costs.get("currency", "INR") == "INR" else costs.get("currency", "") + " "


def meal_budget(costs: dict, price_level: Optional[int]) -> int:
    table = costs["meal_budget_per_person"]
    if price_level is not None and str(price_level) in table:
        return int(table[str(price_level)])
    return int(table["default"])


def leg_cost(rate_kind: str, distance_km: float, travelers: int, costs: dict) -> float:
    r = costs["rates"]
    if rate_kind == "cab":
        return distance_km * r["cab_per_km"] * math.ceil(travelers / r["cab_seats"])
    if rate_kind == "auto":
        return distance_km * r["auto_per_km"] * math.ceil(travelers / r["auto_seats"])
    if rate_kind == "transit":
        return r["transit_per_leg_per_person"] * travelers
    return 0.0  # walk


def estimate_cost(legs: list[tuple[str, float]], lunch_price_levels: list[Optional[int]], entry_per_person: Optional[float],
                  travelers: int, costs: dict) -> TripCost:
    """legs: [(rate_kind, distance_km)]. lunch_price_levels: one per lunch actually planned."""
    sym = _sym(costs)
    travel = int(round(sum(leg_cost(k, d, travelers, costs) for k, d in legs)))
    food = int(round(sum(meal_budget(costs, pl) * travelers for pl in lunch_price_levels)))
    entry = None if entry_per_person is None else int(round(entry_per_person * travelers))
    total = travel + food + (entry or 0)
    r = costs["rates"]
    kinds = {k for k, _ in legs}
    notes = []
    if "cab" in kinds:
        notes.append(f"Cab {sym}{r['cab_per_km']}/km per vehicle, {r['cab_seats']} seats (editable)")
    if "auto" in kinds:
        notes.append(f"Auto/budget cab {sym}{r['auto_per_km']}/km per vehicle, {r['auto_seats']} seats (editable)")
    if "transit" in kinds:
        notes.append(f"Transit {sym}{r['transit_per_leg_per_person']} per leg per person (editable)")
    if lunch_price_levels:
        notes.append("Lunch uses a per-person meal budget by price level (editable)")
    notes.append("Entry fees are not included unless entered" if entry is None
                 else "Entry fees as entered, per person")
    return TripCost(currency=costs.get("currency", "INR"), travel=travel, food=food, entry=entry,
                    total=total, per_person=int(round(total / travelers)), assumptions=notes[:5], is_estimate=True)
