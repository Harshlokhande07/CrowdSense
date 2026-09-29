"""
Comprehensive test suite for Twilio SMS & WhatsApp integration.
Mocks twilio.rest.Client to ensure zero real network calls.
"""

import time
import pytest
from unittest.mock import MagicMock, patch

from core.config import is_valid_e164, mask_phone_number
from core.notifier import TwilioNotifier
from core.alerts import AlertManager


def test_phone_masking_and_e164_validation():
    """Validates E.164 format check and phone number masking."""
    # E.164 Validation
    assert is_valid_e164("+14155552671") is True
    assert is_valid_e164("+919876543210") is True
    assert is_valid_e164("+442071838750") is True
    assert is_valid_e164("14155552671") is False  # Missing leading +
    assert is_valid_e164("+1234") is False  # Too short
    assert is_valid_e164("invalid_phone") is False
    assert is_valid_e164("") is False

    # Phone Masking
    assert mask_phone_number("+919876543210") == "+91******3210"
    assert mask_phone_number("+14155552671") == "+14******2671"
    assert mask_phone_number("123") == "***"


def test_unconfigured_twilio_safe_noop():
    """Unconfigured Twilio must safely no-op without raising any exceptions."""
    with patch("core.notifier.TWILIO_ENABLED", False):
        notifier = TwilioNotifier(max_queue_size=10)
        notifier.shutdown()

        res = notifier.send_alert(
            zone_id="ZONE_A",
            zone_name="Main Gate",
            level="CRITICAL",
            score=90,
            reasons=["Overcrowded"],
            kind="ESCALATION"
        )
        assert res is False
        assert notifier.get_status() == "DISABLED"


def test_queue_overflow_keeps_critical_messages():
    """Queue overflow must drop oldest non-CRITICAL message while retaining CRITICAL alerts."""
    with patch("core.notifier.TWILIO_ENABLED", True), \
         patch("core.notifier.ALERT_PHONE_NUMBERS", ["+14155552671"]):

        notifier = TwilioNotifier(max_queue_size=3, auto_start=False)

        # Enqueue 1 CRITICAL, then 2 HIGH
        notifier.send_alert("Z1", "Zone 1", "CRITICAL", 85, ["Dense"], "ESCALATION")
        notifier.send_alert("Z2", "Zone 2", "HIGH", 45, ["Slow"], "REPEAT")
        notifier.send_alert("Z3", "Zone 3", "HIGH", 40, ["Slow"], "REPEAT")
        assert notifier.queue.qsize() == 3

        # Add 4th item (CRITICAL). Oldest non-critical (Z2) must be dropped!
        notifier.send_alert("Z4", "Zone 4", "CRITICAL", 95, ["Surge"], "ESCALATION")
        assert notifier.queue.qsize() == 3
        assert notifier.total_dropped >= 1

        items = []
        while not notifier.queue.empty():
            items.append(notifier.queue.get_nowait())

        zones_in_queue = [it["zone_id"] for it in items]
        assert "Z1" in zones_in_queue
        assert "Z4" in zones_in_queue
        assert "Z2" not in zones_in_queue  # Z2 dropped

        notifier.shutdown()


def test_twilio_retry_on_server_error_and_no_retry_on_4xx():
    """Retries with exponential backoff on connection/5xx errors; does NOT retry 4xx client errors."""
    with patch("core.notifier.TWILIO_ENABLED", True), \
         patch("core.notifier.ALERT_PHONE_NUMBERS", ["+14155552671"]), \
         patch("core.notifier.TWILIO_CHANNEL", "sms"), \
         patch("core.notifier.TWILIO_SENDER", "+15005550006"):

        notifier = TwilioNotifier(max_queue_size=10)
        notifier.shutdown()

        mock_client = MagicMock()

        # Case 1: Twilio 400 Bad Request / 21211 Invalid Number -> NO retry
        class MockTwilioClientError(Exception):
            status = 400
            code = 21211

        mock_client.messages.create.side_effect = MockTwilioClientError("Invalid 'To' Phone Number")
        ok_4xx = notifier._send_single_sms(mock_client, "+14155552671", "Test Alert")
        assert ok_4xx is False
        assert mock_client.messages.create.call_count == 1  # Exactly 1 call, no retries

        # Case 2: Network / 5xx Server Error -> Up to 3 retries
        mock_client.reset_mock()
        mock_client.messages.create.side_effect = Exception("500 Internal Server Error / Timeout")

        with patch("time.sleep", return_value=None):
            ok_5xx = notifier._send_single_sms(mock_client, "+14155552671", "Test Alert")
            assert ok_5xx is False
            assert mock_client.messages.create.call_count == 3  # Tried 3 times


