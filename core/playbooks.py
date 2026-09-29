"""
Action Playbooks Module.
Maps zone states, severity, and risk reasons to concrete, prioritized operator intervention steps.
"""

from typing import List, Dict, Any, Optional

# Default Action Playbooks
ACTION_PLAYBOOKS: Dict[str, List[str]] = {
    "CRITICAL_DEFAULT": [
        "Pause entry inflow at upstream entrance gates immediately",
        "Open designated emergency exit and bypass corridors",
        "Deploy rapid-response crowd safety team (min. 4 personnel)"
    ],
    "CONGESTION_STAGNATION": [
        "Throttle turnstile entry rate by 50%",
        "Deploy 2 field marshals to guide crowd forward and clear stagnation",
        "Make public address announcement advising continuous movement"
    ],
    "OPPOSING_FLOW": [
        "Deploy portable stanchion lane dividers along main corridor",
        "Redirect inbound pedestrian flow to alternate secondary lane",
        "Position field staff at merge point to enforce one-way flow"
    ],
    "HIGH_DENSITY": [
        "Prepare overflow holding pen / buffer queue area",
        "Verify live CCTV camera feeds at adjacent bottlenecks",
        "Alert secondary response team to standby"
    ],
    "WARNING_DENSITY": [
        "Routine visual monitoring of entry gates",
        "Check automated inflow counters against venue capacity"
    ],
    "NORMAL": [
        "Standard perimeter safety observation"
    ]
}

def get_recommended_actions(
    zone_name: str,
    severity: str,
    reasons: Optional[List[str]] = None,
    risk_score: float = 0.0
) -> List[str]:
    """
    Returns prioritized list of actionable recommendations for safety operators based on zone state and reasons.
    """
    reasons_str = " ".join(reasons or []).lower()
    actions = []

    if severity == "CRITICAL":
        actions.extend(ACTION_PLAYBOOKS["CRITICAL_DEFAULT"])
        if "opposing" in reasons_str:
            actions.append(f"Install emergency lane separation in {zone_name}")
    elif severity == "CONGESTION":
        if "opposing" in reasons_str:
            actions.extend(ACTION_PLAYBOOKS["OPPOSING_FLOW"])
        else:
            actions.extend(ACTION_PLAYBOOKS["CONGESTION_STAGNATION"])
    elif severity == "HIGH":
        if "opposing" in reasons_str:
            actions.extend(ACTION_PLAYBOOKS["OPPOSING_FLOW"])
        else:
            actions.extend(ACTION_PLAYBOOKS["HIGH_DENSITY"])
    elif severity == "WARNING":
        actions.extend(ACTION_PLAYBOOKS["WARNING_DENSITY"])
    else:
        actions.extend(ACTION_PLAYBOOKS["NORMAL"])

    # Prefix with zone context
    return [a.replace("upstream entrance gates", f"upstream gates for {zone_name}") for a in actions]

def format_action_summary(actions: List[str]) -> str:
    """Combines actions list into concise summary for SMS / notification text."""
    if not actions:
        return "Maintain routine monitoring."
    return "; ".join(actions[:2])
