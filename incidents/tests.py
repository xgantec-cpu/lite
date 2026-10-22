from datetime import timedelta
import asyncio
import hashlib
import json
import time
import uuid
from unittest.mock import patch
from urllib.parse import quote

from channels.testing import WebsocketCommunicator
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db import connection
from django.utils import timezone

from .models import AreaAlert, CaseMessage, EmergencyChatCall, EmergencyChatMessage, EmergencyChatRoom, EmergencyRequest, HospitalFacility, Incident, IncidentFavorite, IncidentNote, InHouseConversation, InHouseMessage, InstitutionProfile, LocationArea, LocationPing, MFAProfile, OperationsAccess, PublicAlertSubscription, Recording, Referral, ReferralDestination, ResponseProfile, SecurityEvent, TravelSafetyPlan
from .device_detection import detect_device
from .mfa import totp_code
from .realtime import async_broadcast_emergency_chat_update
from .websocket_auth import make_public_chat_token, make_websocket_token
from emergency_platform.asgi import application


class EmergencyRequestFlowTests(TestCase):
    def setUp(self):
        self.area, _ = LocationArea.objects.get_or_create(name="Masaka", defaults={"district": "Masaka"})

    def test_home_page_is_available(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "SEEK HELP")
        self.assertContains(response, "Quick video help")
        self.assertContains(response, "Travel / Get alerts")
        self.assertContains(response, "Alerts")
        self.assertNotContains(response, "Optional community safety alerts")
        self.assertContains(response, "Allow location")
        self.assertContains(response, "id_client_uuid")

    def test_device_detection_identifies_common_platforms(self):
        iphone = detect_device("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1")
        android = detect_device("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36")
        laptop = detect_device("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
        self.assertEqual(iphone["operating_system"], "iOS")
        self.assertEqual(android["device_type"], "Android phone")
        self.assertEqual(laptop["device_type"], "Laptop / desktop")

    def test_quick_help_page_is_available(self):
        response = self.client.get(reverse("quick_help"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tap to record video")
        self.assertContains(response, "quick-camera-switch")
        self.assertContains(response, "quick-camera-toggle")

    def test_submission_creates_request_and_incident(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": self.area.name,
            "location_description": "Near the bus park",
            "latitude": "-0.3400",
            "longitude": "31.7333",
            "location_accuracy": "20",
            "location_source": "gps",
            "client_uuid": "11111111-1111-4111-8111-111111111111",
            "emergency_type": "danger",
            "message": "I need assistance",
            "priority": "critical",
        }, HTTP_USER_AGENT="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile Safari/604.1")
        self.assertRedirects(response, reverse("submit_success"))
        emergency_request = EmergencyRequest.objects.get()
        self.assertEqual(emergency_request.area, self.area)
        self.assertEqual(emergency_request.location_source, "gps")
        self.assertEqual(emergency_request.incident.assigned_area, self.area)
        self.assertEqual(emergency_request.device_type, "iPhone")
        self.assertEqual(emergency_request.operating_system, "iOS")
        self.assertEqual(emergency_request.browser, "Safari")
        self.assertEqual(str(emergency_request.client_uuid), "11111111-1111-4111-8111-111111111111")
        self.assertTrue(emergency_request.tracking_enabled)
        self.assertTrue(emergency_request.request_id.startswith("EMG-MSKA-"))

    def test_critical_case_can_start_ping_stop_and_resume_tracking(self):
        client_uuid = "22222222-2222-4222-8222-222222222222"
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": self.area.name,
            "latitude": "-0.3400",
            "longitude": "31.7333",
            "location_accuracy": "20",
            "location_source": "gps",
            "client_uuid": client_uuid,
            "emergency_type": "danger",
            "priority": "critical",
        })
        incident = EmergencyRequest.objects.get().incident
        tracking_url = reverse("emergency_location_tracking", args=[incident.pk])
        started = self.client.post(tracking_url, {"action": "start"})
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json()["active"])
        ping_payload = {
            "action": "ping",
            "latitude": "-0.3410",
            "longitude": "31.7340",
            "location_accuracy": "12",
            "ping_id": "critical-location-ping-001",
        }
        pinged = self.client.post(tracking_url, ping_payload)
        replayed = self.client.post(tracking_url, ping_payload)
        self.assertEqual(pinged.status_code, 200)
        self.assertEqual(replayed.status_code, 200)
        self.assertEqual(LocationPing.objects.filter(request=incident.request).count(), 1)
        incident.request.refresh_from_db()
        self.assertEqual(str(incident.request.latitude), "-0.341000")
        stopped = self.client.post(tracking_url, {"action": "stop"})
        self.assertEqual(stopped.status_code, 200)
        self.assertFalse(stopped.json()["active"])
        self.assertEqual(self.client.post(tracking_url, {"action": "ping", **ping_payload}).status_code, 409)
        resumed = self.client.post(tracking_url, {"action": "resume"})
        self.assertEqual(resumed.status_code, 200)
        self.assertTrue(resumed.json()["active"])

    def test_tracking_endpoint_requires_the_sender_session(self):
        incident = Incident.objects.create(
            request=EmergencyRequest.objects.create(
                phone_number="+256700000000",
                latitude="-0.340000",
                longitude="31.733300",
                location_source="gps",
                client_uuid="33333333-3333-4333-8333-333333333333",
                priority="critical",
                tracking_enabled=True,
            ),
            assigned_area=self.area,
        )
        response = self.client.post(reverse("emergency_location_tracking", args=[incident.pk]), {"action": "start"})
        self.assertEqual(response.status_code, 403)

    def test_typed_area_prefix_is_resolved(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masa",
            "location_description": "Near the bus park",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        self.assertRedirects(response, reverse("submit_success"))
        self.assertEqual(EmergencyRequest.objects.get().area, self.area)

    def test_phone_coordinates_override_user_entered_area(self):
        LocationArea.objects.get_or_create(name="Kampala")
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Kampala",
            "latitude": "-0.3128",
            "longitude": "31.7135",
            "location_accuracy": "20",
            "location_source": "gps",
            "emergency_type": "danger",
            "priority": "high",
        })
        self.assertRedirects(response, reverse("submit_success"))
        self.assertEqual(EmergencyRequest.objects.get().area, self.area)

    def test_gps_routing_uses_real_district_boundary(self):
        kampala = LocationArea.objects.get_or_create(name="Kampala")[0]
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "latitude": "0.3476",
            "longitude": "32.5825",
            "location_accuracy": "10",
            "location_source": "gps",
            "emergency_type": "danger",
            "priority": "high",
        })
        self.assertRedirects(response, reverse("submit_success"))
        self.assertEqual(EmergencyRequest.objects.get().area, kampala)

    def test_submission_without_location_uses_non_code(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        self.assertRedirects(response, reverse("submit_success"))
        emergency_request = EmergencyRequest.objects.get()
        self.assertIsNone(emergency_request.area)
        self.assertTrue(emergency_request.request_id.startswith("EMG-NON-"))

    def test_repeated_submission_with_same_idempotency_key_creates_one_case(self):
        payload = {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "location_source": "user",
            "emergency_type": "danger",
            "priority": "high",
            "idempotency_key": "repeat-safe-request-001",
        }
        first_response = self.client.post(reverse("home"), payload)
        second_response = self.client.post(reverse("home"), payload)
        self.assertEqual(first_response.status_code, 302)
        self.assertEqual(second_response.status_code, 302)
        self.assertEqual(EmergencyRequest.objects.count(), 1)
        self.assertEqual(Incident.objects.count(), 1)

    def test_invalid_area_explains_the_submission_error(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Not a Uganda district",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Start typing and choose one of the suggested Uganda locations.")

    def test_high_precision_gps_values_are_rounded(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "latitude": "-0.3400123456789",
            "longitude": "31.7333123456789",
            "location_accuracy": "12.34567",
            "location_source": "gps",
            "emergency_type": "danger",
            "priority": "high",
        })
        self.assertRedirects(response, reverse("submit_success"))
        emergency_request = EmergencyRequest.objects.get()
        self.assertEqual(str(emergency_request.latitude), "-0.340012")
        self.assertEqual(str(emergency_request.longitude), "31.733312")

    def test_quick_video_is_stored_with_the_incident(self):
        video = SimpleUploadedFile("help.webm", b"video-bytes", content_type="video/webm")
        response = self.client.post(reverse("quick_help"), {
            "quick_mode": "1",
            "latitude": "-0.340012",
            "longitude": "31.733312",
            "location_source": "gps",
            "client_uuid": "44444444-4444-4444-8444-444444444444",
            "recording_duration": "4",
            "video": video,
            "emergency_type": "danger",
            "priority": "critical",
        })
        self.assertRedirects(response, reverse("submit_success"))
        emergency_request = EmergencyRequest.objects.get()
        self.assertEqual(emergency_request.incident.recordings.count(), 1)
        self.assertTrue(emergency_request.tracking_enabled)
        self.assertTrue(emergency_request.request_id.startswith("EMG-MSKA-"))

    def test_quick_video_ajax_submit_returns_success_url(self):
        video = SimpleUploadedFile("help.webm", b"video-bytes", content_type="video/webm")
        response = self.client.post(
            reverse("quick_help"),
            {
                "quick_mode": "1",
                "latitude": "-0.340012",
                "longitude": "31.733312",
                "location_source": "gps",
                "client_uuid": "88888888-8888-4888-8888-888888888888",
                "recording_duration": "4",
                "video": video,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["redirect_url"], reverse("submit_success"))

    def test_quick_video_reuses_the_client_token_for_repeat_case_detection(self):
        client_uuid = "77777777-7777-4777-8777-777777777777"
        base_payload = {
            "quick_mode": "1",
            "latitude": "-0.340012",
            "longitude": "31.733312",
            "location_source": "gps",
            "client_uuid": client_uuid,
            "recording_duration": "4",
            "emergency_type": "danger",
            "priority": "critical",
        }
        first_video = SimpleUploadedFile("first.webm", b"first-video", content_type="video/webm")
        self.client.post(reverse("quick_help"), {**base_payload, "idempotency_key": "quick-repeat-first", "video": first_video})
        first_incident = EmergencyRequest.objects.get().incident
        second_video = SimpleUploadedFile("second.webm", b"second-video", content_type="video/webm")
        self.client.post(reverse("quick_help"), {**base_payload, "idempotency_key": "quick-repeat-second", "video": second_video})
        second_incident = EmergencyRequest.objects.order_by("-pk").first().incident

        self.assertEqual(second_incident.similar_to_id, first_incident.pk)
        self.assertEqual(second_incident.similarity_signal, "client_uuid")

    def test_submission_creates_a_48_hour_chat_room(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        self.assertRedirects(response, reverse("submit_success"))
        emergency_request = EmergencyRequest.objects.get()
        self.assertTrue(EmergencyChatRoom.objects.filter(incident=emergency_request.incident).exists())
        success = self.client.get(reverse("submit_success"))
        self.assertContains(success, "Can you chat with us?")

    def test_matching_client_uuid_links_a_new_case_to_the_previous_case(self):
        client_uuid = "55555555-5555-4555-8555-555555555555"
        submission = {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
            "client_uuid": client_uuid,
        }
        self.client.post(reverse("home"), {**submission, "idempotency_key": "repeat-case-first"})
        first_incident = EmergencyRequest.objects.get().incident
        self.client.post(reverse("home"), {**submission, "idempotency_key": "repeat-case-second"})
        second_incident = EmergencyRequest.objects.order_by("-pk").first().incident

        self.assertEqual(second_incident.similar_to_id, first_incident.pk)
        self.assertEqual(second_incident.similarity_signal, "client_uuid")
        self.assertIsNotNone(second_incident.similarity_checked_at)

    def test_reports_without_a_device_token_are_not_matched(self):
        submission = {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        }
        self.client.post(reverse("home"), {**submission, "idempotency_key": "no-token-first"})
        self.client.post(reverse("home"), {**submission, "idempotency_key": "no-token-second"})
        second_incident = EmergencyRequest.objects.order_by("-pk").first().incident

        self.assertIsNone(second_incident.similar_to_id)
        self.assertEqual(second_incident.similarity_signal, "")

    def test_public_chat_can_be_accepted_and_used(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        chat_url = reverse("emergency_chat", args=[incident.pk])
        accepted = self.client.post(chat_url, {"action": "accept"})
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(accepted.json()["accepted"])
        sent = self.client.post(chat_url, {"action": "message", "body": "I am safe for now."})
        self.assertEqual(sent.status_code, 200)
        user_messages = [message for message in sent.json()["messages"] if message["sender_type"] == "public"]
        self.assertEqual(user_messages[0]["body"], "I am safe for now.")
        self.assertEqual(user_messages[0]["channel"], "text")

    def test_opening_public_chat_seeds_automated_greeting_and_follow_up(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        response = self.client.get(reverse("emergency_chat_page", args=[incident.pk]))
        self.assertEqual(response.status_code, 200)
        messages = EmergencyChatMessage.objects.filter(room__incident=incident, sender_type="system")
        self.assertEqual(messages.count(), 2)
        bodies = list(messages.values_list("body", flat=True))
        self.assertTrue(any(body.startswith("Hello. You are now connected") for body in bodies))
        self.assertTrue(any("confirmed GPS position" in body for body in bodies))
        self.client.get(reverse("emergency_chat_page", args=[incident.pk]))
        self.assertEqual(messages.count(), 2)

    def test_public_chat_link_survives_stale_workspace_activity(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        user = get_user_model().objects.create_user(username="stale-workspace-user", password="secret-pass")
        self.client.force_login(user)
        session = self.client.session
        session["workspace_last_activity"] = int(time.time()) - 301
        session.save()
        token = make_public_chat_token(incident)
        response = self.client.get(
            reverse("emergency_chat_page", args=[incident.pk]),
            {"access": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secure response chat")

    def test_replayed_chat_message_is_stored_once(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        chat_url = reverse("emergency_chat", args=[incident.pk])
        self.client.post(chat_url, {"action": "accept"})
        payload = {
            "action": "message",
            "body": "Please keep the line open.",
            "idempotency_key": "chat-message-replay-001",
        }
        self.client.post(chat_url, payload)
        self.client.post(chat_url, payload)
        self.assertEqual(EmergencyChatRoom.objects.get(incident=incident).messages.filter(sender_type="public").count(), 1)

    def test_authenticated_user_without_assignment_cannot_open_emergency_chat(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        outsider = get_user_model().objects.create_user(username="unassigned-responder", password="secret-pass")
        profile = ResponseProfile.objects.create(user=outsider)
        profile.active = True
        profile.save()
        self.client.force_login(outsider)
        response = self.client.get(reverse("emergency_chat_page", args=[incident.pk]))
        self.assertEqual(response.status_code, 403)

    def test_public_chat_uses_a_separate_full_screen_page(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        response = self.client.get(reverse("emergency_chat_page", args=[incident.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Back to previous step")
        self.assertContains(response, "data-chat-fullscreen=\"true\"")
        self.assertContains(response, "data-call-end")

    def test_opening_public_chat_activates_without_invitation(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        response = self.client.get(reverse("emergency_chat_page", args=[incident.pk]))
        room = EmergencyChatRoom.objects.get(incident=incident)
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(room.accepted_at)
        self.assertContains(response, "data-chat-panel")
        self.assertNotContains(response, "Accept secure chat")

    def test_success_page_repairs_missing_chat_room(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        EmergencyChatRoom.objects.filter(incident=incident).delete()
        response = self.client.get(reverse("submit_success"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(EmergencyChatRoom.objects.filter(incident=incident).exists())
        self.assertContains(response, "Open chat")

    def test_public_chat_handoff_token_survives_lost_session(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        token = make_public_chat_token(incident)
        session = self.client.session
        session.pop("request_id", None)
        session.save()
        chat_url = f"{reverse('emergency_chat_page', args=[incident.pk])}?access={quote(token, safe='')}"
        response = self.client.get(chat_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secure response chat")
        action_url = f"{reverse('emergency_chat', args=[incident.pk])}?access={quote(token, safe='')}"
        response = self.client.post(action_url, {"action": "accept"})
        self.assertEqual(response.status_code, 200)

    def test_public_chat_refresh_recovers_after_session_and_room_expire(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "emergency_type": "danger",
            "priority": "high",
            "location_source": "user",
        })
        incident = EmergencyRequest.objects.get().incident
        token = make_public_chat_token(incident)
        room = EmergencyChatRoom.objects.get(incident=incident)
        room.accepted_at = timezone.now()
        room.expires_at = timezone.now() - timedelta(minutes=1)
        room.save(update_fields=["accepted_at", "expires_at"])
        session = self.client.session
        session.pop("request_id", None)
        session.save()

        success = self.client.get(reverse("submit_success"), {"access": token})
        self.assertEqual(success.status_code, 200)
        self.assertContains(success, "Can you chat with us?")
        renewed_room = EmergencyChatRoom.objects.get(incident=incident)
        self.assertIsNone(renewed_room.accepted_at)
        self.assertGreater(renewed_room.expires_at, timezone.now())

        renewed_room.expires_at = timezone.now() - timedelta(minutes=1)
        renewed_room.save(update_fields=["expires_at"])
        session = self.client.session
        session.pop("request_id", None)
        session.save()
        chat_url = f"{reverse('emergency_chat_page', args=[incident.pk])}?access={quote(token, safe='')}"
        response = self.client.get(chat_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secure response chat")
        self.assertTrue(EmergencyChatRoom.objects.filter(incident=incident).exists())

    def test_public_voice_call_is_routed_to_the_assigned_responder(self):
        area = self.area
        responder = get_user_model().objects.create_user(username="masaka-responder", password="secret-pass")
        profile = ResponseProfile.objects.create(user=responder)
        profile.areas.add(area)
        request = EmergencyRequest.objects.create(phone_number="+256700000000", area=area, emergency_type="danger")
        incident = Incident.objects.create(request=request, assigned_area=area, assigned_admin=responder)
        room = EmergencyChatRoom.objects.create(incident=incident, expires_at=timezone.now() + timedelta(hours=48))
        public_client = Client()
        session = public_client.session
        session["request_id"] = request.request_id
        session.save()
        chat_url = reverse("emergency_chat", args=[incident.pk])
        public_client.post(chat_url, {"action": "accept"})
        response = public_client.post(chat_url, {"action": "call"})
        self.assertEqual(response.status_code, 200)
        call = EmergencyChatCall.objects.get(room=room)
        self.assertEqual(call.recipient, responder)
        responder_client = Client()
        responder_client.force_login(responder)
        accepted = responder_client.post(chat_url, {
            "action": "call_response",
            "call_id": call.pk,
            "status": "accepted",
        })
        self.assertEqual(accepted.status_code, 200)
        call.refresh_from_db()
        self.assertIsNotNone(call.started_at)
        self.assertEqual(public_client.post(chat_url, {
            "action": "call_control",
            "call_id": call.pk,
            "control": "mute",
        }).status_code, 200)
        call.refresh_from_db()
        self.assertTrue(call.caller_muted)
        self.assertEqual(public_client.post(chat_url, {
            "action": "call_control",
            "call_id": call.pk,
            "control": "hold",
        }).status_code, 200)
        call.refresh_from_db()
        self.assertTrue(call.on_hold)
        public_client.post(chat_url, {
            "action": "call_response",
            "call_id": call.pk,
            "status": "ended",
        })
        call.refresh_from_db()
        self.assertEqual(call.status, "ended")

    def test_success_page_requires_a_recent_submission(self):
        response = self.client.get(reverse("submit_success"))
        self.assertRedirects(response, reverse("home"))


class ResponderDashboardTests(TestCase):
    def setUp(self):
        self.masaka, _ = LocationArea.objects.get_or_create(name="Masaka")
        self.kampala, _ = LocationArea.objects.get_or_create(name="Kampala")
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="masaka-admin", password="secret-pass")
        self.profile = ResponseProfile.objects.create(user=self.user)
        self.profile.areas.add(self.masaka)
        self.incident = self._create_incident(self.masaka)
        self.other_incident = self._create_incident(self.kampala)

    def _create_incident(self, area):
        request = EmergencyRequest.objects.create(phone_number="+256700000000", area=area, emergency_type="security")
        return Incident.objects.create(request=request, assigned_area=area)

    def test_anonymous_dashboard_redirects_to_approved_user_login(self):
        response = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(
            response,
            f"{reverse('dashboard_login')}?next={reverse('dashboard_home')}",
        )

    def test_inactive_dashboard_user_returns_to_login_pad(self):
        self.profile.active = False
        self.profile.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(response, f"{reverse('dashboard_login')}?reason=inactive")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_server_side_workspace_lock_expires_idle_session(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["workspace_last_activity"] = int(time.time()) - 301
        session.save()
        response = self.client.get(reverse("dashboard_home"))
        self.assertRedirects(response, f"{reverse('dashboard_login')}?reason=inactivity")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_mini_admin_can_login_and_only_sees_assigned_area(self):
        response = self.client.post(reverse("dashboard_login"), {"username": "masaka-admin", "password": "secret-pass"})
        self.assertRedirects(response, reverse("dashboard_home"))
        self.assertTrue(SecurityEvent.objects.filter(event_type="login_success", user=self.user).exists())
        response = self.client.get(reverse("dashboard_incoming"), {"district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)
        self.assertNotContains(response, self.other_incident.request.request_id)

    def test_failed_dashboard_login_is_recorded_without_storing_password(self):
        response = self.client.post(reverse("dashboard_login"), {"username": "masaka-admin", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        event = SecurityEvent.objects.get(event_type="login_failure")
        self.assertEqual(event.details, {"surface": "dashboard"})
        self.assertNotIn("wrong-password", str(event.details))

    def test_repeat_case_warning_is_visible_to_the_assigned_responder(self):
        previous_request = EmergencyRequest.objects.create(
            phone_number="+256701111111",
            area=self.masaka,
            client_uuid=uuid.UUID("66666666-6666-4666-8666-666666666666"),
            emergency_type="security",
        )
        previous_incident = Incident.objects.create(request=previous_request, assigned_area=self.masaka)
        repeat_request = EmergencyRequest.objects.create(
            phone_number="+256701111111",
            area=self.masaka,
            client_uuid=previous_request.client_uuid,
            emergency_type="medical",
        )
        repeat_incident = Incident.objects.create(
            request=repeat_request,
            assigned_area=self.masaka,
            similar_to=previous_incident,
            similarity_signal="client_uuid",
            similarity_checked_at=timezone.now(),
        )
        self.client.force_login(self.user)

        incoming = self.client.get(reverse("dashboard_incoming"), {"district": self.masaka.pk})
        self.assertContains(incoming, "Repeat signal")
        report = self.client.get(reverse("dashboard_incident", args=[repeat_incident.pk]))
        self.assertContains(report, "Possible repeat request detected")
        self.assertContains(report, previous_request.request_id)

    def test_profiled_superuser_is_limited_to_assigned_districts(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incoming"), {"district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)
        self.assertNotContains(response, self.other_incident.request.request_id)

    def test_incoming_cases_are_newest_first(self):
        newest = self._create_incident(self.masaka)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incoming"), {"district": self.masaka.pk})
        incidents = list(response.context["incidents"])
        self.assertEqual(incidents[0].pk, newest.pk)

    def test_opened_cases_leave_default_attention_queue(self):
        self.incident.opened_at = timezone.now()
        self.incident.save(update_fields=["opened_at"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incoming"), {"district": self.masaka.pk})
        self.assertNotContains(response, self.incident.request.request_id)
        response = self.client.get(reverse("dashboard_incoming"), {"view": "opened", "district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)

    def test_opened_case_is_in_archive_even_if_status_is_still_new(self):
        self.incident.opened_at = timezone.now()
        self.incident.save(update_fields=["opened_at"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_cases"), {"district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)

    def test_incoming_and_archive_group_cases_by_district(self):
        second_masaka = self._create_incident(self.masaka)
        self.incident.status = "acknowledged"
        self.incident.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incoming"))
        grouped = response.context["grouped_incidents"]
        self.assertEqual(grouped[0]["area"].name, "Masaka")
        self.assertEqual(grouped[0]["count"], 1)
        response = self.client.get(reverse("dashboard_cases"))
        grouped_cases = response.context["grouped_cases"]
        self.assertEqual(grouped_cases[0]["area"].name, "Masaka")
        self.assertEqual(grouped_cases[0]["count"], 1)

    def test_area_activity_page_ranks_the_leading_district_first(self):
        second_masaka = self._create_incident(self.masaka)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_area_activity"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cases by district")
        self.assertContains(response, "Masaka")
        ranking = response.context["area_ranking"]
        self.assertEqual(ranking[0]["area"].name, "Masaka")
        self.assertEqual(ranking[0]["count"], 2)
        self.assertEqual(response.context["period"], "month")
        self.assertEqual(len(ranking[0]["trend"]), 30)
        self.assertEqual(response.context["area_chart_data"][0]["count"], 2)
        self.assertContains(response, "Live case mix")
        self.assertContains(response, "Active incidents")
        self.assertContains(response, "Critical priority")
        self.assertContains(response, "New requests")
        self.assertContains(response, "Resolved today")
        self.assertContains(response, "area-operations-top")
        self.assertContains(response, "Incident map")
        self.assertIn("map_points", response.context)
        live_data = self.client.get(reverse("dashboard_area_activity"), {"period": "month", "format": "json"})
        self.assertEqual(live_data.status_code, 200)
        self.assertEqual(live_data.json()["total_cases"], 2)
        self.assertEqual(live_data.json()["districts"][0]["count"], 2)
        yearly = self.client.get(reverse("dashboard_area_activity"), {"period": "year"})
        self.assertEqual(yearly.status_code, 200)
        self.assertEqual(yearly.context["period"], "year")
        self.assertEqual(len(yearly.context["area_ranking"][0]["trend"]), 12)

    def test_admin_profile_shows_assignments_and_workload(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin profile")
        self.assertContains(response, "Masaka")
        self.assertContains(response, "Assigned districts")
        self.assertContains(response, "Only your assigned response areas")

    def test_operations_center_requires_passcode_and_searches_all_cases(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        access = OperationsAccess.objects.get(pk=1)
        access.set_passcode("level-five-safe")
        access.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("operations_center"))
        self.assertContains(response, "Level five passcode")
        self.assertNotContains(response, self.other_incident.request.request_id)
        response = self.client.post(reverse("operations_center"), {"passcode": "level-five-safe"})
        self.assertRedirects(response, reverse("operations_center"))
        response = self.client.get(reverse("operations_center"), {"q": self.other_incident.request.request_id})
        self.assertContains(response, self.other_incident.request.request_id)
        response = self.client.get(reverse("dashboard_incident", args=[self.other_incident.pk]))
        self.assertEqual(response.status_code, 200)

    def test_operations_center_numbers_and_searches_cases_by_number(self):
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        access = OperationsAccess.objects.get(pk=1)
        access.set_passcode("level-five-safe")
        access.save()
        self.client.force_login(self.user)
        self.client.post(reverse("operations_center"), {"passcode": "level-five-safe"})
        response = self.client.get(reverse("operations_center"))
        self.assertContains(response, "Cases by district")
        self.assertContains(response, "Kampala")
        response = self.client.get(reverse("operations_center"), {"district": self.kampala.pk})
        self.assertContains(response, f"Case {self.other_incident.pk}")
        response = self.client.get(reverse("operations_center"), {"q": str(self.other_incident.pk)})
        self.assertContains(response, self.other_incident.request.request_id)
        self.assertNotContains(response, self.incident.request.request_id)

    def test_new_report_is_assigned_to_the_only_active_district_admin(self):
        response = self.client.post(reverse("home"), {
            "phone_number": "+256700000000",
            "area_name": "Masaka",
            "location_source": "user",
            "emergency_type": "security",
            "priority": "high",
        })
        self.assertRedirects(response, reverse("submit_success"))
        incident = Incident.objects.latest("pk")
        self.assertEqual(incident.assigned_admin, self.user)

    def test_mini_admin_can_update_visible_incident_status(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {"status": "acknowledged"})
        self.assertRedirects(response, reverse("dashboard_incident", args=[self.incident.pk]))
        self.incident.refresh_from_db()
        self.assertEqual(self.incident.status, "acknowledged")
        self.assertEqual(self.incident.assigned_admin, self.user)

    def test_unassigned_case_shows_referral_notice_instead_of_django_error(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.other_incident.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Please seek a referral", status_code=403)
        self.assertContains(response, "Kampala", status_code=403)

    def test_case_without_coordinates_still_renders_a_neutral_map(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "incident-detail-map")
        self.assertContains(response, "Location not tagged")

    def test_assigned_admin_can_read_the_current_case_location(self):
        self.incident.request.latitude = "-0.340000"
        self.incident.request.longitude = "31.733300"
        self.incident.request.last_location_at = timezone.now()
        self.incident.request.save(update_fields=["latitude", "longitude", "last_location_at"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident_location", args=[self.incident.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["latitude"], -0.34)
        self.assertIsNotNone(response.json()["last_location_at"])

    def test_opening_case_moves_it_to_the_archive(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertEqual(response.status_code, 200)
        self.incident.refresh_from_db()
        self.assertIsNotNone(self.incident.opened_at)
        self.assertEqual(self.incident.status, "acknowledged")
        self.assertIsNotNone(self.incident.acknowledged_at)
        response = self.client.get(reverse("dashboard_incoming"), {"view": "unopened", "district": self.masaka.pk})
        self.assertNotContains(response, self.incident.request.request_id)
        response = self.client.get(reverse("dashboard_cases"), {"district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)

    def test_expired_chat_room_can_be_reinitiated(self):
        self.client.post(reverse("home"), {
            "phone_number": "+256700000001",
            "area_name": "Masaka",
            "emergency_type": "security",
            "priority": "high",
            "location_source": "user",
        })
        new_incident = EmergencyRequest.objects.latest("pk").incident
        new_room = EmergencyChatRoom.objects.get(incident=new_incident)
        new_room.accepted_at = timezone.now()
        new_room.expires_at = timezone.now() - timedelta(minutes=1)
        new_room.save(update_fields=["accepted_at", "expires_at"])
        response = self.client.get(reverse("submit_success"))
        self.assertEqual(response.status_code, 200)
        renewed_room = EmergencyChatRoom.objects.get(incident=new_incident)
        self.assertIsNone(renewed_room.accepted_at)
        self.assertGreater(renewed_room.expires_at, timezone.now())
        self.assertContains(response, "Can you chat with us?")

    def test_incident_report_shows_device_metadata_sections(self):
        self.incident.request.device_type = "Android phone"
        self.incident.request.operating_system = "Android"
        self.incident.request.browser = "Google Chrome"
        self.incident.request.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "Device type")
        self.assertContains(response, "Android phone")
        self.assertContains(response, "Operating system")
        self.assertContains(response, "Google Chrome")

    def test_incident_report_shows_submitted_video(self):
        recording = Recording.objects.create(
            incident=self.incident,
            file=SimpleUploadedFile("incident.webm", b"video", content_type="video/webm"),
            duration_seconds=4,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "Submitted video")
        self.assertContains(response, reverse("dashboard_recording", args=[recording.pk]))

    def test_only_parent_admin_can_delete_solved_case_data_with_passcode(self):
        recording = Recording.objects.create(
            incident=self.incident,
            file=SimpleUploadedFile("delete-me.webm", b"video", content_type="video/webm"),
            duration_seconds=4,
        )
        self.incident.status = "resolved"
        self.incident.save(update_fields=["status"])
        self.client.force_login(self.user)
        denied = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {
            "action": "delete_case",
            "delete_passcode": "778899",
        })
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(Incident.objects.filter(pk=self.incident.pk).exists())

        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])
        detail = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(detail, "Delete all case data")
        wrong = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {
            "action": "delete_case",
            "delete_passcode": "wrong-passcode",
        })
        self.assertRedirects(wrong, reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertTrue(Incident.objects.filter(pk=self.incident.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(event_type="case_delete_failure", user=self.user).exists())

        deleted = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {
            "action": "delete_case",
            "delete_passcode": "778899",
        })
        self.assertRedirects(deleted, reverse("dashboard_cases"))
        self.assertFalse(Incident.objects.filter(pk=self.incident.pk).exists())
        self.assertFalse(EmergencyRequest.objects.filter(pk=self.incident.request_id).exists())
        self.assertFalse(Recording.objects.filter(pk=recording.pk).exists())
        self.assertTrue(SecurityEvent.objects.filter(event_type="case_delete_success", user=self.user).exists())

    def test_admin_can_favorite_case_and_save_clue_notes(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {"action": "favorite"})
        self.assertRedirects(response, reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertTrue(IncidentFavorite.objects.filter(incident=self.incident, user=self.user).exists())
        response = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {
            "action": "note",
            "note": "Check the bus park camera and call the nearby patrol.",
        })
        self.assertRedirects(response, reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertEqual(IncidentNote.objects.get().author, self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "Check the bus park camera")
        self.assertContains(response, "Remove favorite")

    def test_profile_passcode_unlocks_personal_favorites_page(self):
        IncidentFavorite.objects.create(incident=self.incident, user=self.user)
        self.client.force_login(self.user)
        response = self.client.post(reverse("dashboard_profile"), {
            "action": "set_favorites_passcode",
            "favorites_passcode": "private-safe-key",
            "favorites_passcode_confirmation": "private-safe-key",
        })
        self.assertRedirects(response, reverse("dashboard_profile"))
        response = self.client.get(reverse("dashboard_favorites"))
        self.assertContains(response, "Favorites passcode")
        response = self.client.post(reverse("dashboard_favorites"), {"passcode": "private-safe-key"})
        self.assertRedirects(response, reverse("dashboard_favorites"))
        response = self.client.get(reverse("dashboard_favorites"))
        self.assertContains(response, self.incident.request.request_id)

    def test_profile_hides_passcode_fields_after_setup(self):
        self.client.force_login(self.user)
        self.client.post(reverse("dashboard_profile"), {
            "action": "set_favorites_passcode",
            "favorites_passcode": "private-safe-key",
            "favorites_passcode_confirmation": "private-safe-key",
        })
        response = self.client.get(reverse("dashboard_profile"))
        self.assertContains(response, "Favorites page passcode")
        self.assertContains(response, "configured")
        self.assertNotContains(response, 'id="favorites-passcode"')
        self.assertNotContains(response, 'id="favorites-confirmation"')

    def test_operations_center_requires_superuser_and_passcode(self):
        access = OperationsAccess.objects.get(pk=1)
        access.set_passcode("level-five-safe")
        access.save()
        self.client.force_login(self.user)
        response = self.client.post(reverse("operations_center"), {"passcode": "level-five-safe"})
        self.assertEqual(response.status_code, 403)

    def test_inactive_profile_cannot_login(self):
        self.profile.active = False
        self.profile.save()
        response = self.client.post(reverse("dashboard_login"), {"username": "masaka-admin", "password": "secret-pass"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "inactive")

    def test_institution_portal_uses_default_passcode_and_case_chat(self):
        institution = InstitutionProfile.objects.create(
            username="masaka-police-test",
            institution_type="police",
            institution_name="Masaka Police Station",
            area=self.masaka,
        )
        referral = Referral.objects.create(
            incident=self.incident,
            referred_by=self.user,
            target_type="police_station",
            target_name="Masaka Police Station",
            target_contact="",
            channel="in_app",
            message="Please respond to this case.",
            destination_area=self.masaka,
            recipient_admin=institution.user,
        )
        response = self.client.post(reverse("institution_login"), {"username": "masaka-police-test", "password": "2564"})
        self.assertRedirects(response, reverse("institution_portal"))
        self.assertContains(self.client.get(reverse("institution_portal")), referral.incident.request.request_id)
        response = self.client.post(reverse("institution_portal"), {
            "action": "change_password",
            "new_password": "private-pass-1",
            "new_password_confirmation": "private-pass-1",
        })
        self.assertRedirects(response, reverse("institution_portal"))
        map_response = self.client.get(reverse("institution_global_map"), {"case": referral.incident.pk})
        self.assertEqual(map_response.status_code, 200)
        self.assertContains(map_response, "institution-global-case-map")
        self.assertContains(map_response, referral.incident.request.request_id)
        response = self.client.post(reverse("institution_case", args=[referral.pk]), {
            "action": "message",
            "body": "Police desk has received the case.",
        })
        self.assertRedirects(response, reverse("institution_case", args=[referral.pk]))
        message = CaseMessage.objects.get()
        self.assertEqual(message.sender, institution.user)
        self.assertEqual(message.recipient, self.user)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "Police desk has received the case.")
        response = self.client.post(reverse("case_chat_feed", args=[referral.pk]), {
            "body": "Please confirm the response location.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["messages"][-1]["body"], "Please confirm the response location.")
        institution.user.refresh_from_db()
        self.client.force_login(institution.user)
        response = self.client.get(reverse("case_chat_feed", args=[referral.pk]))
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertEqual(response.json()["unread"], 1)
        response = self.client.get(reverse("case_chat_feed", args=[referral.pk]) + "?open=1")
        self.assertEqual(response.json()["unread"], 0)

    def test_hospital_directory_filters_by_district_and_hospital_login(self):
        hospital, _ = HospitalFacility.objects.get_or_create(
            name="Masaka Regional Referral Hospital",
            district=self.masaka,
            defaults={
                "ownership": "government",
                "level": "Regional Referral Hospital",
            },
        )
        institution = InstitutionProfile.objects.get(hospital_facility=hospital)
        response = self.client.get(reverse("institution_hospital_directory"), {"district": self.masaka.pk, "q": "regional"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["label"], hospital.name)
        response = self.client.post(reverse("institution_login"), {
            "district": self.masaka.pk,
            "hospital": hospital.pk,
            "password": "2564",
        })
        self.assertRedirects(response, reverse("institution_portal"))
        self.assertEqual(response.wsgi_request.user, institution.user)

    def test_police_login_uses_the_exact_selected_district_account(self):
        parent_area = LocationArea.objects.create(name="Test Masaka District", district="Test Masaka District")
        child_area = LocationArea.objects.create(name="Test Masaka City", district="Test Masaka City")
        city_user = get_user_model().objects.create_user(username="test-masaka-city-police", password="city-private-pass")
        InstitutionProfile.objects.create(
            username="Test Masaka City",
            institution_type="police",
            institution_name="Test Masaka City Police Station",
            area=child_area,
            user=city_user,
        )
        district_user = get_user_model().objects.create_user(username="test-masaka-district-police", password="2564")
        InstitutionProfile.objects.create(
            username="Test Masaka District",
            institution_type="police",
            institution_name="Test Masaka District Police Station",
            area=parent_area,
            user=district_user,
        )
        response = self.client.post(reverse("institution_login"), {
            "institution_type": "police",
            "district": parent_area.pk,
            "password": "2564",
        })
        self.assertRedirects(response, reverse("institution_portal"))
        self.assertEqual(response.wsgi_request.user, district_user)

    def test_active_filter_and_map_include_only_open_incidents_with_coordinates(self):
        self.incident.request.latitude = "-0.340000"
        self.incident.request.longitude = "31.733300"
        self.incident.request.save()
        self.other_incident.status = "resolved"
        self.other_incident.request.latitude = "0.347600"
        self.other_incident.request.longitude = "32.582500"
        self.other_incident.request.save()
        self.other_incident.save()
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_home"))
        self.assertContains(response, self.incident.request.request_id)
        self.assertNotContains(response, self.other_incident.request.request_id)
        self.assertContains(response, "incident-map")
        self.assertContains(response, "district-case-chart")

    def test_global_map_is_scoped_to_active_cases_in_assigned_areas(self):
        for incident, latitude, longitude in (
            (self.incident, "-0.340000", "31.733300"),
            (self.other_incident, "0.347600", "32.582500"),
        ):
            incident.request.latitude = latitude
            incident.request.longitude = longitude
            incident.request.save(update_fields=["latitude", "longitude"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_global_map"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "global-case-map")
        self.assertContains(response, self.incident.request.request_id)
        self.assertNotContains(response, self.other_incident.request.request_id)

    def test_global_map_focuses_on_the_requested_case(self):
        self.incident.request.latitude = "-0.340000"
        self.incident.request.longitude = "31.733300"
        self.incident.request.save(update_fields=["latitude", "longitude"])
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_global_map"), {"case": self.incident.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tracking " + self.incident.request.request_id)
        selected_points = [point for point in response.context["map_points"] if point["selected"]]
        self.assertEqual([point["id"] for point in selected_points], [self.incident.pk])

    def test_global_map_shows_the_area_alert_composer(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_global_map"))
        self.assertContains(response, "Send an area alert")
        self.assertContains(response, "Send when your team verifies a public need")
        self.assertContains(response, "Do not include names, phone numbers, or exact case locations.")

    @override_settings(WEBPUSH_VAPID_PUBLIC_KEY="", WEBPUSH_VAPID_PRIVATE_KEY="", WEBPUSH_VAPID_SUBJECT="")
    def test_public_area_alert_can_be_sent_for_an_early_security_warning(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("dashboard_global_map"), {
            "action": "send_area_alert",
            "alert_area": self.masaka.pk,
            "alert_issue_type": "security",
            "alert_title": "Security information",
            "alert_body": "Please use well-lit routes and contact the response desk if you need assistance.",
        }, follow=True)
        self.assertEqual(response.status_code, 200)
        alert = AreaAlert.objects.get()
        self.assertEqual(alert.area, self.masaka)
        self.assertEqual(alert.case_count_snapshot, 1)
        self.assertEqual(alert.delivery_status, "not_configured")
        self.assertContains(response, "Web Push is not configured yet")

    def test_public_alert_detail_page_shows_safe_notification_content(self):
        alert = AreaAlert.objects.create(
            area=self.masaka,
            created_by=self.user,
            title="Road safety information",
            body="Please use the marked route and follow official guidance.",
            issue_type="security",
            idempotency_key="public-alert-detail-test",
        )
        response = self.client.get(reverse("public_area_alert_detail", args=[alert.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Road safety information")
        self.assertContains(response, "Please use the marked route")
        self.assertContains(response, "Masaka")

    def test_public_alert_history_page_shows_recent_delivered_notifications(self):
        AreaAlert.objects.create(
            area=self.masaka,
            created_by=self.user,
            title="Active road safety notice",
            body="Please use the marked route and follow official guidance.",
            delivery_status="sent",
            idempotency_key="public-alert-history-sent-test",
        )
        AreaAlert.objects.create(
            area=self.masaka,
            created_by=self.user,
            title="Undelivered internal notice",
            body="This notice was not delivered to subscribed browsers.",
            delivery_status="failed",
            idempotency_key="public-alert-history-failed-test",
        )
        response = self.client.get(reverse("public_alert_history"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sent public notifications")
        self.assertContains(response, "Active road safety notice")
        self.assertContains(response, "Masaka")
        self.assertNotContains(response, "Undelivered internal notice")

    def test_travel_location_area_resolves_gps_to_the_starting_district(self):
        response = self.client.post(
            reverse("travel_location_area"),
            data=json.dumps({"latitude": -0.340000, "longitude": 31.733300}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["area"]["name"], "Masaka")
        self.assertIn("destination", response.json()["message"].lower())

    def test_expired_public_alert_detail_redirects_without_exposing_notice(self):
        alert = AreaAlert.objects.create(
            area=self.masaka,
            created_by=self.user,
            title="Expired road notice",
            body="This message is no longer current.",
            idempotency_key="expired-public-alert-test",
        )
        AreaAlert.objects.filter(pk=alert.pk).update(created_at=timezone.now() - timedelta(hours=5))
        response = self.client.get(reverse("public_area_alert_detail", args=[alert.pk]))
        self.assertRedirects(response, reverse("subscriber_alerts"))

    def test_public_alert_subscription_is_saved_for_one_district(self):
        response = self.client.post(
            reverse("public_alert_subscribe"),
            data=json.dumps({
                "area_id": self.masaka.pk,
                "endpoint": "https://push.example.test/subscription-1",
                "keys": {"p256dh": "public-key", "auth": "auth-key"},
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        subscription = PublicAlertSubscription.objects.get()
        self.assertEqual(subscription.area, self.masaka)
        self.assertTrue(subscription.active)
        self.assertEqual(subscription.endpoint, "https://push.example.test/subscription-1")

    def test_subscriber_page_saves_multiple_places_and_travel_watch(self):
        response = self.client.get(reverse("subscriber_alerts"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Safety alerts and travel watch")
        self.assertContains(response, "Use GPS for live trip view")
        self.assertContains(response, "Find a district")
        endpoint = "https://push.example.test/travel-subscription"
        subscription_payload = {
            "endpoint": endpoint,
            "keys": {"p256dh": "public-key", "auth": "auth-key"},
            "area_ids": [self.masaka.pk, self.kampala.pk],
        }
        response = self.client.post(
            reverse("public_alert_subscribe"),
            data=json.dumps(subscription_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        subscription = PublicAlertSubscription.objects.get(endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest())
        self.assertEqual(set(subscription.notification_areas.values_list("pk", flat=True)), {self.masaka.pk, self.kampala.pk})
        response = self.client.post(
            reverse("travel_alert_plan"),
            data=json.dumps({
                **subscription_payload,
                "origin_area": self.masaka.pk,
                "destination_area": self.kampala.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["route_map"]["features"]), 2)
        plan = TravelSafetyPlan.objects.get(subscription=subscription, active=True)
        self.assertEqual(plan.origin_area, self.masaka)
        self.assertEqual(plan.destination_area, self.kampala)
        self.assertTrue(plan.route_areas.filter(pk=self.masaka.pk).exists())
        self.assertTrue(plan.route_areas.filter(pk=self.kampala.pk).exists())

        travel_only_endpoint = "https://push.example.test/travel-only"
        response = self.client.post(
            reverse("travel_alert_plan"),
            data=json.dumps({
                "endpoint": travel_only_endpoint,
                "keys": {"p256dh": "travel-public-key", "auth": "travel-auth-key"},
                "origin_area": self.masaka.pk,
                "destination_area": self.kampala.pk,
                "area_ids": [],
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        travel_only = PublicAlertSubscription.objects.get(endpoint_hash=hashlib.sha256(travel_only_endpoint.encode()).hexdigest())
        self.assertFalse(travel_only.receives_area_alerts)
        response = self.client.post(
            reverse("travel_alert_stop"),
            data=json.dumps({"endpoint": travel_only_endpoint}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TravelSafetyPlan.objects.get(subscription=travel_only).active)

    @override_settings(GOOGLE_MAPS_API_KEY="test-google-server-key")
    def test_travel_watch_uses_google_traffic_when_configured(self):
        endpoint = "https://push.example.test/google-traffic"
        google_response = {
            "routes": [{
                "distanceMeters": 120000,
                "duration": "7200s",
                "staticDuration": "5400s",
                "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
            }],
        }
        with patch("incidents.views.urlopen") as mocked_urlopen:
            response = mocked_urlopen.return_value.__enter__.return_value
            response.read.return_value = json.dumps(google_response).encode("utf-8")
            result = self.client.post(
                reverse("travel_alert_plan"),
                data=json.dumps({
                    "endpoint": endpoint,
                    "keys": {"p256dh": "public-key", "auth": "auth-key"},
                    "origin_area": self.masaka.pk,
                    "destination_area": self.kampala.pk,
                    "start_latitude": "-0.3400",
                    "start_longitude": "31.7333",
                    "area_ids": [],
                }),
                content_type="application/json",
            )

        self.assertEqual(result.status_code, 200)
        traffic = result.json()["google_traffic"]
        self.assertEqual(result.json()["traffic_provider"], "Google")
        self.assertTrue(result.json()["traffic_available"])
        self.assertEqual(traffic["traffic_level"], "Heavy")
        self.assertEqual(traffic["traffic_delay_seconds"], 1800)
        self.assertGreater(len(traffic["road_points"]), 1)
        mocked_urlopen.assert_called_once()

    def test_travel_route_can_be_calculated_without_browser_alert_subscription(self):
        response = self.client.post(
            reverse("travel_alert_plan"),
            data=json.dumps({
                "origin_area": self.masaka.pk,
                "destination_area": self.kampala.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["watch_active"])
        self.assertIsNone(response.json()["plan_id"])
        self.assertIn("Route calculated", response.json()["message"])
        self.assertFalse(TravelSafetyPlan.objects.exists())

    def test_travel_corridor_does_not_become_a_saved_notification_place(self):
        endpoint = "https://push.example.test/travel-corridor-only"
        subscription_payload = {
            "endpoint": endpoint,
            "keys": {"p256dh": "public-key", "auth": "auth-key"},
            "area_ids": [self.masaka.pk],
        }
        response = self.client.post(
            reverse("public_alert_subscribe"),
            data=json.dumps(subscription_payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("travel_alert_plan"),
            data=json.dumps({
                **subscription_payload,
                "origin_area": self.masaka.pk,
                "destination_area": self.kampala.pk,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        subscription = PublicAlertSubscription.objects.get(endpoint_hash=hashlib.sha256(endpoint.encode()).hexdigest())
        self.assertEqual(set(subscription.notification_areas.values_list("pk", flat=True)), {self.masaka.pk})
        self.assertTrue(TravelSafetyPlan.objects.get(subscription=subscription).route_areas.filter(pk=self.kampala.pk).exists())
        response = self.client.post(
            reverse("public_alert_preferences"),
            data=json.dumps({"endpoint": endpoint}),
            content_type="application/json",
        )
        self.assertEqual(response.json()["areas"], [self.masaka.pk])

    def test_inhouse_chat_uses_district_codes_and_delivers_messages(self):
        user_model = get_user_model()
        kampala_admin = user_model.objects.create_user(username="kampala-admin", password="secret-pass")
        kampala_profile = ResponseProfile.objects.create(user=kampala_admin)
        kampala_profile.areas.add(self.kampala)
        self.client.force_login(self.user)
        response = self.client.get(reverse("inhouse_chat"))
        self.assertContains(response, "msk")
        self.assertContains(response, "kpl")
        response = self.client.post(reverse("inhouse_chat"), {
            "peer": kampala_admin.pk,
            "body": "Masaka response team checking in.",
        })
        self.assertRedirects(response, f"{reverse('inhouse_chat')}?peer={kampala_admin.pk}")
        conversation = InHouseConversation.objects.get(user_one_id=min(self.user.pk, kampala_admin.pk), user_two_id=max(self.user.pk, kampala_admin.pk))
        message = InHouseMessage.objects.filter(conversation=conversation).first()
        self.assertIsNotNone(message)
        self.assertTrue(message.body.startswith("Masaka response"))
        response = self.client.get(reverse("inhouse_chat"), {"format": "json", "peer": kampala_admin.pk})
        self.assertEqual(response.json()["messages"][0]["sender_code"], "msk")

    def test_acted_case_moves_to_archive_and_can_be_referred(self):
        self.client.force_login(self.user)
        self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {"status": "acknowledged"})
        response = self.client.get(reverse("dashboard_incoming"), {"view": "unopened"})
        self.assertEqual(list(response.context["incidents"]), [])
        response = self.client.get(reverse("dashboard_cases"), {"district": self.masaka.pk})
        self.assertContains(response, self.incident.request.request_id)
        response = self.client.post(reverse("dashboard_incident", args=[self.incident.pk]), {
            "action": "refer",
            "target_type": "organization",
            "target_name": "Masaka Police Office",
            "target_contact": "+256700000001",
            "channel": "whatsapp",
            "message": "Please assist with this emergency.",
        })
        self.assertEqual(response.status_code, 302)
        referral = Referral.objects.get()
        self.assertEqual(referral.target_name, "Masaka Police Office")
        self.assertEqual(referral.referred_by, self.user)

    def test_referral_workspace_sends_in_app_transfer_to_another_admin(self):
        recipient = get_user_model().objects.create_user(username="kampala-admin", password="secret-pass")
        recipient_profile = ResponseProfile.objects.create(user=recipient)
        recipient_profile.areas.add(self.kampala)
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard_referral_admin_search"), {"q": "kampala"})
        self.assertEqual(response.status_code, 200)
        search_result = response.json()["results"][0]
        self.assertIn("Kampala", search_result["label"])
        self.assertNotIn("kampala-admin", search_result["label"])
        response = self.client.post(reverse("dashboard_referral_create", args=[self.incident.pk]), {
            "target_type": "admin",
            "recipient_admin": recipient.pk,
            "channel": "in_app",
            "message": "Please coordinate support from your side.",
        })
        self.assertEqual(response.status_code, 302)
        referral = Referral.objects.get()
        self.assertEqual(referral.recipient_admin, recipient)
        self.assertEqual(referral.channel, "in_app")
        self.assertTrue(referral.referral_token_hash)
        referral_token = self.client.session["referral_token_notice"]["token"]
        token_user = get_user_model().objects.create_user(username="token-admin", password="secret-pass")
        ResponseProfile.objects.create(user=token_user)
        self.client.force_login(token_user)
        response = self.client.post(reverse("dashboard_referral_token"), {"token": referral_token})
        self.assertRedirects(response, reverse("dashboard_incident", args=[self.incident.pk]))
        response = self.client.get(reverse("dashboard_incident", args=[self.incident.pk]))
        self.assertContains(response, "Access granted through a secure referral token.")
        self.client.force_login(recipient)
        response = self.client.get(reverse("dashboard_referral_inbox"))
        self.assertContains(response, self.incident.request.request_id)
        self.assertContains(response, "Please coordinate support")

    def test_configured_police_referral_requires_matching_district(self):
        station = ReferralDestination.objects.create(
            name="Masaka Central Police Station",
            destination_type="police_station",
            area=self.masaka,
            contact="+256700000002",
        )
        self.client.force_login(self.user)
        response = self.client.post(reverse("dashboard_referral_create", args=[self.incident.pk]), {
            "target_type": "police_station",
            "destination": station.pk,
            "channel": "sms",
            "message": "Please respond.",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Choose the district where the destination is located.")
        response = self.client.post(reverse("dashboard_referral_create", args=[self.incident.pk]), {
            "target_type": "police_station",
            "destination_area": self.masaka.pk,
            "destination": station.pk,
            "channel": "sms",
            "message": "Please respond.",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Referral.objects.get().destination, station)


class EncryptionAndMFATests(TestCase):
    def test_sensitive_incident_values_are_encrypted_at_rest(self):
        request = EmergencyRequest.objects.create(
            phone_number="+256700000000",
            latitude="-0.312800",
            longitude="31.713500",
            location_description="Private landmark",
            message="Confidential emergency details",
            ip_address="192.0.2.10",
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT phone_number, latitude, location_description, message, ip_address "
                "FROM incidents_emergencyrequest WHERE id = %s",
                [request.pk],
            )
            raw_values = cursor.fetchone()
        self.assertTrue(all(str(value).startswith("enc:v1:") for value in raw_values))
        restored = EmergencyRequest.objects.get(pk=request.pk)
        self.assertEqual(restored.phone_number, "+256700000000")
        self.assertEqual(str(restored.latitude), "-0.312800")
        self.assertEqual(restored.location_description, "Private landmark")
        self.assertEqual(restored.message, "Confidential emergency details")
        self.assertEqual(restored.ip_address, "192.0.2.10")

    @override_settings(MFA_REQUIRED=True)
    def test_dashboard_login_requires_and_completes_mfa(self):
        area = LocationArea.objects.get(name="Masaka")
        user = get_user_model().objects.create_user(username="mfa-responder", password="secret-pass")
        profile = ResponseProfile.objects.create(user=user)
        profile.areas.add(area)

        response = self.client.post(reverse("dashboard_login"), {
            "username": "mfa-responder",
            "password": "secret-pass",
        })
        self.assertRedirects(response, reverse("mfa_setup"))
        response = self.client.get(reverse("mfa_setup"))
        self.assertEqual(response.status_code, 200)
        secret = MFAProfile.objects.get(user=user).secret
        code = totp_code(secret, int(time.time() // 30))
        response = self.client.post(reverse("mfa_setup"), {"code": code})
        self.assertRedirects(response, reverse("dashboard_home"))
        self.assertTrue(MFAProfile.objects.get(user=user).enabled)
        self.assertTrue(self.client.get(reverse("dashboard_home")).status_code == 200)


class AdminSectionGateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="parent-admin",
            email="parent@example.com",
            password="secret-pass",
        )
        self.client.force_login(self.user)

    def test_admin_section_requires_gate_password(self):
        admin_url = reverse("admin:index")
        response = self.client.get(admin_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("admin_section_gate"), response["Location"])
        response = self.client.post(reverse("admin_section_gate"), {
            "password": "mindset123..",
            "next": admin_url,
        })
        self.assertRedirects(response, admin_url)
        self.assertEqual(self.client.get(admin_url).status_code, 200)

    def test_admin_section_rejects_wrong_gate_password(self):
        response = self.client.post(reverse("admin_section_gate"), {
            "password": "wrong-password",
            "next": "/admin/",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "administration password is incorrect")


class ChannelsWebsocketTests(TransactionTestCase):
    reset_sequences = True

    def test_public_emergency_chat_uses_websocket_and_persists_messages(self):
        area = LocationArea.objects.get(name="Masaka")
        request = EmergencyRequest.objects.create(
            phone_number="+256700000000",
            area=area,
            emergency_type="danger",
        )
        incident = Incident.objects.create(request=request, assigned_area=area)
        room = EmergencyChatRoom.objects.create(
            incident=incident,
            expires_at=timezone.now() + timedelta(hours=48),
        )
        public_client = Client()
        session = public_client.session
        session["request_id"] = request.request_id
        session.save()

        async def exercise():
            token = make_websocket_token("emergency", [incident.pk], sender_type="public")
            communicator = WebsocketCommunicator(
                application,
                f"/ws/chat/incidents/{incident.pk}/?token={quote(token, safe='')}",
                headers=[(b"host", b"testserver"), (b"origin", b"http://testserver")],
            )
            connected, response = await communicator.connect()
            self.assertTrue(connected, f"{communicator.scope} response={response}")
            ready = await communicator.receive_json_from()
            self.assertEqual(ready["type"], "chat.ready")
            await async_broadcast_emergency_chat_update(incident.pk)
            await asyncio.sleep(0.1)
            refresh = await communicator.receive_json_from()
            self.assertEqual(refresh["type"], "chat.refresh")
            await communicator.disconnect()

        asyncio.run(exercise())
        chat_url = reverse("emergency_chat", args=[incident.pk])
        response = public_client.post(chat_url, {"action": "accept"})
        self.assertEqual(response.status_code, 200)
        response = public_client.post(chat_url, {
            "action": "message",
            "body": "WebSocket message received.",
            "idempotency_key": "websocket-message-001",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(room.messages.filter(sender_type="public").count(), 1)