def test_alerts_sms_cooldown_and_escalation():
    """AlertManager SMS integration: escalation sends immediately; same-level respects cooldown; low level ignored."""
    manager = AlertManager()
    zone = [{"id": "ZONE_A", "name": "Gate 3", "count": 6, "level": "HIGH"}]
    bn_high = [{"zone_id": "ZONE_A", "score": 35, "reasons": ["High density"], "is_bottleneck": False}]
    preds = [{"zone_id": "ZONE_A", "predicted_count": 8, "trend": "RISING"}]

    sent_alerts = []

    def mock_send_alert(zone_id, zone_name, level, score, reasons, kind, recommended_actions=None, **kwargs):
        sent_alerts.append({
            "zone_id": zone_id,
            "zone_name": zone_name,
            "level": level,
            "score": score,
            "kind": kind
        })
        return True

    with patch("core.alerts.TWILIO_ENABLED", True), \
         patch("core.alerts.SMS_MIN_LEVEL", "HIGH"), \
         patch("core.alerts.SMS_COOLDOWN_SEC", 30.0), \
         patch("core.alerts.twilio_notifier.send_alert", side_effect=mock_send_alert):

        # 1. Below SMS_MIN_LEVEL (WARNING) does not send SMS
        zone_warn = [{"id": "ZONE_A", "name": "Gate 3", "count": 2, "level": "WARNING"}]
        bn_warn = [{"zone_id": "ZONE_A", "score": 20, "reasons": ["Elevated"], "is_bottleneck": False}]
        manager.process_zone_states(zone_warn, bn_warn, preds, now=100.0)
        assert len(sent_alerts) == 0

        # 2. Enter HIGH at t=105.0 -> Dispatches ESCALATION
        manager.process_zone_states(zone, bn_high, preds, now=105.0)
        assert len(sent_alerts) == 1
        assert sent_alerts[-1]["level"] == "HIGH"
        assert sent_alerts[-1]["kind"] == "ESCALATION"

        # 3. Repeat at HIGH at t=110.0 (< 30s cooldown) -> Does NOT send
        manager.process_zone_states(zone, bn_high, preds, now=110.0)
        assert len(sent_alerts) == 1

        # 4. Escalation to CRITICAL at t=115.0 (still inside 30s cooldown) -> ALWAYS sends immediately!
        bn_crit = [{"zone_id": "ZONE_A", "score": 80, "reasons": ["Surge"], "is_bottleneck": True}]
        zone[0]["level"] = "CRITICAL"
        manager.process_zone_states(zone, bn_crit, preds, now=115.0)
        assert len(sent_alerts) == 2
        assert sent_alerts[-1]["level"] == "CRITICAL"
        assert sent_alerts[-1]["kind"] == "ESCALATION"

        # 5. Repeat at CRITICAL at t=150.0 (> 30s cooldown from t=115) -> Dispatches REPEAT
        manager.process_zone_states(zone, bn_crit, preds, now=150.0)
        assert len(sent_alerts) == 3
        assert sent_alerts[-1]["level"] == "CRITICAL"
        assert sent_alerts[-1]["kind"] == "REPEAT"


