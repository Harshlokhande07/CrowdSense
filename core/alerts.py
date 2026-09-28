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
    TWILIO_SID,
    TWILIO_TOKEN,
    TWILIO_FROM,
    TWILIO_TO,
    ALERT_PHONE,
    FIREBASE_KEY_PATH,
    ALERT_COOLDOWN_SEC
)

logger = logging.getLogger("CrowdSense.Alerts")

class AlertManager:
    def __init__(self):
        # Service status indicators
        self.db_status = "NOT_CONFIGURED"
        self.twilio_status = "NOT_CONFIGURED"
        self.ntfy_status = "READY" if ENABLE_MOBILE_ALERT else "DISABLED"

        self.db = None
        self.twilio_client = None

        # Zone Active Incidents: zone_id -> Incident dict
        self.active_incidents: Dict[str, Dict[str, Any]] = {}
        # Recent Alerts History (in-memory deque)
        self.alerts_history: List[Dict[str, Any]] = []

        # Re-notification cooldown tracker: zone_id -> last_notification_timestamp
        self.last_notify_time: Dict[str, float] = {}

        # Background notification queue & worker thread
        self.notify_queue = queue.Queue(maxsize=100)
        self.worker_thread = threading.Thread(target=self._notification_worker, daemon=True)
        self.worker_thread.start()

        # Lazy service init
        self._init_services()

    def reset(self):
        """Clears active incidents, history, and cooldown timestamps on source switch."""
        self.active_incidents.clear()
        self.alerts_history.clear()
        self.last_notify_time.clear()

    def _init_services(self):
        """Attempts to lazy-initialize Firestore and Twilio without crashing."""
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

        # 2. Twilio Lazy Init
        if TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM and ALERT_PHONE:
            try:
                from twilio.rest import Client
                self.twilio_client = Client(TWILIO_SID, TWILIO_TOKEN)
                self.twilio_status = "READY"
                logger.info("Twilio SMS client initialized successfully.")
            except Exception as e:
                logger.error(f"Twilio client initialization failed: {e}")
                self.twilio_status = "DISCONNECTED"
                self.twilio_client = None
        else:
            self.twilio_status = "NOT_CONFIGURED"

    def process_zone_states(
        self,
        zones: List[Dict[str, Any]],
        bottlenecks: List[Dict[str, Any]],
        predictions: List[Dict[str, Any]],
        now: float
    ) -> List[Dict[str, Any]]:
        """
        Runs the per-zone incident state machine.
        Escalates or de-escalates alerts, updates existing incidents, and queues notifications.
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
            risk_score = bn_info.get("score", 0)
            bn_reasons = bn_info.get("reasons", [])

            pred_info = pred_map.get(z_id, {})

            # Map inputs to Incident Severity: NORMAL | WARNING | HIGH | CONGESTION | CRITICAL
            severity = "NORMAL"
            if risk_score >= 70 or level == "CRITICAL":
                severity = "CRITICAL"
            elif risk_score >= 45 or bn_info.get("is_bottleneck", False):
                severity = "CONGESTION"
            elif level == "HIGH" or risk_score >= 30:
                severity = "HIGH"
            elif level == "ELEVATED":
                severity = "WARNING"

            # Check if an incident already exists for this zone
            if z_id in self.active_incidents:
                incident = self.active_incidents[z_id]

                if severity == "NORMAL":
                    # Incident resolved
                    incident["status"] = "RESOLVED"
                    incident["resolved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                    self._record_alert_history(incident)
                    self.active_incidents.pop(z_id)
                    logger.info(f"Incident resolved for {z_name}")
                else:
                    # Incident persisting: UPDATE peak count, duration, reasons
                    prev_severity = incident["severity"]
                    incident["peak_count"] = max(incident["peak_count"], count)
                    incident["current_count"] = count
                    incident["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
                    incident["duration_s"] = round(now - incident["start_ts"], 1)
                    incident["reasons"] = bn_reasons

                    # Escalation check: if severity rises, reset status to ACTIVE and trigger new notification
                    if self._severity_level(severity) > self._severity_level(prev_severity):
                        incident["severity"] = severity
                        incident["status"] = "ACTIVE"
                        incident["action_recommended"] = self._recommend_action(z_name, severity)
                        self._trigger_notifications(incident, now)

                    current_active_alerts.append(incident)

            else:
                if severity != "NORMAL":
                    # CREATE NEW INCIDENT
                    incident = {
                        "id": f"ALT-{z_id}-{int(now)}",
                        "zone_id": z_id,
                        "zone_name": z_name,
                        "severity": severity,
                        "status": "ACTIVE",
                        "current_count": count,
                        "peak_count": count,
                        "reasons": bn_reasons,
                        "start_ts": now,
                        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "last_seen": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                        "duration_s": 0.0,
                        "action_recommended": self._recommend_action(z_name, severity)
                    }
                    self.active_incidents[z_id] = incident
                    self._record_alert_history(incident)
                    self._trigger_notifications(incident, now)
                    current_active_alerts.append(incident)

        return current_active_alerts

    def acknowledge_incident(self, incident_id: str, operator: str, note: str, now: float) -> Tuple[bool, int, str, Optional[Dict[str, Any]]]:
        """
        Acknowledges an active incident.
        PROTOTYPE LIMITS: No authentication in this prototype; operator name is free text.
        Returns: (success, status_code, message, updated_incident)
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
            logger.info(f"Persisting incident ACK to Firestore for {incident_id} by {operator}")
            try:
                self.db.collection("alerts").document(incident_id).set({
                    "status": "ACKNOWLEDGED",
                    "ack_at": iso_time,
                    "ack_by": operator,
                    "note": note
                }, merge=True)
            except Exception as e:
                logger.error(f"Firestore ACK write error: {e}")
        else:
            logger.info(f"Persisting incident ACK to in-memory state for {incident_id} by {operator}")

        return True, 200, "Incident acknowledged successfully.", target_incident

    def resolve_incident(self, incident_id: str, note: str, operator: Optional[str], now: float) -> Tuple[bool, int, str, Optional[Dict[str, Any]]]:
        """
        Manually resolves an active incident.
        PROTOTYPE LIMITS: No authentication in this prototype; operator name is free text.
        Returns: (success, status_code, message, updated_incident)
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

        if self.db is not None:
            logger.info(f"Persisting incident RESOLVE to Firestore for {incident_id}")
            try:
                self.db.collection("alerts").document(incident_id).set({
                    "status": "RESOLVED",
                    "resolved_at": iso_time,
                    "resolved_by": target_incident["resolved_by"],
                    "note": target_incident.get("note", "")
                }, merge=True)
            except Exception as e:
                logger.error(f"Firestore RESOLVE write error: {e}")
        else:
            logger.info(f"Persisting incident RESOLVE to in-memory state for {incident_id}")

        return True, 200, "Incident resolved successfully.", target_incident

    @staticmethod
    def _severity_level(severity: str) -> int:
        levels = {"NORMAL": 0, "WARNING": 1, "HIGH": 2, "CONGESTION": 3, "CRITICAL": 4}
        return levels.get(severity, 0)

    @staticmethod
    def _recommend_action(zone_name: str, severity: str) -> str:
        if severity == "CRITICAL":
            return f"Pause entry at {zone_name}. Open alternate emergency exit lane immediately."
        elif severity == "CONGESTION":
            return f"Deploy field staff to {zone_name} to direct crowd flow."
        elif severity == "HIGH":
            return f"Monitor camera feed for {zone_name}. Prepare entry throttle."
        else:
            return f"Routine safety monitoring in {zone_name}."

    def _trigger_notifications(self, incident: Dict[str, Any], now: float):
        """Enqueues notification tasks with cooldown checks."""
        z_id = incident["zone_id"]
        last_t = self.last_notify_time.get(z_id, 0.0)

        if now - last_t < ALERT_COOLDOWN_SEC:
            return  # Throttle re-notifications

        self.last_notify_time[z_id] = now

        # Put notification payload into background queue
        try:
            self.notify_queue.put_nowait(dict(incident))
        except queue.Full:
            logger.warning("Notification queue full. Skipping alert payload.")

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

    def _notification_worker(self):
        """Background thread worker handling HTTP requests for ntfy and SMS via Twilio."""
        while True:
            try:
                incident = self.notify_queue.get()
                if incident is None:
                    break

                z_name = incident["zone_name"]
                severity = incident["severity"]
                count = incident["current_count"]
                action = incident["action_recommended"]

                message = f"[{severity}] {z_name}: {count} people detected. {action}"

                # 1. Send via ntfy.sh
                if ENABLE_MOBILE_ALERT and NTFY_TOPIC:
                    try:
                        requests.post(
                            f"https://ntfy.sh/{NTFY_TOPIC}",
                            data=message.encode("utf-8"),
                            headers={
                                "Title": f"CrowdSense Alert - {severity}",
                                "Priority": "urgent" if severity == "CRITICAL" else "high",
                                "Tags": "warning,rotating_light"
                            },
                            timeout=5
                        )
                        self.ntfy_status = "OK"
                    except Exception as e:
                        logger.error(f"ntfy notification failed: {e}")
                        self.ntfy_status = "FAILED"

                # 2. Send via Twilio SMS (ONLY for CRITICAL severity)
                to_phone = TWILIO_TO or ALERT_PHONE
                if severity == "CRITICAL" and self.twilio_client is not None and to_phone:
                    try:
                        self.twilio_client.messages.create(
                            to=to_phone,
                            from_=TWILIO_FROM,
                            body=f"CrowdSense CRITICAL: {z_name} congestion alert! {action}"
                        )
                        self.twilio_status = "OK"
                        # Mask phone number for security in logs
                        masked_phone = to_phone[:3] + "****" + to_phone[-4:] if len(to_phone) >= 7 else "***"
                        logger.info(f"Twilio SMS dispatched to {masked_phone}")
                    except Exception as e:
                        logger.error(f"Twilio SMS delivery failed: {e}")
                        self.twilio_status = "FAILED"

            except Exception as e:
                logger.error(f"Error in notification worker thread: {e}")
            finally:
                time.sleep(0.1)

    def get_system_notifications_status(self) -> Dict[str, str]:
        """Returns the current status of all notification channels."""
        return {
            "database": self.db_status,
            "twilio": self.twilio_status,
            "ntfy": self.ntfy_status
        }
