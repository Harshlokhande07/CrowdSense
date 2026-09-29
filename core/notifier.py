"""
CrowdSense Twilio SMS & WhatsApp Notifier Module.
Handles asynchronous, non-blocking alert dispatch via Twilio with bounded queues,
exponential backoff retries, phone masking, and channel support (SMS / WhatsApp).
"""

import time
import queue
import logging
import threading
from typing import List, Dict, Any, Optional
from collections import deque

from core.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_API_KEY_SID,
    TWILIO_API_KEY_SECRET,
    TWILIO_AUTH_TOKEN,
    TWILIO_MESSAGING_SERVICE_SID,
    TWILIO_FROM_NUMBER,
    TWILIO_SENDER,
    ALERT_PHONE_NUMBERS,
    ZONE_RECIPIENTS,
    SMS_MIN_LEVEL,
    SMS_COOLDOWN_SEC,
    SMS_SEND_RESOLVED,
    TWILIO_CHANNEL,
    TWILIO_ENABLED,
    mask_phone_number,
    is_valid_e164
)

logger = logging.getLogger("CrowdSense.Notifier")

class TwilioNotifier:
    """
    Asynchronous notification manager for Twilio SMS & WhatsApp.
    Never blocks video inference / event processing threads.
    """
    def __init__(self, max_queue_size: int = 50, auto_start: bool = True):
        self.max_queue_size = max_queue_size
        self.queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()

        # Telemetry & Diagnostics
        self.total_sent: int = 0
        self.total_failed: int = 0
        self.total_dropped: int = 0
        self.recent_logs: deque = deque(maxlen=20)
        self.lock = threading.Lock()

        # Lazy Client
        self._client = None
        self._client_init_attempted = False
        self._client_init_error: Optional[str] = None

        # Start Background Worker
        self._worker_thread = None
        if auto_start:
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="CrowdSense-TwilioWorker")
            self._worker_thread.start()

    def _get_client(self):
        """Lazy-creates twilio.rest.Client with 10s connection timeout."""
        if self._client is not None:
            return self._client
        if not TWILIO_ENABLED:
            return None

        try:
            from twilio.rest import Client
            from twilio.http.http_client import TwilioHttpClient

            http_client = TwilioHttpClient(timeout=10.0)

            if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET:
                self._client = Client(
                    TWILIO_API_KEY_SID,
                    TWILIO_API_KEY_SECRET,
                    TWILIO_ACCOUNT_SID,
                    http_client=http_client
                )
                logger.info("Initialized Twilio Client using API Key SID authentication.")
            elif TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
                self._client = Client(
                    TWILIO_ACCOUNT_SID,
                    TWILIO_AUTH_TOKEN,
                    http_client=http_client
                )
                logger.info("Initialized Twilio Client using Account SID + Auth Token fallback.")
            return self._client
        except Exception as e:
            self._client_init_error = str(e)
            logger.error(f"Failed to initialize Twilio client: {e}")
            return None

    def format_message(
        self,
        zone_name: str,
        level: str,
        score: int,
        reasons: List[str],
        kind: str,
        recommended_actions: Optional[List[str]] = None
    ) -> str:
        """
        Formats a compact, high-priority message (aiming for <= 160 chars for standard single SMS segment).
        Format: CROWDSENSE {LEVEL}: {zone_name} | Risk {score}/100 | {top 2 reasons} | {HH:MM:SS}
        """
        now_str = time.strftime("%H:%M:%S", time.localtime())
        reasons_str = ", ".join(reasons[:2]) if reasons else "High Congestion"

        if kind == "RESOLVED":
            base_msg = f"CROWDSENSE RESOLVED: {zone_name} is back to NORMAL | {now_str}"
            return base_msg

        prefix = "CROWDSENSE " + ("ALERT" if level == "WARNING" else level)
        base_msg = f"{prefix}: {zone_name} | Risk {score}/100 | {reasons_str} | {now_str}"

        # Append top recommended action if it fits comfortably within standard SMS segment
        if recommended_actions and len(recommended_actions) > 0:
            first_action = recommended_actions[0]
            candidate = f"{base_msg} | Action: {first_action}"
            if len(candidate) <= 160:
                return candidate

        return base_msg

    def get_recipients_for_zone(self, zone_id: str) -> List[str]:
        """Resolves target phone numbers for a zone, falling back to global ALERT_PHONE_NUMBERS."""
        if zone_id and zone_id in ZONE_RECIPIENTS and ZONE_RECIPIENTS[zone_id]:
            return ZONE_RECIPIENTS[zone_id]
        return ALERT_PHONE_NUMBERS

    def send_alert(
        self,
        zone_id: str,
        zone_name: str,
        level: str,
        score: int,
        reasons: List[str],
        kind: str,
        recommended_actions: Optional[List[str]] = None
    ) -> bool:
        """
        Enqueues an alert for background delivery without blocking the inference loop.
        Drops oldest non-CRITICAL message if the bounded queue is full.
        """
        if not TWILIO_ENABLED:
            return False

        message_body = self.format_message(zone_name, level, score, reasons, kind, recommended_actions)
        recipients = self.get_recipients_for_zone(zone_id)

        if not recipients:
            logger.warning(f"No valid recipients configured for zone '{zone_id}'.")
            return False

        payload = {
            "zone_id": zone_id,
            "zone_name": zone_name,
            "level": level,
            "score": score,
            "kind": kind,
            "message": message_body,
            "recipients": recipients,
            "created_at": time.time(),
            "is_critical": (level == "CRITICAL")
        }

        # Handle Queue Overflow with Non-Critical Drop Logic
        try:
            self.queue.put_nowait(payload)
            return True
        except queue.Full:
            # Queue is full; drop oldest non-critical item
            dropped_item = None
            with self.lock:
                temp_items = []
                while not self.queue.empty():
                    try:
                        temp_items.append(self.queue.get_nowait())
                    except queue.Empty:
                        break

                # Find first non-critical item to drop
                drop_idx = -1
                for idx, item in enumerate(temp_items):
                    if not item.get("is_critical", False):
                        drop_idx = idx
                        break

                if drop_idx >= 0:
                    dropped_item = temp_items.pop(drop_idx)
                elif temp_items:
                    # All are critical; drop oldest item to maintain responsiveness
                    dropped_item = temp_items.pop(0)

                # Re-queue remaining items and the new payload
                for item in temp_items:
                    self.queue.put_nowait(item)
                try:
                    self.queue.put_nowait(payload)
                except queue.Full:
                    pass

                self.total_dropped += 1
                if dropped_item:
                    logger.warning(f"Twilio notify queue overflow. Dropped '{dropped_item.get('level')}' alert for '{dropped_item.get('zone_name')}'. Total dropped: {self.total_dropped}")
                    self._record_log(dropped_item, status="DROPPED", detail="Queue capacity exceeded")

            return True

    def _send_single_sms(self, client, to_number: str, message_body: str) -> bool:
        """Sends one SMS / WhatsApp with up to 3 retries, exponential backoff, and non-retry on 4xx."""
        # Format sender and receiver according to channel
        if TWILIO_CHANNEL == "whatsapp":
            from_target = f"whatsapp:{TWILIO_SENDER}" if not TWILIO_SENDER.startswith("whatsapp:") else TWILIO_SENDER
            to_target = f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number
        else:
            from_target = TWILIO_SENDER
            to_target = to_number

        is_messaging_service = TWILIO_MESSAGING_SERVICE_SID and TWILIO_SENDER.startswith("MG")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                kwargs = {"to": to_target, "body": message_body}
                if is_messaging_service:
                    kwargs["messaging_service_sid"] = TWILIO_MESSAGING_SERVICE_SID
                else:
                    kwargs["from_"] = from_target

                client.messages.create(**kwargs)
                return True
            except Exception as e:
                # Check for TwilioRestException 4xx client errors (do not retry)
                status_code = getattr(e, "status", None)
                code = getattr(e, "code", None)
                if status_code is not None and 400 <= status_code < 500:
                    logger.error(f"Twilio client error (HTTP {status_code}, Code {code}): {e}. Will not retry for {mask_phone_number(to_number)}.")
                    return False

                if attempt < max_retries:
                    backoff = 0.5 * (2 ** (attempt - 1))
                    logger.warning(f"Twilio send attempt {attempt} failed: {e}. Retrying in {backoff}s...")
                    time.sleep(backoff)
                else:
                    logger.error(f"Twilio send failed after {max_retries} attempts to {mask_phone_number(to_number)}: {e}")
                    return False
        return False

    def _worker_loop(self):
        """Background worker consuming alert payloads."""
        while not self._stop_event.is_set():
            try:
                payload = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue

            if payload is None:
                break

            client = self._get_client()
            if client is None:
                with self.lock:
                    self.total_failed += len(payload.get("recipients", []))
                    self._record_log(payload, status="FAILED", detail="Twilio client not configured or auth error")
                continue

            recipients = payload.get("recipients", [])
            message_body = payload.get("message", "")
            success_count = 0

            for recipient in recipients:
                ok = self._send_single_sms(client, recipient, message_body)
                if ok:
                    success_count += 1
                else:
                    logger.error(f"Failed to deliver alert to recipient {mask_phone_number(recipient)}")

            with self.lock:
                if success_count > 0:
                    self.total_sent += success_count
                    self._record_log(payload, status="SENT", detail=f"Delivered to {success_count}/{len(recipients)} recipients")
                else:
                    self.total_failed += len(recipients)
                    self._record_log(payload, status="FAILED", detail="All recipient delivery attempts failed")

    def _record_log(self, payload: Dict[str, Any], status: str, detail: str = ""):
        """Stores structured log entry for dashboard /api/state inspection."""
        masked_recipients = [mask_phone_number(r) for r in payload.get("recipients", [])]
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "zone_id": payload.get("zone_id"),
            "zone_name": payload.get("zone_name"),
            "level": payload.get("level"),
            "kind": payload.get("kind"),
            "status": status,
            "recipients": masked_recipients,
            "detail": detail
        }
        self.recent_logs.append(entry)

    def get_status(self) -> str:
        """Returns health status string: 'ENABLED', 'DISABLED', or 'DEGRADED'."""
        if not TWILIO_ENABLED:
            return "DISABLED"
        if self._client_init_error or (self.total_failed > 0 and self.total_sent == 0):
            return "DEGRADED"
        return "ENABLED"

    def get_diagnostics(self) -> Dict[str, Any]:
        """Provides full notification diagnostics for REST and WebSocket payloads."""
        with self.lock:
            return {
                "status": self.get_status(),
                "channel": TWILIO_CHANNEL,
                "sent": self.total_sent,
                "failed": self.total_failed,
                "dropped": self.total_dropped,
                "queue_size": self.queue.qsize(),
                "recent_logs": list(self.recent_logs)
            }

    def shutdown(self, timeout: float = 1.0):
        """Stops background worker thread gracefully."""
        self._stop_event.set()
        try:
            self.queue.put_nowait(None)
        except Exception:
            pass
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout)
        logger.info("Twilio notifier worker shut down cleanly.")

# Global singleton instance
twilio_notifier = TwilioNotifier()