def test_alerts_sms_resolved_handling():
    """SMS RESOLVED is dispatched once after 3s NORMAL if SMS_SEND_RESOLVED is True; suppressed if False."""
    zone = [{"id": "ZONE_A", "name": "Gate 3", "count": 10, "level": "CRITICAL"}]
    bn_crit = [{"zone_id": "ZONE_A", "score": 85, "reasons": ["Surge"], "is_bottleneck": True}]
    preds = [{"zone_id": "ZONE_A", "predicted_count": 12, "trend": "RISING"}]

    # Case A: SMS_SEND_RESOLVED = True
    manager1 = AlertManager()
    sent_alerts1 = []

    with patch("core.alerts.TWILIO_ENABLED", True), \
         patch("core.alerts.SMS_MIN_LEVEL", "HIGH"), \
         patch("core.alerts.SMS_SEND_RESOLVED", True), \
         patch("core.alerts.twilio_notifier.send_alert", side_effect=lambda **kw: sent_alerts1.append(kw)):

        # Create CRITICAL incident
        manager1.process_zone_states(zone, bn_crit, preds, now=100.0)
        assert len(sent_alerts1) == 1
        assert sent_alerts1[-1]["kind"] == "ESCALATION"

        # Drop to NORMAL
        zone_norm = [{"id": "ZONE_A", "name": "Gate 3", "count": 1, "level": "NORMAL"}]
        bn_norm = [{"zone_id": "ZONE_A", "score": 0, "reasons": [], "is_bottleneck": False}]

        manager1.process_zone_states(zone_norm, bn_norm, preds, now=101.0)
        # At t=101 (<3s), no resolution yet
        assert len(sent_alerts1) == 1

        # At t=105 (>3s), resolution triggers RESOLVED SMS
        manager1.process_zone_states(zone_norm, bn_norm, preds, now=105.0)
        assert len(sent_alerts1) == 2
        assert sent_alerts1[-1]["kind"] == "RESOLVED"
        assert sent_alerts1[-1]["level"] == "NORMAL"

    # Case B: SMS_SEND_RESOLVED = False
    manager2 = AlertManager()
    sent_alerts2 = []

    with patch("core.alerts.TWILIO_ENABLED", True), \
         patch("core.alerts.SMS_MIN_LEVEL", "HIGH"), \
         patch("core.alerts.SMS_SEND_RESOLVED", False), \
         patch("core.alerts.twilio_notifier.send_alert", side_effect=lambda **kw: sent_alerts2.append(kw)):

        manager2.process_zone_states(zone, bn_crit, preds, now=100.0)
        assert len(sent_alerts2) == 1

        manager2.process_zone_states(zone_norm, bn_norm, preds, now=105.0)
        assert len(sent_alerts2) == 1  # No RESOLVED SMS sent


def test_demo_safety_prefix():
    """Prefix [DEMO] must be added to message when demo_mode is True."""
    notifier = TwilioNotifier(max_queue_size=5, auto_start=False)

    # Demo mode = True
    msg_demo = notifier.format_message(
        zone_name="Main Gate",
        level="HIGH",
        score=75,
        reasons=["Surge"],
        kind="ESCALATION",
        demo_mode=True
    )
    assert msg_demo.startswith("[DEMO] ")
    assert "CROWDSENSE HIGH: Main Gate" in msg_demo

    # Demo mode = False (Production)
    msg_prod = notifier.format_message(
        zone_name="Main Gate",
        level="HIGH",
        score=75,
        reasons=["Surge"],
        kind="ESCALATION",
        demo_mode=False
    )
    assert not msg_prod.startswith("[DEMO] ")
    assert msg_prod.startswith("CROWDSENSE HIGH: Main Gate")

    # Resolved in demo mode
    msg_res_demo = notifier.format_message(
        zone_name="Main Gate",
        level="NORMAL",
        score=0,
        reasons=[],
        kind="RESOLVED",
        demo_mode=True
    )
    assert msg_res_demo.startswith("[DEMO] CROWDSENSE RESOLVED:")

