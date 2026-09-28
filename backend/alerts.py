"""
CrowdSense Backend Alerts Wrapper Module.
Maintains backward compatibility by routing calls to core.alerts.AlertManager.
"""

from core.alerts import AlertManager

_manager = AlertManager()

def notify(zone: str, status: str, count: int):
    """Legacy helper function for sending zone alerts."""
    incident = {
        "id": f"ALT-{zone}",
        "zone_id": zone,
        "zone_name": f"Zone {zone}",
        "severity": status if status in ("CRITICAL", "HIGH", "WARNING") else "CRITICAL",
        "current_count": count,
        "action_recommended": f"Check camera for Zone {zone} and throttle entry."
    }
    _manager._trigger_notifications(incident, 0.0)
