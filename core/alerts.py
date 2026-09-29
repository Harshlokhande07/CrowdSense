"""
Alert Pipeline & Notification Integration Module.
Implements per-zone incident state machine (NORMAL -> WARNING -> HIGH -> CONGESTION -> CRITICAL),
lazy-initialization of Firestore and Twilio integrations, and background worker for ntfy alerts.
"""

import os
import time
import logging
import threading
import queue
import requests
from typing import List, Dict, Any, Optional, Tuple

from core.config import (
    NTFY_TOPIC,
    ENABLE_MOBILE_ALERT,
    FIREBASE_KEY_PATH,
    ALERT_COOLDOWN_SEC,
    DEESCALATION_HYSTERESIS_SEC,
    DEESCALATION_HYSTERESIS_MARGIN,
    SMS_MIN_LEVEL,
    SMS_COOLDOWN_SEC,
    SMS_SEND_RESOLVED,
    TWILIO_ENABLED
)
from core.playbooks import get_recommended_actions, format_action_summary
from core.notifier import twilio_notifier

logger = logging.getLogger("CrowdSense.Alerts")

# Entry threshold mappings for severity levels
SEVERITY_ENTRY_THRESHOLDS = {
    "CRITICAL": 70.0,
    "CONGESTION": 45.0,
    "HIGH": 30.0,
    "WARNING": 20.0,
    "NORMAL": 0.0
}

class AlertManager:
    def __init__(self, demo_mode: bool = False, camera_name: str = "Main Camera"):
        self.demo_mode = demo_mode
        self.camera_name = camera_name
        # Service status indicators
        self.db_status = "NOT_CONFIGURED"
        self.ntfy_status = "READY" if ENABLE_MOBILE_ALERT else "DISABLED"

        self.db = None

        # Zone Active Incidents: zone_id -> Incident dict
        self.active_incidents: Dict[str, Dict[str, Any]] = {}
        # Recent Alerts History (in-memory deque)
        self.alerts_history: List[Dict[str, Any]] = []

        # Notification cooldown trackers
        self.last_notify_time: Dict[str, float] = {}
        self.last_notify_level: Dict[str, str] = {}

        # Twilio SMS / WhatsApp cooldown trackers
        self.last_sms_time: Dict[str, float] = {}
        self.last_sms_level: Dict[str, str] = {}

        # De-escalation and resolution hysteresis timers
        self.deescalation_candidate: Dict[str, Tuple[str, float]] = {}  # zone_id -> (lower_severity, start_time)
        self.resolution_start_time: Dict[str, float] = {}  # zone_id -> start_time

        # Background notification queue & bounded worker thread for ntfy & firestore
        self.notify_queue = queue.Queue(maxsize=50)
        self.dropped_notifications_count: int = 0
        self.worker_thread = threading.Thread(target=self._notification_worker, daemon=True)
        self.worker_thread.start()

        # Lazy service init
        self._init_services()

    def reset(self):
        """Clears active incidents, history, cooldowns, and hysteresis timers on source switch."""
        self.active_incidents.clear()
        self.alerts_history.clear()
        self.last_notify_time.clear()
        self.last_notify_level.clear()
        self.last_sms_time.clear()
        self.last_sms_level.clear()
        self.deescalation_candidate.clear()
        self.resolution_start_time.clear()

    def _init_services(self):
        """Attempts to lazy-initialize Firestore without crashing."""
        # 1. Firestore Lazy Init
        fb_path = FIREBASE_KEY_PATH or os.getenv("FIREBASE_KEY", "")
        if fb_path and os.path.exists(fb_path):
            try:
                import firebase_admin
                from firebase_admin import credentials, firestore
                if not firebase_admin._apps:
                    cred = credentials.Certificate(fb_path)
                    firebase_admin.initialize_app(cred)
                self.db = firestore.client()
                self.db_status = "CONNECTED"
                logger.info("Firestore client initialized successfully.")
            except Exception as e:
                logger.error(f"Firestore initialization failed: {e}")
                self.db_status = "DISCONNECTED"
                self.db = None
        else:
            self.db_status = "NOT_CONFIGURED"

    @property
    def twilio_status(self) -> str:
        return twilio_notifier.get_status()

    @staticmethod
    def _severity_level(severity: str) -> int:
        levels = {"NORMAL": 0, "WARNING": 1, "HIGH": 2, "CONGESTION": 3, "CRITICAL": 4}
        return levels.get(severity, 0)

    def _evaluate_raw_severity(self, risk_score: float, level: str, is_bottleneck: bool) -> str:
        """Determines target severity before hysteresis check."""
        if risk_score >= 70 or level == "CRITICAL":
            return "CRITICAL"
        elif risk_score >= 45 or is_bottleneck:
            return "CONGESTION"
        elif level == "HIGH" or risk_score >= 30:
            return "HIGH"
        elif level == "ELEVATED" or risk_score >= 20:
            return "WARNING"
        return "NORMAL"

    def process_zone_states(
        self,
        zones: List[Dict[str, Any]],
        bottlenecks: List[Dict[str, Any]],
        predictions: List[Dict[str, Any]],
        now: float
    ) -> List[Dict[str, Any]]:
        """
        Runs the per-zone incident state machine with:
        - Instant escalation
        - Hysteresis de-escalation (requires staying >= 5 pts below entry threshold for >= 3s)
        - Single active incident per zone & 3s NORMAL resolution rule
        - Cooldown throttling for repeat notifications at same level
        """
        bn_map = {b["zone_id"]: b for b in bottlenecks}
        pred_map = {p["zone_id"]: p for p in predictions}

        current_active_alerts = []

        for z in zones:
            z_id = z["id"]
            z_name = z["name"]
            count = z["count"]
            level = z["level"]

            bn_info = bn_map.get(z_id, {})
            risk_score = float(bn_info.get("score", 0))
            bn_reasons = bn_info.get("reasons", [])
            is_bn = bn_info.get("is_bottleneck", False)

            raw_severity = self._evaluate_raw_severity(risk_score, level, is_bn)

            # Check if an incident already exists for this zone
            if z_id in self.active_incidents:
                incident = self.active_incidents[z_id]
                current_sev = incident["severity"]
                curr_rank = self._severity_level(current_sev)
                raw_rank = self._severity_level(raw_severity)

                effective_severity = current_sev

                if raw_rank > curr_rank:
                    # ESCALATION: immediate transition without delay
                    effective_severity = raw_severity
                    self.deescalation_candidate.pop(z_id, None)
                    self.resolution_start_time.pop(z_id, None)
                elif raw_rank < curr_rank:
                    # DE-ESCALATION / RESOLUTION: requires hysteresis margin and duration check
                    entry_thresh = SEVERITY_ENTRY_THRESHOLDS.get(current_sev, 0.0)
                    hysteresis_margin_met = (risk_score <= (entry_thresh - DEESCALATION_HYSTERESIS_MARGIN))

                    if raw_severity == "NORMAL":
                        # Check resolution duration
                        if z_id not in self.resolution_start_time:
                            self.resolution_start_time[z_id] = now
                        if (now - self.resolution_start_time[z_id] >= DEESCALATION_HYSTERESIS_SEC) and hysteresis_margin_met:
                            # Resolve incident
                            incident["status"] = "RESOLVED"
                            incident["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                            self._record_alert_history(incident)
                            self.active_incidents.pop(z_id, None)
                            self.resolution_start_time.pop(z_id, None)
                            self.deescalation_candidate.pop(z_id, None)
                            self.last_notify_level.pop(z_id, None)

                            # Send SMS resolved alert if configured
                            if SMS_SEND_RESOLVED and self._severity_level(self.last_sms_level.get(z_id, "NORMAL")) >= self._severity_level(SMS_MIN_LEVEL):
                                self._trigger_sms_notifications(
                                    zone_id=z_id,
                                    zone_name=z_name,
                                    level="NORMAL",
                                    score=int(risk_score),
                                    reasons=["Conditions returned to normal"],
                                    kind="RESOLVED",
                                    now=now,
                                    recommended_actions=[]
                                )
                            self.last_sms_level.pop(z_id, None)
                            self.last_sms_time.pop(z_id, None)

                            logger.info(f"Incident resolved for {z_name}")
                            continue
                    else:
                        # De-escalating one or more levels
                        cand = self.deescalation_candidate.get(z_id)
                        if cand is None or cand[0] != raw_severity:
                            self.deescalation_candidate[z_id] = (raw_severity, now)
                        else:
                            cand_sev, cand_start = cand
                            if (now - cand_start >= DEESCALATION_HYSTERESIS_SEC) and hysteresis_margin_met:
                                effective_severity = cand_sev
                                self.deescalation_candidate.pop(z_id, None)
                else:
                    # Stable state: reset hysteresis candidate timers
                    self.deescalation_candidate.pop(z_id, None)
                    self.resolution_start_time.pop(z_id, None)

                # UPDATE active incident state
                is_escalation = (self._severity_level(effective_severity) > curr_rank)
                incident["severity"] = effective_severity
                incident["peak_count"] = max(incident["peak_count"], count)
                incident["current_count"] = count
                incident["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                incident["duration_s"] = round(now - incident["start_ts"], 1)
                incident["reasons"] = bn_reasons
                actions = get_recommended_actions(z_name, effective_severity, bn_reasons, risk_score)
                incident["recommended_actions"] = actions
                incident["action_recommended"] = format_action_summary(actions)

                if is_escalation:
                    incident["status"] = "ACTIVE"
                    self._trigger_notifications(incident, now, is_escalation=True)
                    self._trigger_sms_notifications(
                        zone_id=z_id,
                        zone_name=z_name,
                        level=effective_severity,
                        score=int(risk_score),
                        reasons=bn_reasons,
                        kind="ESCALATION",
                        now=now,
                        recommended_actions=actions
                    )
                else:
                    self._trigger_notifications(incident, now, is_escalation=False)
                    if effective_severity == current_sev:
                        self._trigger_sms_notifications(
                            zone_id=z_id,
                            zone_name=z_name,
                            level=effective_severity,
                            score=int(risk_score),
                            reasons=bn_reasons,
                            kind="REPEAT",
                            now=now,
                            recommended_actions=actions
                        )
                    else:
                        # De-escalation: do not send SMS, update level tracker
                        self.last_sms_level[z_id] = effective_severity

                current_active_alerts.append(incident)

            else:
                if raw_severity != "NORMAL":
                    # CREATE NEW INCIDENT
                    actions = get_recommended_actions(z_name, raw_severity, bn_reasons, risk_score)
                    incident = {
                        "id": f"ALT-{z_id}-{int(now)}",
                        "zone_id": z_id,
                        "zone_name": z_name,
                        "camera_name": self.camera_name,
                        "severity": raw_severity,
                        "status": "ACTIVE",
                        "current_count": count,
                        "peak_count": count,
                        "reasons": bn_reasons,
                        "start_ts": now,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "duration_s": 0.0,
                        "recommended_actions": actions,
                        "action_recommended": format_action_summary(actions)
                    }
                    self.active_incidents[z_id] = incident
                    self._record_alert_history(incident)
                    self._trigger_notifications(incident, now, is_escalation=True)
                    self._trigger_sms_notifications(
                        zone_id=z_id,
                        zone_name=z_name,
                        level=raw_severity,
                        score=int(risk_score),
                        reasons=bn_reasons,
                        kind="ESCALATION",
                        now=now,
                        recommended_actions=actions
                    )
                    current_active_alerts.append(incident)

        return current_active_alerts

    def acknowledge_incident(self, incident_id: str, operator: str, note: str, now: float) -> Tuple[bool, int, str, Optional[Dict[str, Any]]]:
        """
        Acknowledges an active incident with operator attribution and optional Firestore sync.
        """
        target_incident = None
        for inc in self.active_incidents.values():
            if inc.get("id") == incident_id:
                target_incident = inc
                break

        if not target_incident:
            return False, 404, f"Incident '{incident_id}' not found.", None

        if target_incident.get("status") == "RESOLVED":
            return False, 409, f"Incident '{incident_id}' is already resolved.", None

        iso_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        target_incident["status"] = "ACKNOWLEDGED"
        target_incident["ack_at"] = iso_time
        target_incident["ack_by"] = operator
        target_incident["note"] = note

        if self.db is not None:
            try:
                self.db.collection("alerts").document(incident_id).set({
                    "status": "ACKNOWLEDGED",
                    "ack_at": iso_time,
                    "ack_by": operator,
                    "note": note
                }, merge=True)
            except Exception as e:
                logger.error(f"Firestore ACK write error: {e}")

        return True, 200, "Incident acknowledged successfully.", target_incident

    def resolve_incident(self, incident_id: str, note: str, operator: Optional[str], now: float) -> Tuple[bool, int, str, Optional[Dict[str, Any]]]:
        """
        Manually resolves an active incident.
        """
        target_zone_id = None
        target_incident = None
        for zid, inc in list(self.active_incidents.items()):
            if inc.get("id") == incident_id:
                target_incident = inc
                target_zone_id = zid
                break

        if not target_incident:
            return False, 404, f"Incident '{incident_id}' not found.", None

        if target_incident.get("status") == "RESOLVED":
            return False, 409, f"Incident '{incident_id}' is already resolved.", None

        iso_time = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        target_incident["status"] = "RESOLVED"
        target_incident["resolved_at"] = iso_time
        target_incident["resolved_by"] = operator if operator else target_incident.get("ack_by", "Operator")
        if note:
            target_incident["note"] = note

        self._record_alert_history(target_incident)
        if target_zone_id:
            self.active_incidents.pop(target_zone_id, None)
            self.last_notify_level.pop(target_zone_id, None)

            if SMS_SEND_RESOLVED and self._severity_level(self.last_sms_level.get(target_zone_id, "NORMAL")) >= self._severity_level(SMS_MIN_LEVEL):
                self._trigger_sms_notifications(
                    zone_id=target_zone_id,
                    zone_name=target_incident.get("zone_name", target_zone_id),
                    level="NORMAL",
                    score=0,
                    reasons=["Manually resolved by operator"],
                    kind="RESOLVED",
                    now=now,
                    recommended_actions=[]
                )
            self.last_sms_level.pop(target_zone_id, None)
            self.last_sms_time.pop(target_zone_id, None)

        if self.db is not None:
            try:
                self.db.collection("alerts").document(incident_id).set({
                    "status": "RESOLVED",
                    "resolved_at": iso_time,
                    "resolved_by": target_incident["resolved_by"],
                    "note": target_incident.get("note", "")
                }, merge=True)
            except Exception as e:
                logger.error(f"Firestore RESOLVE write error: {e}")

        return True, 200, "Incident resolved successfully.", target_incident

    def _trigger_sms_notifications(
        self,
        zone_id: str,
        zone_name: str,
        level: str,
        score: int,
        reasons: List[str],
        kind: str,
        now: float,
        recommended_actions: Optional[List[str]] = None
    ):
        """
        Dispatches Twilio SMS/WhatsApp alert with cooldown and level filtering.
        - Escalations always dispatch immediately.
        - Same-level repeats respect SMS_COOLDOWN_SEC.
        - RESOLVED alerts dispatch if SMS_SEND_RESOLVED is True.
        """
        if not TWILIO_ENABLED:
            return

        min_rank = self._severity_level(SMS_MIN_LEVEL)
        current_rank = self._severity_level(level)

        if kind != "RESOLVED" and current_rank < min_rank:
            return

        last_t = self.last_sms_time.get(zone_id, 0.0)

        if kind == "REPEAT":
            if (now - last_t) < SMS_COOLDOWN_SEC:
                return

        twilio_notifier.demo_mode = self.demo_mode
        twilio_notifier.send_alert(
            zone_id=zone_id,
            zone_name=zone_name,
            level=level,
            score=int(score),
            reasons=reasons,
            kind=kind,
            recommended_actions=recommended_actions
        )

        self.last_sms_time[zone_id] = now
        self.last_sms_level[zone_id] = level

    def _trigger_notifications(self, incident: Dict[str, Any], now: float, is_escalation: bool = False):
        """
        Enqueues notification payload into background worker queue for ntfy.
        Escalations (e.g. HIGH -> CRITICAL) dispatch immediately.
        Repeat notifications at the same severity level are throttled by ALERT_COOLDOWN_SEC.
        """
        z_id = incident["zone_id"]
        sev = incident["severity"]
        last_t = self.last_notify_time.get(z_id, 0.0)
        last_sev = self.last_notify_level.get(z_id)

        # Cooldown check: only throttle if same severity level and within cooldown window
        if not is_escalation and (last_sev == sev) and (now - last_t < ALERT_COOLDOWN_SEC):
            return

        self.last_notify_time[z_id] = now
        self.last_notify_level[z_id] = sev

        # Enqueue payload into background worker thread
        try:
            self.notify_queue.put_nowait(dict(incident))
        except queue.Full:
            self.dropped_notifications_count += 1
            logger.warning(
                f"Notification queue overflow. Dropped notification for {incident.get('zone_name')} "
                f"(Total dropped: {self.dropped_notifications_count})"
            )

    def _record_alert_history(self, incident: Dict[str, Any]):
        """Records alert snapshot to in-memory list and Firestore."""
        self.alerts_history.insert(0, dict(incident))
        if len(self.alerts_history) > 50:
            self.alerts_history = self.alerts_history[:50]

        # Firestore write (non-blocking)
        if self.db is not None:
            try:
                self.db.collection("alerts").add({
                    "incident_id": incident["id"],
                    "zone_id": incident["zone_id"],
                    "severity": incident["severity"],
                    "count": incident["current_count"],
                    "reasons": incident.get("reasons", []),
                    "timestamp": incident["created_at"]
                })
            except Exception as e:
                logger.error(f"Firestore alert write failed: {e}")

    def _send_ntfy_sync(self, incident: Dict[str, Any]) -> bool:
        """Dispatches ntfy notification with 1 retry."""
        if not (ENABLE_MOBILE_ALERT and NTFY_TOPIC):
            return True
        z_name = incident.get("zone_name", incident.get("zone_id", "Zone"))
        severity = incident.get("severity", "ALERT")
        count = incident.get("current_count", 0)
        action = incident.get("action_recommended", "")
        demo_prefix = "[DEMO] " if self.demo_mode else ""
        message = f"{demo_prefix}[{severity}] {z_name}: {count} people detected. Action: {action}"
        title = f"{demo_prefix}CrowdSense Alert - {severity}"

        for attempt in range(2):
            try:
                requests.post(
                    f"https://ntfy.sh/{NTFY_TOPIC}",
                    data=message.encode("utf-8"),
                    headers={
                        "Title": title,
                        "Priority": "urgent" if severity == "CRITICAL" else "high",
                        "Tags": "warning,rotating_light"
                    },
                    timeout=4.0
                )
                self.ntfy_status = "OK"
                return True
            except Exception as e:
                logger.error(f"ntfy attempt {attempt+1} failed: {e}")
                time.sleep(0.5)
        self.ntfy_status = "FAILED"
        return False

    def _notification_worker(self):
        """Dedicated background worker handling ntfy push with timeouts and retries."""
        while True:
            try:
                incident = self.notify_queue.get()
                if incident is None:
                    break
                self._send_ntfy_sync(incident)
            except Exception as e:
                logger.error(f"Error in notification worker thread: {e}")
            finally:
                time.sleep(0.01)

    def get_system_notifications_status(self) -> Dict[str, Any]:
        """Returns current status of notification channels, Twilio telemetry, and queue drop count."""
        twilio_diag = twilio_notifier.get_diagnostics()
        return {
            "database": self.db_status,
            "twilio": twilio_diag["status"],
            "sms": twilio_diag["status"],
            "ntfy": self.ntfy_status,
            "dropped_notifications": self.dropped_notifications_count + twilio_diag["dropped"],
            "twilio_details": twilio_diag
        }

