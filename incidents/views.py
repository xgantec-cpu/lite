from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.hashers import check_password
from django.contrib.auth.decorators import login_required
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import FileResponse, HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request as UrlRequest, urlopen
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import base64
import hashlib
import json
import logging
import math
import mimetypes
import os
import re
import secrets
import uuid
from datetime import timedelta
from pathlib import Path

from .forms import EmergencyRequestForm
from .forms_referral import ReferralForm, masked_admin_label
from .audit import record_security_event
from .device_detection import detect_device
from .geography import area_name_for_boundary, boundary_features, boundary_name_for_point, route_area_names
from .healthcare import matching_area_ids
from .models import AreaAlert, CallRequest, CaseMessage, EmergencyChatCall, EmergencyChatMessage, EmergencyChatRoom, EmergencyRequest, HospitalFacility, Incident, IncidentFavorite, IncidentNote, InHouseConversation, InHouseMessage, InstitutionProfile, LocationArea, LocationPing, MFAProfile, OperationsAccess, PublicAlertSubscription, Recording, Referral, ResponseProfile, TravelSafetyPlan, area_routing_code
from .mfa import generate_secret, otpauth_uri, verify_totp
from .realtime import broadcast_case_chat_update, broadcast_emergency_chat_update, broadcast_inhouse_chat_update
from .websocket_auth import make_public_chat_token, make_websocket_token, public_chat_token_identity, public_chat_token_matches


CRITICAL_TRACKING_WINDOW = timedelta(minutes=30)
PUBLIC_ALERT_LIFETIME = timedelta(hours=4)
PUBLIC_ALERT_SUBSCRIPTION_COOKIE = "rapid_response_public_alert_subscription"
PUBLIC_ALERT_SUBSCRIPTION_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
TRACKING_OPEN_STATUSES = {"new", "acknowledged", "responding"}
MAX_VIDEO_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_AUDIO_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_CHAT_FILE_BYTES = 20 * 1024 * 1024
ALLOWED_VIDEO_TYPES = {"video/webm", "video/mp4", "video/quicktime", "video/ogg"}
ALLOWED_VIDEO_EXTENSIONS = {".webm", ".mp4", ".mov", ".m4v", ".ogv"}
ALLOWED_AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav", "audio/x-wav"}
MFA_SURFACE_LABELS = {
    "dashboard": "responder dashboard",
    "institution": "institution portal",
    "admin": "main administration",
}
ALLOWED_AUDIO_EXTENSIONS = {".webm", ".ogg", ".mp3", ".m4a", ".wav"}
ALLOWED_CHAT_FILE_TYPES = {
    "application/pdf", "application/json", "application/zip", "application/x-zip-compressed",
    "application/msword", "application/vnd.ms-excel", "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv", "image/jpeg", "image/png", "image/gif", "image/webp",
    "audio/webm", "audio/ogg", "audio/mpeg", "audio/mp4", "audio/wav",
    "video/webm", "video/mp4", "video/quicktime", "video/ogg",
}
ALLOWED_CHAT_FILE_EXTENSIONS = {
    ".pdf", ".json", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".webm", ".ogg",
    ".mp3", ".m4a", ".wav", ".mp4", ".mov",
}
logger = logging.getLogger(__name__)


def _is_allowed_upload(upload, content_types, extensions):
    if upload is None:
        return False
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(upload.name or "").suffix.lower()
    return content_type in content_types and extension in extensions


def _is_allowed_chat_file(upload):
    if upload is None or upload.size > MAX_CHAT_FILE_BYTES:
        return False
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    extension = Path(upload.name or "").suffix.lower()
    return extension in ALLOWED_CHAT_FILE_EXTENSIONS and (
        content_type in ALLOWED_CHAT_FILE_TYPES or content_type in {"", "application/octet-stream"}
    )


def _chat_file_fields(upload):
    content_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    return {
        "attachment": upload,
        "attachment_name": Path(upload.name or "attachment").name[:255],
        "attachment_content_type": content_type[:120],
        "attachment_size": upload.size,
    }


def _write_idempotency_key(request, scope, *values):
    supplied_key = request.headers.get("Idempotency-Key") or request.POST.get("idempotency_key")
    if supplied_key:
        raw_key = supplied_key.strip()[:128]
    else:
        payload = request.POST.copy()
        payload.pop("csrfmiddlewaretoken", None)
        payload.pop("idempotency_key", None)
        raw_key = payload.urlencode()
    user_key = request.user.pk if request.user.is_authenticated else request.session.session_key or "anonymous"
    bucket = int(timezone.now().timestamp() // 30)
    fingerprint = "|".join([scope, str(user_key), raw_key, *[str(value) for value in values], str(bucket)])
    return hashlib.sha256(fingerprint.encode()).hexdigest()


def websocket_access_token(request, kind, allowed_ids, sender_type=None):
    return make_websocket_token(
        kind,
        allowed_ids,
        user_id=request.user.pk if request.user.is_authenticated else None,
        sender_type=sender_type,
    )


def _mfa_surface_allowed(user, surface):
    if surface == "dashboard":
        return _can_access_dashboard(user)
    if surface == "institution":
        return _can_access_institution(user)
    return user.is_active and user.is_superuser


def _mfa_profile(user):
    profile, _ = MFAProfile.objects.get_or_create(user=user)
    return profile


def _mfa_begin(request, user, surface, return_path=None):
    profile = _mfa_set_pending(request, user, surface, return_path=return_path)
    return redirect("mfa_verify" if profile.enabled else "mfa_setup")


def _mfa_set_pending(request, user, surface, return_path=None):
    request.session.cycle_key()
    request.session["mfa_pending_user_id"] = user.pk
    request.session["mfa_pending_surface"] = surface
    request.session["mfa_return_path"] = return_path or {
        "dashboard": reverse("dashboard_home"),
        "institution": reverse("institution_portal"),
        "admin": "/admin/",
    }[surface]
    request.session["mfa_started_at"] = int(timezone.now().timestamp())
    request.session.pop("mfa_pending_secret", None)
    return _mfa_profile(user)


def _mfa_pending_user(request):
    user_id = request.session.get("mfa_pending_user_id")
    surface = request.session.get("mfa_pending_surface")
    started_at = request.session.get("mfa_started_at")
    if not user_id or surface not in MFA_SURFACE_LABELS or not started_at:
        return None, None
    if int(timezone.now().timestamp()) - int(started_at) > settings.MFA_CHALLENGE_AGE:
        _mfa_clear(request)
        return None, None
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or not _mfa_surface_allowed(user, surface):
        _mfa_clear(request)
        return None, None
    return user, surface


def _mfa_clear(request):
    for key in (
        "mfa_pending_user_id",
        "mfa_pending_surface",
        "mfa_return_path",
        "mfa_started_at",
        "mfa_pending_secret",
    ):
        request.session.pop(key, None)


def _mfa_complete(request, user, surface):
    return_path = request.session.get("mfa_return_path") or {
        "dashboard": reverse("dashboard_home"),
        "institution": reverse("institution_portal"),
        "admin": "/admin/",
    }[surface]
    login(request, user)
    request.session["mfa_verified_user"] = user.pk
    _mfa_clear(request)
    record_security_event(request, "login_success", user=user, details={"surface": surface, "mfa": True})
    return redirect(return_path)


def _mfa_required_for(user):
    profile = MFAProfile.objects.filter(user=user).only("enabled").first()
    return settings.MFA_REQUIRED or bool(profile and profile.enabled)


def mfa_setup(request: HttpRequest) -> HttpResponse:
    user, surface = _mfa_pending_user(request)
    if user is None and request.user.is_authenticated and _can_access_dashboard(request.user):
        _mfa_set_pending(request, request.user, "dashboard")
        user, surface = _mfa_pending_user(request)
    if user is None:
        return redirect("dashboard_login")
    profile = _mfa_profile(user)
    if profile.enabled:
        return redirect("mfa_verify")
    secret = profile.secret
    if not secret:
        secret = generate_secret()
        profile.set_secret(secret)
        profile.save(update_fields=["secret", "enabled", "last_used_counter", "confirmed_at", "updated_at"])
    error = None
    if request.method == "POST":
        counter = verify_totp(secret, request.POST.get("code"))
        if counter is None:
            record_security_event(request, "mfa_failure", user=user, details={"surface": surface, "stage": "setup"})
            error = "That code is not valid. Check your authenticator time and try again."
        else:
            profile.set_secret(secret)
            profile.enabled = True
            profile.last_used_counter = counter
            profile.confirmed_at = timezone.now()
            profile.save()
            record_security_event(request, "mfa_enabled", user=user, details={"surface": surface})
            return _mfa_complete(request, user, surface)
    return render(request, "auth/mfa.html", {
        "mode": "setup",
        "surface_label": MFA_SURFACE_LABELS[surface],
        "secret": secret,
        "otpauth_uri": otpauth_uri(secret, user.get_username()),
        "error": error,
    })


def mfa_verify(request: HttpRequest) -> HttpResponse:
    user, surface = _mfa_pending_user(request)
    if user is None:
        return redirect("dashboard_login")
    profile = _mfa_profile(user)
    if not profile.enabled or not profile.secret:
        return redirect("mfa_setup")
    error = None
    if request.method == "POST":
        if _rate_limited(request, f"mfa-verify:{user.pk}", limit=5, window=300):
            record_security_event(request, "mfa_failure", user=user, details={"surface": surface, "reason": "throttled"})
            error = "Too many verification attempts. Please wait five minutes."
        else:
            with transaction.atomic():
                profile = MFAProfile.objects.select_for_update().get(pk=profile.pk)
                counter = verify_totp(
                    profile.secret,
                    request.POST.get("code"),
                    last_used_counter=profile.last_used_counter,
                )
                if counter is not None:
                    profile.last_used_counter = counter
                    profile.save(update_fields=["last_used_counter", "updated_at"])
            if counter is None:
                record_security_event(request, "mfa_failure", user=user, details={"surface": surface, "reason": "invalid_code"})
                error = "That code is not valid or has already been used."
            else:
                return _mfa_complete(request, user, surface)
    return render(request, "auth/mfa.html", {
        "mode": "verify",
        "surface_label": MFA_SURFACE_LABELS[surface],
        "error": error,
    })


def _rate_limited(request, scope, limit=30, window=60):
    address = request.META.get("REMOTE_ADDR", "unknown")
    key = f"rate-limit:{scope}:{address}"
    try:
        if cache.add(key, 1, timeout=window):
            return False
        count = cache.incr(key)
        return count > limit
    except (OSError, ValueError, NotImplementedError):
        return False


@transaction.atomic
def home(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = EmergencyRequestForm(request.POST)
        if _rate_limited(request, "public-emergency-submit"):
            form.add_error(None, "Too many requests. Please wait a minute before trying again.")
            return render(request, "incidents/home.html", {
                "form": form,
                "districts": LocationArea.objects.filter(active=True),
            }, status=429)
        device = detect_device(request.META.get("HTTP_USER_AGENT", ""))
        video = request.FILES.get("video")
        if request.POST.get("quick_mode") == "1" and not video:
            form.add_error(None, "Quick help requires a recorded video.")
        if video:
            duration = request.POST.get("recording_duration")
            try:
                duration_value = int(duration)
            except (TypeError, ValueError):
                duration_value = 0
            if not _is_allowed_upload(video, ALLOWED_VIDEO_TYPES, ALLOWED_VIDEO_EXTENSIONS):
                form.add_error(None, "The quick-help file must be a video.")
            elif video.size > MAX_VIDEO_UPLOAD_BYTES:
                form.add_error(None, "The video must be smaller than 25 MB.")
            elif duration_value < 1 or duration_value > 20:
                form.add_error(None, "The quick-help video must be between 1 and 20 seconds.")
        if form.is_valid():
            idempotency_key = form.cleaned_data.get("idempotency_key") or uuid.uuid4().hex
            existing_request = EmergencyRequest.objects.filter(idempotency_key=idempotency_key).first()
            if existing_request:
                request.session["request_id"] = existing_request.request_id
                return redirect("submit_success")
            emergency_request = form.save(commit=False)
            emergency_request.idempotency_key = idempotency_key
            emergency_request.ip_address = request.META.get("REMOTE_ADDR")
            emergency_request.device_type = device["device_type"]
            emergency_request.operating_system = device["operating_system"]
            emergency_request.browser = device["browser"]
            emergency_request.area = _resolve_area_from_coordinates(
                emergency_request.latitude,
                emergency_request.longitude,
                emergency_request.area,
            )
            emergency_request.tracking_enabled = bool(
                emergency_request.priority == "critical"
                and emergency_request.location_source == "gps"
                and emergency_request.latitude is not None
                and emergency_request.longitude is not None
                and emergency_request.client_uuid
            )
            try:
                with transaction.atomic():
                    emergency_request.save()
                    similar_incident, similarity_signal = _find_similar_incident(emergency_request)
                    incident = Incident.objects.create(
                        request=emergency_request,
                        assigned_area=emergency_request.area,
                        assigned_admin=_district_admin(emergency_request.area),
                        similar_to=similar_incident,
                        similarity_signal=similarity_signal,
                        similarity_checked_at=timezone.now(),
                    )
                    _ensure_emergency_chat_room(incident)
                    if video:
                        duration = request.POST.get("recording_duration")
                        try:
                            duration = min(int(duration), 20)
                        except (TypeError, ValueError):
                            duration = None
                        Recording.objects.create(incident=incident, file=video, duration_seconds=duration)
            except IntegrityError:
                existing_request = EmergencyRequest.objects.filter(idempotency_key=idempotency_key).first()
                if existing_request:
                    request.session["request_id"] = existing_request.request_id
                    return redirect("submit_success")
                raise
            request.session["request_id"] = emergency_request.request_id
            return redirect("submit_success")
    else:
        form = EmergencyRequestForm(initial={"priority": "high", "location_source": "user", "idempotency_key": uuid.uuid4().hex})
    return render(request, "incidents/home.html", {
        "form": form,
        "districts": LocationArea.objects.filter(active=True),
        "webpush_public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY,
    })


def service_worker(request: HttpRequest) -> HttpResponse:
    response = render(request, "service-worker.js", content_type="application/javascript")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["Service-Worker-Allowed"] = "/"
    return response


def _upsert_public_alert_subscription(request, payload, areas, save_direct_areas=True, direct_areas=None):
    endpoint = str(payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    p256dh = str(keys.get("p256dh") or "").strip()
    auth = str(keys.get("auth") or "").strip()
    if not endpoint.startswith("https://") or not p256dh or not auth or not areas:
        raise ValueError("Choose at least one district and provide a valid browser subscription.")
    direct_areas = list(areas if direct_areas is None else direct_areas)
    client_uuid = _parse_client_uuid(payload.get("client_uuid"))
    endpoint_hash = hashlib.sha256(endpoint.encode("utf-8")).hexdigest()
    subscription = PublicAlertSubscription.objects.filter(endpoint_hash=endpoint_hash).first()
    previous_area_id = subscription.area_id if subscription else None
    previous_direct_alerts = subscription.receives_area_alerts if subscription else False
    if subscription is None:
        subscription = PublicAlertSubscription.objects.create(
            area=areas[0],
            receives_area_alerts=save_direct_areas,
            endpoint_hash=endpoint_hash,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            client_uuid=client_uuid,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:300],
            active=True,
        )
    else:
        subscription.endpoint = endpoint
        subscription.p256dh = p256dh
        subscription.auth = auth
        subscription.client_uuid = client_uuid
        subscription.user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
        subscription.active = True
        subscription.last_seen_at = timezone.now()
        subscription.save(update_fields=["endpoint", "p256dh", "auth", "client_uuid", "user_agent", "active", "last_seen_at"])
    if save_direct_areas:
        if not subscription.receives_area_alerts:
            subscription.receives_area_alerts = True
            subscription.area = direct_areas[0] if direct_areas else areas[0]
            subscription.save(update_fields=["receives_area_alerts", "area"])
        if previous_area_id and previous_direct_alerts:
            subscription.notification_areas.add(previous_area_id)
        subscription.notification_areas.add(*[area.pk for area in direct_areas])
    return subscription


def _subscription_area_list(subscription):
    if not subscription.receives_area_alerts:
        return []
    area_ids = set(subscription.notification_areas.values_list("pk", flat=True))
    if subscription.area_id:
        area_ids.add(subscription.area_id)
    return list(LocationArea.objects.filter(pk__in=area_ids, active=True).order_by("name"))


def _public_alert_subscription_from_request(request):
    endpoint_hash = request.get_signed_cookie(PUBLIC_ALERT_SUBSCRIPTION_COOKIE, default="")
    if not re.fullmatch(r"[0-9a-f]{64}", endpoint_hash):
        return None
    return PublicAlertSubscription.objects.filter(endpoint_hash=endpoint_hash, active=True).first()


def _public_alert_area_ids(subscription):
    if subscription is None:
        return set()
    area_ids = set()
    if subscription.receives_area_alerts:
        area_ids.update(subscription.notification_areas.values_list("pk", flat=True))
        if subscription.area_id:
            area_ids.add(subscription.area_id)
    area_ids.update(
        LocationArea.objects.filter(
            travel_safety_plans__subscription=subscription,
            travel_safety_plans__active=True,
            active=True,
        ).values_list("pk", flat=True)
    )
    return area_ids


def _remember_public_alert_subscription(request, response, subscription):
    response.set_signed_cookie(
        PUBLIC_ALERT_SUBSCRIPTION_COOKIE,
        subscription.endpoint_hash,
        max_age=PUBLIC_ALERT_SUBSCRIPTION_COOKIE_MAX_AGE,
        secure=request.is_secure(),
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


def public_alert_subscribe(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to subscribe to area alerts."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The subscription payload is invalid."}, status=400)
    area_values = payload.get("area_ids")
    if area_values is None:
        area_values = [payload.get("area_id")]
    try:
        area_ids = {int(value) for value in area_values if value not in (None, "")}
    except (TypeError, ValueError):
        area_ids = set()
    areas = list(LocationArea.objects.filter(pk__in=area_ids, active=True).order_by("name"))
    if len(areas) != len(area_ids):
        return JsonResponse({"error": "Choose only active Uganda districts."}, status=400)
    try:
        subscription = _upsert_public_alert_subscription(request, payload, areas)
    except ValueError as error:
        return JsonResponse({"error": str(error)}, status=400)
    response = JsonResponse({"ok": True, "area": areas[0].name, "areas": [area.name for area in _subscription_area_list(subscription)]})
    return _remember_public_alert_subscription(request, response, subscription)


def public_alert_preferences(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to read alert preferences."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The subscription payload is invalid."}, status=400)
    endpoint = str(payload.get("endpoint") or "").strip()
    subscription = PublicAlertSubscription.objects.filter(
        endpoint_hash=hashlib.sha256(endpoint.encode("utf-8")).hexdigest(),
        active=True,
    ).first() if endpoint.startswith("https://") else None
    if subscription is None:
        return JsonResponse({"areas": []})
    response = JsonResponse({"areas": [area.pk for area in _subscription_area_list(subscription)]})
    return _remember_public_alert_subscription(request, response, subscription)


def public_alert_remove_area(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to remove an alert district."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        area_id = int(payload.get("area_id"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The alert district is invalid."}, status=400)
    endpoint = str(payload.get("endpoint") or "").strip()
    subscription = PublicAlertSubscription.objects.filter(
        endpoint_hash=hashlib.sha256(endpoint.encode("utf-8")).hexdigest(),
        active=True,
    ).first() if endpoint.startswith("https://") else None
    if subscription is None:
        return JsonResponse({"error": "No active browser subscription was found."}, status=404)
    remaining = [area for area in _subscription_area_list(subscription) if area.pk != area_id]
    subscription.notification_areas.remove(area_id)
    if subscription.area_id == area_id:
        if remaining:
            subscription.area = remaining[0]
            subscription.save(update_fields=["area", "last_seen_at"])
        else:
            subscription.active = False
            subscription.save(update_fields=["active", "last_seen_at"])
    response = JsonResponse({"ok": True, "areas": [area.pk for area in remaining]})
    if subscription.active:
        return _remember_public_alert_subscription(request, response, subscription)
    response.delete_cookie(PUBLIC_ALERT_SUBSCRIPTION_COOKIE, path="/")
    return response


def subscriber_alerts(request: HttpRequest) -> HttpResponse:
    return render(request, "incidents/subscriber_alerts.html", {
        "districts": LocationArea.objects.filter(active=True),
        "webpush_public_key": settings.WEBPUSH_VAPID_PUBLIC_KEY,
    })


def public_alert_history(request: HttpRequest) -> HttpResponse:
    subscription = _public_alert_subscription_from_request(request)
    area_ids = _public_alert_area_ids(subscription)
    audience_filter = Q(is_national=True)
    if area_ids:
        audience_filter |= Q(area_id__in=area_ids)
    alerts = (
        AreaAlert.objects.filter(
            audience_filter,
            created_at__gte=timezone.now() - PUBLIC_ALERT_LIFETIME,
            delivery_status__in=("sent", "partial", "published"),
        )
        .select_related("area")
        .order_by("-created_at", "-pk")
    )
    return render(request, "incidents/public_alert_history.html", {
        "alerts": alerts,
        "has_alert_subscription": subscription is not None,
    })


def public_area_alert_detail(request: HttpRequest, alert_id: int) -> HttpResponse:
    alert = get_object_or_404(
        AreaAlert.objects.select_related("area"),
        pk=alert_id,
    )
    if alert.created_at < timezone.now() - PUBLIC_ALERT_LIFETIME:
        return redirect("public_alert_history")
    subscription = _public_alert_subscription_from_request(request)
    if not alert.is_national and alert.area_id not in _public_alert_area_ids(subscription):
        return redirect("public_alert_history")
    return render(request, "incidents/public_alert_detail.html", {"alert": alert})


def _travel_route_map_features(route_areas):
    """Attach ordered Uganda district boundary features to a travel corridor."""
    boundaries = boundary_features().get("features", [])
    features = []
    for area in route_areas:
        feature = next(
            (
                item for item in boundaries
                if item.get("properties", {}).get("name") == area.name
                or area_name_for_boundary(item.get("properties", {}).get("name"), [area.name]) == area.name
            ),
            None,
        )
        if feature is None:
            continue
        features.append({
            **feature,
            "properties": {**feature.get("properties", {}), "route_name": area.name},
        })
    return {"type": "FeatureCollection", "features": features}


def _geometry_center(geometry):
    points = []

    def collect(value):
        if isinstance(value, (list, tuple)) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            points.append((float(value[0]), float(value[1])))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                collect(item)

    collect((geometry or {}).get("coordinates", []))
    if not points:
        return None
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return (
        (min(latitudes) + max(latitudes)) / 2,
        (min(longitudes) + max(longitudes)) / 2,
    )


def _google_duration_seconds(value):
    try:
        return float(str(value or "").rstrip("s"))
    except (TypeError, ValueError):
        return 0.0


def _decode_google_polyline(encoded):
    points = []
    index = 0
    latitude = 0
    longitude = 0
    while index < len(encoded):
        values = []
        for _ in range(2):
            result = 0
            shift = 0
            while True:
                if index >= len(encoded):
                    return points
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            values.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += values[0]
        longitude += values[1]
        points.append([latitude / 100000, longitude / 100000])
    return points


def _google_traffic_route(origin_point, destination_point):
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", "")
    if not api_key or not origin_point or not destination_point:
        return None
    request_payload = {
        "origin": {"location": {"latLng": {"latitude": origin_point[0], "longitude": origin_point[1]}}},
        "destination": {"location": {"latLng": {"latitude": destination_point[0], "longitude": destination_point[1]}}},
        "travelMode": "DRIVE",
        "routingPreference": "TRAFFIC_AWARE_OPTIMAL",
        "computeAlternativeRoutes": False,
        "languageCode": "en-US",
        "units": "METRIC",
    }
    request = UrlRequest(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.distanceMeters,routes.duration,routes.staticDuration,routes.polyline.encodedPolyline",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        logger.warning("Google traffic route lookup failed: %s", error)
        return None
    route = (data.get("routes") or [None])[0]
    if not route:
        return None
    duration = _google_duration_seconds(route.get("duration"))
    static_duration = _google_duration_seconds(route.get("staticDuration"))
    traffic_delay = max(0, duration - static_duration) if static_duration else 0
    delay_ratio = traffic_delay / static_duration if static_duration else 0
    if traffic_delay <= 120 or delay_ratio < 0.1:
        traffic_level = "Light"
    elif traffic_delay <= 600 or delay_ratio < 0.25:
        traffic_level = "Moderate"
    else:
        traffic_level = "Heavy"
    encoded_polyline = (route.get("polyline") or {}).get("encodedPolyline", "")
    return {
        "provider": "Google",
        "distance_meters": route.get("distanceMeters"),
        "duration_seconds": duration,
        "static_duration_seconds": static_duration,
        "traffic_delay_seconds": traffic_delay,
        "traffic_level": traffic_level,
        "road_points": _decode_google_polyline(encoded_polyline),
        "updated_at": timezone.now().isoformat(),
    }


def travel_location_area(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to identify the current travel district."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        latitude = float(payload.get("latitude"))
        longitude = float(payload.get("longitude"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The current GPS coordinates are invalid."}, status=400)
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return JsonResponse({"error": "The current GPS coordinates are outside a valid range."}, status=400)
    boundary_name = boundary_name_for_point(latitude, longitude)
    available_names = list(LocationArea.objects.filter(active=True).values_list("name", flat=True))
    area_name = area_name_for_boundary(boundary_name, available_names)
    area = LocationArea.objects.filter(name=area_name, active=True).first() if area_name else None
    if area is None:
        return JsonResponse({"error": "Your GPS position is outside the supported Uganda districts. Choose the starting district manually."}, status=404)
    return JsonResponse({
        "ok": True,
        "area": {"id": area.pk, "name": area.name},
        "message": f"Starting district found: {area.name}. Choose your destination district to continue.",
    })


def travel_alert_plan(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to start a travel safety watch."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
        origin_id = int(payload.get("origin_area"))
        destination_id = int(payload.get("destination_area"))
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "Choose a starting district and destination district."}, status=400)
    areas = list(LocationArea.objects.filter(pk__in={origin_id, destination_id}, active=True))
    areas_by_id = {area.pk: area for area in areas}
    if len(areas) != 2 or origin_id == destination_id:
        return JsonResponse({"error": "Choose two different active Uganda districts."}, status=400)
    origin = areas_by_id[origin_id]
    destination = areas_by_id[destination_id]
    available_names = list(LocationArea.objects.filter(active=True).values_list("name", flat=True))
    route_names = route_area_names(origin.name, destination.name, available_names)
    route_areas = list(LocationArea.objects.filter(name__in=route_names, active=True))
    route_by_name = {area.name: area for area in route_areas}
    route_areas = [route_by_name[name] for name in route_names if name in route_by_name]
    if origin not in route_areas:
        route_areas.insert(0, origin)
    if destination not in route_areas:
        route_areas.append(destination)
    route_map = _travel_route_map_features(route_areas)
    route_features_by_name = {
        feature.get("properties", {}).get("route_name"): feature
        for feature in route_map.get("features", [])
    }
    origin_point = _geometry_center((route_features_by_name.get(origin.name) or {}).get("geometry"))
    destination_point = _geometry_center((route_features_by_name.get(destination.name) or {}).get("geometry"))
    try:
        gps_latitude = float(payload.get("start_latitude"))
        gps_longitude = float(payload.get("start_longitude"))
        if math.isfinite(gps_latitude) and math.isfinite(gps_longitude):
            origin_point = (gps_latitude, gps_longitude)
    except (TypeError, ValueError):
        pass
    google_traffic = _google_traffic_route(origin_point, destination_point)
    direct_area_values = payload.get("area_ids") or []
    try:
        direct_area_ids = {int(value) for value in direct_area_values if value not in (None, "")}
    except (TypeError, ValueError):
        direct_area_ids = set()
    direct_areas = list(LocationArea.objects.filter(pk__in=direct_area_ids, active=True))
    if len(direct_areas) != len(direct_area_ids):
        return JsonResponse({"error": "Choose only active Uganda districts."}, status=400)
    subscription = None
    endpoint = str(payload.get("endpoint") or "").strip()
    keys = payload.get("keys") or {}
    if endpoint or keys:
        try:
            subscription = _upsert_public_alert_subscription(
                request,
                payload,
                route_areas,
                save_direct_areas=bool(direct_area_ids),
                direct_areas=direct_areas,
            )
        except ValueError as error:
            return JsonResponse({"error": str(error)}, status=400)

    if subscription is not None:
        plan = TravelSafetyPlan.objects.filter(subscription=subscription, active=True).first()
        if plan is None:
            plan = TravelSafetyPlan.objects.create(
                subscription=subscription,
                client_uuid=subscription.client_uuid,
                origin_area=origin,
                destination_area=destination,
            )
        else:
            plan.origin_area = origin
            plan.destination_area = destination
            plan.client_uuid = subscription.client_uuid
            plan.save(update_fields=["origin_area", "destination_area", "client_uuid", "updated_at"])
        plan.route_areas.set(route_areas)
    return JsonResponse({
        "ok": True,
        "watch_active": subscription is not None,
        "plan_id": plan.pk if subscription is not None else None,
        "origin": origin.name,
        "destination": destination.name,
        "route": [area.name for area in route_areas],
        "route_map": route_map,
        "traffic_provider": "Google" if getattr(settings, "GOOGLE_MAPS_API_KEY", "") else "OSRM",
        "traffic_available": bool(google_traffic),
        "google_traffic": google_traffic,
        "message": (
            "Travel watch active. You will receive opted-in safety alerts for this district corridor."
            if subscription is not None
            else "Route calculated. Enable browser alerts to receive safety notices along this corridor."
        ),
    })


def travel_alert_stop(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to stop a travel safety watch."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The travel watch request is invalid."}, status=400)
    endpoint = str(payload.get("endpoint") or "").strip()
    subscription = PublicAlertSubscription.objects.filter(
        endpoint_hash=hashlib.sha256(endpoint.encode("utf-8")).hexdigest(),
        active=True,
    ).first() if endpoint.startswith("https://") else None
    if subscription is None:
        return JsonResponse({"error": "No active browser subscription was found."}, status=404)
    TravelSafetyPlan.objects.filter(subscription=subscription, active=True).update(active=False, updated_at=timezone.now())
    return JsonResponse({"ok": True})


def public_alert_unsubscribe(request: HttpRequest) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST to unsubscribe from area alerts."}, status=405)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({"error": "The subscription payload is invalid."}, status=400)
    endpoint = str(payload.get("endpoint", "")).strip()
    if not endpoint.startswith("https://"):
        return JsonResponse({"error": "The browser subscription is invalid."}, status=400)
    PublicAlertSubscription.objects.filter(
        endpoint_hash=hashlib.sha256(endpoint.encode("utf-8")).hexdigest(),
    ).update(active=False, last_seen_at=timezone.now())
    response = JsonResponse({"ok": True})
    response.delete_cookie(PUBLIC_ALERT_SUBSCRIPTION_COOKIE, path="/")
    return response


def submit_success(request: HttpRequest) -> HttpResponse:
    request_id = request.session.get("request_id")
    incident = None
    public_token = request.GET.get("access", "")
    if public_token:
        identity = public_chat_token_identity(public_token)
        incident_id = identity.get("incident_id") if identity else None
        if incident_id:
            incident = Incident.objects.select_related("request", "assigned_area", "assigned_admin").filter(
                pk=incident_id,
            ).first()
            if incident and public_chat_token_matches(public_token, incident):
                request_id = incident.request.request_id
                request.session["request_id"] = request_id
            else:
                incident = None
    if incident is None and request_id:
        incident = Incident.objects.select_related("request", "assigned_area", "assigned_admin").filter(
            request__request_id=request_id,
        ).first()
    if not request_id or incident is None:
        return redirect("home")
    if incident:
        _ensure_emergency_chat_room(incident)
    chat_room = _active_emergency_chat_room(incident) if incident else None
    case_request = incident.request if incident else None
    chat_unread_count = (
        chat_room.messages.filter(sender_type="admin", read_at__isnull=True).count()
        if chat_room else 0
    )
    tracking_available = bool(
        case_request
        and case_request.priority == "critical"
        and case_request.location_source == "gps"
        and case_request.client_uuid
        and case_request.latitude is not None
        and case_request.longitude is not None
        and incident.status in TRACKING_OPEN_STATUSES
    )
    return render(request, "incidents/success.html", {
        "request_id": request_id,
        "incident": incident,
        "chat_room": chat_room,
        "chat_unread_count": chat_unread_count,
        "public_chat_token": make_public_chat_token(incident) if chat_room else "",
        "tracking_available": tracking_available,
        "tracking_endpoint": reverse("emergency_location_tracking", args=[incident.pk]) if tracking_available else "",
        "tracking_auto_start": bool(tracking_available and case_request.tracking_enabled),
    })


def _tracking_case_is_eligible(incident):
    case_request = incident.request
    return bool(
        case_request.priority == "critical"
        and case_request.location_source == "gps"
        and case_request.client_uuid
        and case_request.latitude is not None
        and case_request.longitude is not None
        and incident.status in TRACKING_OPEN_STATUSES
    )


def _tracking_response(case_request):
    return {
        "ok": True,
        "active": case_request.tracking_active,
        "enabled": case_request.tracking_enabled,
        "last_location_at": case_request.last_location_at.isoformat() if case_request.last_location_at else None,
    }


def _location_trail(case_request):
    return [
        [float(latitude), float(longitude)]
        for latitude, longitude in case_request.location_pings.order_by("created_at", "pk").values_list("latitude", "longitude")
    ]


def _delete_incident_files(file_names):
    for file_name in set(file_names):
        if not file_name:
            continue
        if Recording.objects.filter(file=file_name).exists() or EmergencyChatMessage.objects.filter(audio=file_name).exists():
            continue
        try:
            default_storage.delete(file_name)
        except (OSError, ValueError):
            logger.warning("Could not delete incident media file %s", file_name, exc_info=True)


@transaction.atomic
def emergency_location_tracking(request: HttpRequest, incident_id: int) -> JsonResponse:
    if request.method != "POST":
        return JsonResponse({"error": "Use POST for location tracking actions."}, status=405)
    incident = Incident.objects.select_related("request").filter(pk=incident_id).first()
    if incident is None or request.session.get("request_id") != incident.request.request_id:
        return JsonResponse({"error": "This tracking session is not authorised."}, status=403)
    case_request = EmergencyRequest.objects.select_for_update().get(pk=incident.request_id)
    action = request.POST.get("action", "").strip().lower()
    now = timezone.now()

    if not _tracking_case_is_eligible(incident):
        return JsonResponse({"error": "Location tracking is available only for an active critical case with consent."}, status=403)

    if action == "start":
        if not case_request.tracking_enabled:
            return JsonResponse({"error": "Location sharing was stopped. Choose resume to start it again."}, status=409)
        if case_request.tracking_active and case_request.tracking_started_at:
            if now >= case_request.tracking_started_at + CRITICAL_TRACKING_WINDOW:
                case_request.tracking_active = False
                case_request.tracking_enabled = False
                case_request.tracking_stopped_at = now
                case_request.save(update_fields=["tracking_active", "tracking_enabled", "tracking_stopped_at"])
                return JsonResponse({"error": "This tracking session expired. Resume it if help is still needed."}, status=410)
            else:
                return JsonResponse(_tracking_response(case_request))
        if not case_request.tracking_active:
            case_request.tracking_active = True
            case_request.tracking_started_at = now
            case_request.tracking_stopped_at = None
            case_request.save(update_fields=["tracking_active", "tracking_started_at", "tracking_stopped_at", "tracking_enabled"])
        return JsonResponse(_tracking_response(case_request))

    if action == "resume":
        case_request.tracking_enabled = True
        case_request.tracking_active = True
        case_request.tracking_started_at = now
        case_request.tracking_stopped_at = None
        case_request.save(update_fields=["tracking_enabled", "tracking_active", "tracking_started_at", "tracking_stopped_at"])
        return JsonResponse(_tracking_response(case_request))

    if action == "stop":
        case_request.tracking_active = False
        case_request.tracking_enabled = False
        case_request.tracking_stopped_at = now
        case_request.save(update_fields=["tracking_active", "tracking_enabled", "tracking_stopped_at"])
        return JsonResponse(_tracking_response(case_request))

    if action != "ping":
        return JsonResponse({"error": "Unsupported tracking action."}, status=400)
    if not case_request.tracking_active or not case_request.tracking_enabled:
        return JsonResponse({"error": "Location tracking is not active."}, status=409)
    if case_request.tracking_started_at and now >= case_request.tracking_started_at + CRITICAL_TRACKING_WINDOW:
        case_request.tracking_active = False
        case_request.tracking_enabled = False
        case_request.tracking_stopped_at = now
        case_request.save(update_fields=["tracking_active", "tracking_enabled", "tracking_stopped_at"])
        return JsonResponse({"error": "This tracking session expired. Resume it if help is still needed."}, status=410)
    if _rate_limited(request, "public-emergency-location", limit=20, window=60):
        return JsonResponse({"error": "Location updates are arriving too quickly."}, status=429)

    latitude = _quick_coordinate(request.POST.get("latitude"), -90, 90, 6)
    longitude = _quick_coordinate(request.POST.get("longitude"), -180, 180, 6)
    accuracy = _quick_coordinate(request.POST.get("location_accuracy"), 0, 100000, 2)
    if latitude is None or longitude is None:
        return JsonResponse({"error": "A valid current location is required."}, status=400)
    ping_id = (request.headers.get("Idempotency-Key") or request.POST.get("ping_id") or uuid.uuid4().hex).strip()[:64]
    existing_ping = LocationPing.objects.filter(idempotency_key=ping_id).first()
    if existing_ping:
        if existing_ping.request_id != case_request.pk:
            return JsonResponse({"error": "This location update key is already in use."}, status=409)
        return JsonResponse(_tracking_response(case_request))
    LocationPing.objects.create(
        request=case_request,
        latitude=latitude,
        longitude=longitude,
        location_accuracy=accuracy,
        idempotency_key=ping_id,
    )
    case_request.latitude = latitude
    case_request.longitude = longitude
    case_request.location_accuracy = accuracy
    case_request.location_source = "gps"
    case_request.last_location_at = now
    case_request.save(update_fields=["latitude", "longitude", "location_accuracy", "location_source", "last_location_at"])
    return JsonResponse(_tracking_response(case_request))


def _ensure_emergency_chat_room(incident):
    expires_at = timezone.now() + timedelta(hours=48)
    try:
        with transaction.atomic():
            room = EmergencyChatRoom.objects.select_for_update().filter(incident=incident).first()
            if room and room.expires_at > timezone.now():
                return room
            if room:
                room.delete()
            return EmergencyChatRoom.objects.create(incident=incident, expires_at=expires_at)
    except IntegrityError:
        return EmergencyChatRoom.objects.get(incident=incident)


def _active_emergency_chat_room(incident):
    if incident is None:
        return None
    room = EmergencyChatRoom.objects.filter(incident=incident).first()
    if room and room.expires_at <= timezone.now():
        room.delete()
        return None
    return room


def _activate_emergency_chat_room(room):
    if room is None:
        return room
    if room.accepted_at is None:
        activated_at = timezone.now()
        updated = EmergencyChatRoom.objects.filter(
            pk=room.pk,
            accepted_at__isnull=True,
        ).update(accepted_at=activated_at, updated_at=activated_at)
        if updated:
            room.accepted_at = activated_at
            room.updated_at = activated_at
        else:
            room.refresh_from_db(fields=["accepted_at", "updated_at"])
    _seed_emergency_chat_messages(room)
    return room


def _seed_emergency_chat_messages(room):
    incident = room.incident
    case_request = incident.request
    if case_request.latitude is not None and case_request.longitude is not None:
        follow_up = (
            "Please reply with what is happening now, whether you are safe, "
            "and any nearby landmark that will help the response team find you."
        )
    else:
        follow_up = (
            "We do not have a confirmed GPS position yet. Please reply with what is happening now, "
            "your district or nearby landmark, whether you are safe, and the best way to reach you."
        )
    messages = (
        (
            f"emergency-system-greeting-{room.pk}",
            "Hello. You are now connected to Rapid Response. A responder has been notified and will review your emergency report.",
        ),
        (f"emergency-system-follow-up-{room.pk}", follow_up),
    )
    for idempotency_key, body in messages:
        EmergencyChatMessage.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults={
                "room": room,
                "sender_type": "system",
                "channel": "system",
                "body": body,
            },
        )


def _can_access_emergency_chat(request, incident):
    public_token = request.GET.get("access") or request.POST.get("access")
    if (
        request.session.get("request_id") == incident.request.request_id
        and not request.user.is_authenticated
    ) or public_chat_token_matches(public_token, incident):
        return True, "public"
    if not request.user.is_authenticated or not _can_access_dashboard(request.user):
        return False, None
    if request.session.get("operations_center_access") or request.user.is_superuser:
        return True, "admin"
    if _token_referral_access(request, incident.pk):
        return True, "admin"
    recipient = _emergency_chat_recipient(incident)
    if request.user.id in {incident.assigned_admin_id, recipient.id if recipient else None}:
        return True, "admin"
    return False, None


def _emergency_chat_recipient(incident):
    referral = incident.referrals.filter(
        channel="in_app",
        recipient_admin__isnull=False,
        archived_at__isnull=True,
    ).select_related("recipient_admin").order_by("-created_at").first()
    if referral:
        return referral.recipient_admin
    return incident.assigned_admin or _district_admin(incident.assigned_area)


def _case_chat_participants(request, referral):
    token_referral = _token_referral_access(request, referral.incident_id)
    is_sender = referral.referred_by_id == request.user.pk and _can_access_dashboard(request.user)
    is_token_recipient = token_referral is not None and token_referral.pk == referral.pk
    is_recipient = (
        referral.recipient_admin_id == request.user.pk and (
            _can_access_dashboard(request.user) or _can_access_institution(request.user)
        )
    ) or (is_token_recipient and _can_access_dashboard(request.user))
    if not is_sender and not is_recipient:
        return None
    return is_sender, is_recipient


def _emergency_chat_json(room, request, sender_type):
    incoming_type = "admin" if sender_type == "public" else "public"
    if request.GET.get("open") == "1":
        room.messages.filter(sender_type=incoming_type, read_at__isnull=True).update(read_at=timezone.now())
    messages_for_room = room.messages.select_related("sender").all()
    return {
        "accepted": room.accepted_at is not None,
        "expires_at": timezone.localtime(room.expires_at).isoformat(),
        "messages": [
            {
                "id": item.pk,
                "body": item.body,
                "channel": item.channel,
                "sender_type": item.sender_type,
                "audio_url": (
                    f"{reverse('emergency_chat_audio', args=[item.pk])}"
                    f"?access={quote_plus(request.GET.get('access', ''))}"
                    if item.audio and request.GET.get("access")
                    else reverse("emergency_chat_audio", args=[item.pk]) if item.audio else ""
                ),
                "attachment_url": (
                    f"{reverse('emergency_chat_file', args=[item.pk])}"
                    f"?access={quote_plus(request.GET.get('access', ''))}"
                    if item.attachment and request.GET.get("access")
                    else reverse("emergency_chat_file", args=[item.pk]) if item.attachment else ""
                ),
                "attachment_name": item.attachment_name,
                "attachment_size": item.attachment_size,
                "audio_duration": item.audio_duration_seconds,
                "mine": item.sender_type == sender_type,
                "sender": "You" if item.sender_type == sender_type else ("Rapid Response" if item.sender_type == "system" else "Response team" if item.sender_type == "admin" else "Request sender"),
                "created_at": timezone.localtime(item.created_at).strftime("%d %b %Y · %H:%M"),
            }
            for item in messages_for_room
        ],
        "unread": room.messages.filter(sender_type=incoming_type, read_at__isnull=True).count(),
        "calls": [
            {
                "id": call.pk,
                "status": call.status,
                "mine": call.requester_type == sender_type,
                "on_hold": call.on_hold,
                "caller_muted": call.caller_muted,
                "recipient_muted": call.recipient_muted,
                "started_at": timezone.localtime(call.started_at).isoformat() if call.started_at else "",
                "created_at": timezone.localtime(call.created_at).strftime("%d %b %Y · %H:%M"),
            }
            for call in room.calls.all()[:5]
        ],
    }


def emergency_chat_page(request: HttpRequest, incident_id: int) -> HttpResponse:
    incident = get_object_or_404(
        Incident.objects.select_related("request", "assigned_area", "assigned_admin"),
        pk=incident_id,
    )
    allowed, sender_type = _can_access_emergency_chat(request, incident)
    if not allowed:
        return render(request, "incidents/emergency_chat.html", {
            "error": "You are not authorised to access this emergency chat.",
            "incident": incident,
        }, status=403)
    room = _active_emergency_chat_room(incident)
    if room is None:
        room = _ensure_emergency_chat_room(incident)
    if sender_type == "public":
        _activate_emergency_chat_room(room)
    return render(request, "incidents/emergency_chat.html", {
        "incident": incident,
        "chat_room": room,
        "chat_role": sender_type,
        "websocket_token": websocket_access_token(request, "emergency", [incident.pk], sender_type),
        "public_chat_token": make_public_chat_token(incident) if sender_type == "public" else "",
        "back_url": reverse("submit_success") if sender_type == "public" else reverse("dashboard_incident", args=[incident.pk]),
    })


def emergency_chat(request: HttpRequest, incident_id: int) -> HttpResponse:
    incident = get_object_or_404(
        Incident.objects.select_related("request", "assigned_area", "assigned_admin"),
        pk=incident_id,
    )
    allowed, sender_type = _can_access_emergency_chat(request, incident)
    if not allowed:
        return JsonResponse({"error": "You are not authorised to access this emergency chat."}, status=403)
    room = _active_emergency_chat_room(incident)
    if room is None:
        room = _ensure_emergency_chat_room(incident)
    if request.method == "POST":
        if _rate_limited(request, f"emergency-chat:{room.pk}", limit=120, window=60):
            return JsonResponse({"error": "Too many chat actions. Please wait a moment and try again."}, status=429)
        action = request.POST.get("action", "message")
        if action == "accept":
            if sender_type != "public":
                return JsonResponse({"error": "Only the request sender can accept this chat."}, status=403)
            _activate_emergency_chat_room(room)
        elif action == "message":
            if room.accepted_at is None:
                return JsonResponse({"error": "Accept the chat invitation before sending a message."}, status=409)
            body = request.POST.get("body", "").strip()
            audio = request.FILES.get("audio")
            attachment = request.FILES.get("file")
            if audio and attachment:
                return JsonResponse({"error": "Send an audio note or a file, not both at once."}, status=400)
            if not body and not audio and not attachment:
                return JsonResponse({"error": "Write a message, record an audio note, or attach a file."}, status=400)
            if audio and (not _is_allowed_upload(audio, ALLOWED_AUDIO_TYPES, ALLOWED_AUDIO_EXTENSIONS) or audio.size > MAX_AUDIO_UPLOAD_BYTES):
                return JsonResponse({"error": "Audio notes must be valid audio files smaller than 10 MB."}, status=400)
            if attachment and not _is_allowed_chat_file(attachment):
                return JsonResponse({"error": "This file type is not allowed or the file is larger than 20 MB."}, status=400)
            try:
                duration = int(request.POST.get("audio_duration", "0")) or None
            except (TypeError, ValueError):
                duration = None
            idempotency_key = request.POST.get("idempotency_key", "").strip()[:64] or None
            if idempotency_key:
                existing_message = EmergencyChatMessage.objects.filter(idempotency_key=idempotency_key).first()
                if existing_message and existing_message.room_id != room.pk:
                    return JsonResponse({"error": "This message key has already been used."}, status=409)
            else:
                existing_message = None
            if existing_message is None:
                attachment_fields = _chat_file_fields(attachment) if attachment else {}
                EmergencyChatMessage.objects.create(
                    room=room,
                    sender=request.user if sender_type == "admin" else None,
                    sender_type=sender_type,
                    channel="file" if attachment else "audio" if audio else "text",
                    idempotency_key=idempotency_key,
                    body=body[:4000],
                    audio=audio,
                    audio_duration_seconds=min(duration, 120) if duration else None,
                    **attachment_fields,
                )
        elif action == "call":
            if room.accepted_at is None:
                return JsonResponse({"error": "Accept the chat invitation before requesting a call."}, status=409)
            recipient = _emergency_chat_recipient(incident) if sender_type == "public" else None
            with transaction.atomic():
                locked_room = EmergencyChatRoom.objects.select_for_update().get(pk=room.pk)
                if not locked_room.calls.filter(status__in=["requested", "accepted"]).exists():
                    EmergencyChatCall.objects.create(
                        room=locked_room,
                        requested_by=request.user if sender_type == "admin" else None,
                        recipient=recipient,
                        requester_type=sender_type,
                    )
        elif action == "call_response":
            status = request.POST.get("status")
            if status not in {"accepted", "declined", "ended"}:
                return JsonResponse({"error": "Invalid call response."}, status=400)
            call = get_object_or_404(EmergencyChatCall, pk=request.POST.get("call_id"), room=room)
            if sender_type == "admin" and call.recipient_id not in {None, request.user.id}:
                return JsonResponse({"error": "This call is routed to another responder."}, status=403)
            if status in {"accepted", "declined"} and sender_type == "admin" and call.requester_type == "admin" and call.requested_by_id == request.user.id:
                return JsonResponse({"error": "The receiving participant must answer this call."}, status=403)
            if status in {"accepted", "declined"} and sender_type == "public" and call.requester_type != "admin":
                return JsonResponse({"error": "The responder must answer this call."}, status=403)
            call.status = status
            call.responded_at = timezone.now()
            update_fields = ["status", "responded_at"]
            if status == "accepted" and call.started_at is None:
                call.started_at = timezone.now()
                update_fields.append("started_at")
            call.save(update_fields=update_fields)
        elif action == "call_control":
            call = get_object_or_404(EmergencyChatCall, pk=request.POST.get("call_id"), room=room)
            if call.status != "accepted":
                return JsonResponse({"error": "Call controls are available after the call is accepted."}, status=409)
            if sender_type == "admin":
                is_participant = (
                    call.recipient_id == request.user.id
                    or (call.requester_type == "admin" and call.requested_by_id == request.user.id)
                )
                if not is_participant:
                    return JsonResponse({"error": "These call controls are assigned to another responder."}, status=403)
            control = request.POST.get("control")
            if control in {"hold", "resume"}:
                call.on_hold = control == "hold"
                call.save(update_fields=["on_hold"])
            elif control in {"mute", "unmute"}:
                muted = control == "mute"
                if sender_type == call.requester_type:
                    call.caller_muted = muted
                    update_fields = ["caller_muted"]
                else:
                    call.recipient_muted = muted
                    update_fields = ["recipient_muted"]
                call.save(update_fields=update_fields)
            else:
                return JsonResponse({"error": "Unsupported call control."}, status=400)
        else:
            return JsonResponse({"error": "Unsupported chat action."}, status=400)
        broadcast_emergency_chat_update(incident.pk)
    return JsonResponse(_emergency_chat_json(room, request, sender_type))


def _quick_help_success_response(request):
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"success": True, "redirect_url": reverse("submit_success")})
    return redirect("submit_success")


@transaction.atomic
def quick_help(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        if _rate_limited(request, "quick-emergency-submit", limit=10, window=60):
            return render(request, "incidents/quick_help.html", {
                "error": "Too many requests. Please wait a minute before trying again.",
            }, status=429)
        video = request.FILES.get("video")
        duration = request.POST.get("recording_duration")
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = 0
        if not video or not _is_allowed_upload(video, ALLOWED_VIDEO_TYPES, ALLOWED_VIDEO_EXTENSIONS) or video.size > MAX_VIDEO_UPLOAD_BYTES or not 1 <= duration <= 20:
            return render(request, "incidents/quick_help.html", {
                "error": "Please record a video between 1 and 20 seconds before sending.",
            }, status=400)

        latitude = _quick_coordinate(request.POST.get("latitude"), -90, 90, 6)
        longitude = _quick_coordinate(request.POST.get("longitude"), -180, 180, 6)
        accuracy = _quick_coordinate(request.POST.get("location_accuracy"), 0, 100000, 2)
        location_source = request.POST.get("location_source", "user").strip().lower()
        if location_source not in {"gps", "cached", "user", "network"} or latitude is None or longitude is None:
            location_source = "user"
        client_uuid = _parse_client_uuid(request.POST.get("client_uuid"))
        idempotency_key = request.POST.get("idempotency_key", "").strip() or uuid.uuid4().hex
        existing_request = EmergencyRequest.objects.filter(idempotency_key=idempotency_key).first()
        if existing_request:
            request.session["request_id"] = existing_request.request_id
            return _quick_help_success_response(request)
        device = detect_device(request.META.get("HTTP_USER_AGENT", ""))
        try:
            with transaction.atomic():
                resolved_area = _resolve_area_from_coordinates(latitude, longitude)
                emergency_request = EmergencyRequest.objects.create(
                    idempotency_key=idempotency_key,
                    phone_number=request.POST.get("phone_number", ""),
                    latitude=latitude,
                    longitude=longitude,
                    location_accuracy=accuracy,
                    location_source=location_source,
                    client_uuid=client_uuid,
                    area=resolved_area,
                    emergency_type="danger",
                    priority="critical",
                    message="Quick video-help request.",
                    tracking_enabled=bool(location_source == "gps" and client_uuid and latitude is not None and longitude is not None),
                    ip_address=request.META.get("REMOTE_ADDR"),
                    device_type=device["device_type"],
                    operating_system=device["operating_system"],
                    browser=device["browser"],
                )
                similar_incident, similarity_signal = _find_similar_incident(emergency_request)
                incident = Incident.objects.create(
                    request=emergency_request,
                    assigned_area=emergency_request.area,
                    assigned_admin=_district_admin(emergency_request.area),
                    similar_to=similar_incident,
                    similarity_signal=similarity_signal,
                    similarity_checked_at=timezone.now(),
                )
                _ensure_emergency_chat_room(incident)
                Recording.objects.create(incident=incident, file=video, duration_seconds=duration)
        except IntegrityError:
            existing_request = EmergencyRequest.objects.filter(idempotency_key=idempotency_key).first()
            if existing_request:
                request.session["request_id"] = existing_request.request_id
                return _quick_help_success_response(request)
            raise
        request.session["request_id"] = emergency_request.request_id
        return _quick_help_success_response(request)
    return render(request, "incidents/quick_help.html", {"idempotency_key": uuid.uuid4().hex})


def _quick_coordinate(value, minimum, maximum, decimal_places):
    if not value:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number < Decimal(str(minimum)) or number > Decimal(str(maximum)):
        return None
    return number.quantize(Decimal("1").scaleb(-decimal_places))


def _parse_client_uuid(value):
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _find_similar_incident(case_request):
    if not case_request.client_uuid:
        return None, ""
    previous_incident = Incident.objects.select_related("request").filter(
        request__client_uuid=case_request.client_uuid,
    ).order_by("-request__created_at", "-pk").first()
    if previous_incident is None:
        return None, ""
    return previous_incident, "client_uuid"


_UGANDA_DISTRICT_COORDINATES = {
    "Arua": (3.0200, 30.9200),
    "Fort Portal City": (0.6714, 30.2808),
    "Gulu": (2.7746, 32.2984),
    "Hoima": (1.4356, 31.3436),
    "Jinja": (0.4476, 33.2032),
    "Kampala": (0.3476, 32.5825),
    "Kamuli": (0.9479, 33.1229),
    "Kawempe": (0.3550, 32.5460),
    "Lira": (2.2499, 32.9091),
    "Masaka": (-0.3128, 31.7135),
    "Mbale": (1.0833, 34.1750),
    "Mbarara": (-0.6072, 30.6548),
    "Mityana": (0.4135, 32.0410),
    "Mukono": (0.3536, 32.7543),
    "Nebbi": (2.4781, 31.0947),
    "Soroti": (1.7145, 33.6118),
    "Wakiso": (0.4048, 32.4795),
}


def _distance_km(lat1, lon1, lat2, lon2):
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    return 2 * radius_km * math.asin(math.sqrt(a))


def _resolve_area_from_coordinates(latitude, longitude, fallback_area=None):
    if latitude is None or longitude is None:
        return fallback_area
    boundary_name = boundary_name_for_point(latitude, longitude)
    available_names = LocationArea.objects.filter(active=True).values_list("name", flat=True)
    area_name = area_name_for_boundary(boundary_name, available_names)
    if area_name:
        return LocationArea.objects.filter(name=area_name, active=True).first() or fallback_area
    return fallback_area


def dashboard_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated and _can_access_dashboard(request.user):
        return redirect("dashboard_home")
    reason = request.GET.get("reason")
    error = None
    if reason == "inactive":
        error = "Your account is inactive or has not been approved for the responder dashboard."
    elif reason == "inactivity":
        error = "You were signed out after five minutes without activity."
    if request.method == "POST":
        username = request.POST.get("username", "")
        password = request.POST.get("password", "")
        if _rate_limited(request, f"dashboard-login:{username.casefold()}", limit=10, window=300):
            record_security_event(request, "login_throttled", details={"surface": "dashboard"})
            error = "Too many sign-in attempts. Please wait five minutes and try again."
            return render(request, "dashboard/login.html", {"error": error}, status=429)
        district_id = request.POST.get("district", "")
        hospital_id = request.POST.get("hospital", "")
        hospital_profile = InstitutionProfile.objects.filter(
            institution_type="hospital",
            area_id=district_id,
            hospital_facility_id=hospital_id,
            active=True,
            user__is_active=True,
        ).select_related("user").first() if district_id and hospital_id else None
        login_username = hospital_profile.user.username if hospital_profile else username
        user = authenticate(request, username=login_username, password=password)
        if user is not None and _can_access_dashboard(user):
            if _mfa_required_for(user):
                return _mfa_begin(request, user, "dashboard")
            login(request, user)
            record_security_event(request, "login_success", user=user, details={"surface": "dashboard"})
            return redirect("dashboard_home")
        record_security_event(request, "login_failure", details={"surface": "dashboard"})
        error = "The username or password is incorrect, or your account is inactive or has not been approved for the responder dashboard."
    return render(request, "dashboard/login.html", {"error": error})


@login_required
def admin_section_gate(request: HttpRequest) -> HttpResponse:
    if not request.user.is_superuser:
        return HttpResponseForbidden("Main administration is restricted to the parent administrator.")
    next_path = request.POST.get("next") or request.GET.get("next") or "/admin/"
    if not next_path.startswith("/admin/") or next_path.startswith("//"):
        next_path = "/admin/"
    if request.method == "POST":
        if _rate_limited(request, "admin-section-gate", limit=5, window=300):
            record_security_event(request, "login_throttled", user=request.user, details={"surface": "admin_gate"})
            return render(request, "dashboard/admin_gate.html", {
                "error": "Too many attempts. Please wait five minutes and try again.",
                "next_path": next_path,
            }, status=429)
        if check_password(request.POST.get("password", ""), settings.ADMIN_SECTION_PASSWORD_HASH):
            request.session["admin_section_unlocked_at"] = int(timezone.now().timestamp())
            record_security_event(request, "login_success", user=request.user, details={"surface": "admin_gate"})
            return redirect(next_path)
        record_security_event(request, "access_denied", user=request.user, details={"surface": "admin_gate"})
        error = "The administration password is incorrect."
    else:
        error = None
    return render(request, "dashboard/admin_gate.html", {"error": error, "next_path": next_path})


def _dashboard_inactive_redirect(request):
    if request.user.is_authenticated:
        record_security_event(request, "session_expired", user=request.user, details={"surface": "dashboard"})
        logout(request)
    return redirect(f"{reverse('dashboard_login')}?reason=inactive")


@login_required
def dashboard_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("dashboard_login")


def workspace_keepalive(request: HttpRequest) -> JsonResponse:
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"error": "Your workspace session is no longer active."}, status=401)
    return JsonResponse({"ok": True})


def _can_access_dashboard(user):
    if not user.is_active:
        return False
    if user.is_superuser:
        return True
    try:
        profile = user.response_profile
    except AttributeError:
        return False
    return profile.active


def _is_parent_admin(user):
    return user.is_superuser and not hasattr(user, "response_profile")


def _visible_incidents(user):
    queryset = Incident.objects.select_related(
        "request", "assigned_area", "assigned_admin", "similar_to", "similar_to__request"
    ).prefetch_related("recordings")
    if _is_parent_admin(user):
        return queryset
    assigned_areas = user.response_profile.areas.filter(active=True)
    return queryset.filter(
        Q(assigned_area__in=assigned_areas)
        | Q(referrals__recipient_admin=user)
    ).distinct().order_by("-request__created_at", "-pk")


def dashboard_activity_ping(request: HttpRequest) -> JsonResponse:
    """Return small dashboard counters without re-rendering the current page."""
    if not request.user.is_authenticated or not _can_access_dashboard(request.user):
        return JsonResponse(
            {"error": "The responder session is no longer active."},
            status=401,
        )

    incoming = _visible_incidents(request.user).filter(
        status="new",
        opened_at__isnull=True,
    ).select_related("request", "assigned_area").order_by("-request__created_at", "-pk")
    latest_case = incoming.first()

    active_referrals = Referral.objects.filter(
        recipient_admin=request.user,
        archived_at__isnull=True,
    ).select_related("incident__request", "incident__assigned_area").order_by("-created_at", "-pk")
    unread_referrals = active_referrals.filter(read_at__isnull=True)
    latest_referral = active_referrals.first()

    latest_inhouse_message = InHouseMessage.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
    ).order_by("-created_at", "-pk").first()
    latest_case_message = CaseMessage.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
        referral__archived_at__isnull=True,
    ).order_by("-created_at", "-pk").first()
    latest_message = max(
        [item for item in (latest_inhouse_message, latest_case_message) if item is not None],
        key=lambda item: (item.created_at, item.pk),
        default=None,
    )

    return JsonResponse({
        "server_time": timezone.now().isoformat(),
        "incoming": {
            "count": incoming.count(),
            "latest_id": latest_case.pk if latest_case else None,
            "latest_reference": latest_case.request.request_id if latest_case else "",
            "latest_area": latest_case.assigned_area.name if latest_case and latest_case.assigned_area else "Unassigned",
            "latest_priority": latest_case.request.priority if latest_case else "",
        },
        "referrals": {
            "unread": unread_referrals.count(),
            "active": active_referrals.count(),
            "latest_id": latest_referral.pk if latest_referral else None,
        },
        "messages": {
            "unread": (
                InHouseMessage.objects.filter(recipient=request.user, read_at__isnull=True).count()
                + CaseMessage.objects.filter(
                    recipient=request.user,
                    read_at__isnull=True,
                    referral__archived_at__isnull=True,
                ).count()
            ),
            "latest_id": f"{latest_message.__class__.__name__}:{latest_message.pk}" if latest_message else "",
        },
    })


def _inhouse_area_code(area):
    if area is None:
        return "non"
    if area.routing_code:
        raw_code = re.sub(r"[^A-Za-z]", "", area.routing_code)
        if len(raw_code) >= 4:
            return (raw_code[0] + raw_code[-2:]).lower()
        if raw_code:
            return raw_code[:3].lower()
    name = re.sub(r"\s+(district|city)$", "", area.name, flags=re.IGNORECASE)
    consonants = re.sub(r"[^A-Za-z]", "", name).upper()
    consonants = "".join(letter for letter in consonants if letter not in "AEIOU")
    if len(consonants) >= 3:
        return (consonants[0] + consonants[-2:]).lower()
    letters = re.sub(r"[^A-Za-z]", "", name).lower()
    return (letters[:3] or "non").ljust(3, "x")


def _inhouse_admin_code(profile):
    if profile is None:
        return "hq"
    areas = profile.areas.filter(active=True).order_by("name")
    codes = [_inhouse_area_code(area) for area in areas]
    return " · ".join(dict.fromkeys(codes)) or "non"


def institution_login(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated and _can_access_institution(request.user):
        return redirect("institution_portal")
    error = "You were signed out after five minutes without activity." if request.GET.get("reason") == "inactivity" else None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if _rate_limited(request, f"institution-login:{username.casefold()}", limit=10, window=300):
            record_security_event(request, "login_throttled", details={"surface": "institution"})
            return render(request, "institution/login.html", {
                "error": "Too many sign-in attempts. Please wait five minutes and try again.",
                "districts": LocationArea.objects.filter(active=True),
            }, status=429)
        institution_type = request.POST.get("institution_type", "hospital")
        district_id = request.POST.get("district", "")
        hospital_id = request.POST.get("hospital", "")
        selected_profile = None
        if district_id and institution_type == "hospital" and hospital_id:
            selected_profile = InstitutionProfile.objects.filter(
                institution_type="hospital",
                area_id=district_id,
                hospital_facility_id=hospital_id,
                active=True,
                user__is_active=True,
            ).select_related("user").first()
        elif district_id and institution_type == "police":
            selected_profile = InstitutionProfile.objects.filter(
                institution_type="police",
                area_id=district_id,
                active=True,
                user__is_active=True,
            ).select_related("user").first()
        if selected_profile:
            login_username = selected_profile.user.username
        elif district_id:
            login_username = ""
        else:
            legacy_user = get_user_model().objects.filter(
                username__iexact=username,
                is_active=True,
                institution_profile__active=True,
            ).first()
            login_username = legacy_user.username if legacy_user else username
        user = authenticate(request, username=login_username, password=password)
        if user is not None and _can_access_institution(user):
            if _mfa_required_for(user):
                return _mfa_begin(request, user, "institution")
            login(request, user)
            record_security_event(request, "login_success", user=user, details={"surface": "institution"})
            return redirect("institution_portal")
        record_security_event(request, "login_failure", details={"surface": "institution"})
        error = "The username or passcode is incorrect, or this institution account is inactive."
    return render(request, "institution/login.html", {
        "error": error,
        "districts": LocationArea.objects.filter(active=True),
    })


def institution_hospital_directory(request: HttpRequest) -> HttpResponse:
    if _rate_limited(request, "hospital-directory", limit=120, window=60):
        return JsonResponse({"error": "Too many directory requests. Please try again shortly."}, status=429)
    district_id = request.GET.get("district")
    query = request.GET.get("q", "").strip()
    hospitals = HospitalFacility.objects.filter(active=True)
    if district_id:
        hospitals = hospitals.filter(district_id__in=matching_area_ids(district_id))
    if query:
        hospitals = hospitals.filter(name__icontains=query)
    return JsonResponse({
        "results": [
            {
                "value": hospital.pk,
                "label": hospital.name,
                "ownership": hospital.get_ownership_display(),
                "level": hospital.level,
            }
            for hospital in hospitals.order_by("ownership", "name")[:100]
        ]
    })


def case_chat_feed(request: HttpRequest, referral_id: int) -> HttpResponse:
    if not request.user.is_authenticated:
        return JsonResponse({"error": "Authentication required."}, status=401)
    referral = get_object_or_404(
        Referral.objects.select_related("referred_by", "recipient_admin"),
        pk=referral_id,
    )
    if referral.channel != "in_app":
        return JsonResponse({"error": "This referral does not have an in-house chat channel."}, status=409)
    participants = _case_chat_participants(request, referral)
    if participants is None:
        return JsonResponse({"error": "You are not a participant in this case chat."}, status=403)
    is_sender, is_recipient = participants
    if request.method == "POST":
        if _rate_limited(request, f"referral-chat:{referral.pk}", limit=120, window=60):
            return JsonResponse({"error": "Too many chat messages. Please wait a moment and try again."}, status=429)
        body = request.POST.get("body", "").strip()
        attachment = request.FILES.get("file")
        if not body and not attachment:
            return JsonResponse({"error": "Write a message or attach a file."}, status=400)
        if attachment and not _is_allowed_chat_file(attachment):
            return JsonResponse({"error": "This file type is not allowed or the file is larger than 20 MB."}, status=400)
        recipient = referral.recipient_admin if is_sender else referral.referred_by
        if recipient is None:
            return JsonResponse({"error": "This referral has no chat recipient."}, status=409)
        attachment_fingerprint = f"{attachment.name}:{attachment.size}" if attachment else ""
        message_key = _write_idempotency_key(request, "case-message", referral.pk, body, attachment_fingerprint)
        attachment_fields = _chat_file_fields(attachment) if attachment else {}
        CaseMessage.objects.get_or_create(
            idempotency_key=message_key,
            defaults={
                "referral": referral,
                "incident": referral.incident,
                "sender": request.user,
                "recipient": recipient,
                "body": body[:4000],
                **attachment_fields,
            },
        )
        broadcast_case_chat_update(referral.pk)
    if request.GET.get("open") == "1":
        CaseMessage.objects.filter(
            referral=referral,
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
    messages_for_case = referral.messages.select_related("sender").all()
    return JsonResponse({
        "messages": [
            {
                "id": item.pk,
                "body": item.body,
                "attachment_url": reverse("case_chat_file", args=[item.pk]) if item.attachment else "",
                "attachment_name": item.attachment_name,
                "attachment_size": item.attachment_size,
                "mine": item.sender_id == request.user.pk,
                "sender": "You" if item.sender_id == request.user.pk else item.sender.get_username(),
                "created_at": timezone.localtime(item.created_at).strftime("%d %b %Y · %H:%M"),
            }
            for item in messages_for_case
        ],
        "unread": referral.messages.filter(recipient=request.user, read_at__isnull=True).count(),
    })


@login_required
def case_chat_file(request: HttpRequest, message_id: int) -> HttpResponse:
    message = CaseMessage.objects.select_related("referral").filter(pk=message_id).first()
    if message is None or not message.attachment:
        return HttpResponse(status=404)
    if _case_chat_participants(request, message.referral) is None:
        return HttpResponseForbidden("Case chat access is required.")
    filename = Path(message.attachment_name or message.attachment.name).name.replace('"', "")
    try:
        file_handle = message.attachment.open("rb")
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(
        file_handle,
        content_type=message.attachment_content_type or mimetypes.guess_type(message.attachment.name)[0] or "application/octet-stream",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required(login_url="/institution/login/")
def institution_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("institution_login")


@login_required(login_url="/institution/login/")
def institution_portal(request: HttpRequest) -> HttpResponse:
    if not _can_access_institution(request.user):
        return redirect("institution_login")
    profile = request.user.institution_profile
    password_error = None
    if request.method == "POST" and request.POST.get("action") == "change_password":
        new_password = request.POST.get("new_password", "")
        confirmation = request.POST.get("new_password_confirmation", "")
        if len(new_password) < 8:
            password_error = "Your new passcode must contain at least eight characters."
        elif new_password != confirmation:
            password_error = "The new passcode and confirmation do not match."
        else:
            request.user.set_password(new_password)
            request.user.save(update_fields=["password"])
            profile.force_password_change = False
            profile.save(update_fields=["force_password_change"])
            login(request, request.user)
            messages.success(request, "Your institution passcode was updated.")
            return redirect("institution_portal")
    if request.method == "POST":
        if request.POST.get("action") == "change_password":
            return render(request, "institution/portal.html", {
                "profile": profile,
                "referrals": [],
                "tab": "forwarded",
                "password_error": password_error,
                "force_password_change": True,
                "counts": {"forwarded": 0, "new": 0, "archive": 0},
            })
        referral = get_object_or_404(Referral, pk=request.POST.get("referral"), recipient_admin=request.user)
        action = request.POST.get("action")
        if action == "archive":
            referral.archived_at = timezone.now()
            referral.read_at = referral.read_at or timezone.now()
            referral.save(update_fields=["archived_at", "read_at"])
        elif action == "restore":
            referral.archived_at = None
            referral.save(update_fields=["archived_at"])
        elif action == "read":
            referral.read_at = timezone.now()
            referral.save(update_fields=["read_at"])
        return redirect(f"{reverse('institution_portal')}?tab={request.POST.get('tab', 'forwarded')}")
    tab = request.GET.get("tab", "forwarded")
    if tab not in {"forwarded", "new", "archive"}:
        tab = "forwarded"
    referrals = Referral.objects.filter(recipient_admin=request.user).select_related(
        "incident__request", "incident__assigned_area", "referred_by"
    )
    if tab == "new":
        referrals = referrals.filter(read_at__isnull=True, archived_at__isnull=True)
    elif tab == "archive":
        referrals = referrals.filter(archived_at__isnull=False)
    else:
        referrals = referrals.filter(archived_at__isnull=True)
    all_referrals = Referral.objects.filter(recipient_admin=request.user)
    return render(request, "institution/portal.html", {
        "profile": profile,
        "referrals": referrals,
        "tab": tab,
        "password_error": password_error,
        "force_password_change": profile.force_password_change,
        "counts": {
            "forwarded": all_referrals.filter(archived_at__isnull=True).count(),
            "new": all_referrals.filter(read_at__isnull=True, archived_at__isnull=True).count(),
            "archive": all_referrals.filter(archived_at__isnull=False).count(),
        },
    })


@login_required(login_url="/institution/login/")
def institution_case(request: HttpRequest, referral_id: int) -> HttpResponse:
    if not _can_access_institution(request.user):
        return redirect("institution_login")
    if request.user.institution_profile.force_password_change:
        return redirect("institution_portal")
    referral = get_object_or_404(
        Referral.objects.select_related("incident__request", "incident__assigned_area", "referred_by"),
        pk=referral_id,
        recipient_admin=request.user,
    )
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "message":
            body = request.POST.get("body", "").strip()
            attachment = request.FILES.get("file")
            if body or attachment:
                if attachment and not _is_allowed_chat_file(attachment):
                    messages.error(request, "This file type is not allowed or the file is larger than 20 MB.")
                    return redirect("institution_case", referral_id=referral.pk)
                attachment_fingerprint = f"{attachment.name}:{attachment.size}" if attachment else ""
                message_key = _write_idempotency_key(request, "institution-message", referral.pk, body, attachment_fingerprint)
                CaseMessage.objects.get_or_create(
                    idempotency_key=message_key,
                    defaults={
                        "referral": referral,
                        "incident": referral.incident,
                        "sender": request.user,
                        "recipient": referral.referred_by,
                        "body": body[:4000],
                        **(_chat_file_fields(attachment) if attachment else {}),
                    },
                )
                messages.success(request, "Message sent to the referring responder.")
            else:
                messages.error(request, "Write a message or attach a file.")
        elif action == "call":
            call_key = _write_idempotency_key(request, "institution-call", referral.pk)
            CallRequest.objects.get_or_create(
                idempotency_key=call_key,
                defaults={
                    "referral": referral,
                    "caller": request.user,
                    "recipient": referral.referred_by,
                },
            )
            messages.success(request, "Call request sent to the referring responder.")
        elif action == "archive":
            referral.archived_at = timezone.now()
            referral.read_at = referral.read_at or timezone.now()
            referral.save(update_fields=["archived_at", "read_at"])
            return redirect("institution_portal")
        referral.read_at = referral.read_at or timezone.now()
        referral.save(update_fields=["read_at"])
        broadcast_case_chat_update(referral.pk)
        return redirect("institution_case", referral_id=referral.pk)
    referral.read_at = referral.read_at or timezone.now()
    referral.save(update_fields=["read_at"])
    sender_profile = getattr(referral.referred_by, "response_profile", None)
    return render(request, "institution/case.html", {
        "profile": request.user.institution_profile,
        "referral": referral,
        "messages": referral.messages.select_related("sender", "recipient").all(),
        "call_requests": referral.call_requests.select_related("caller", "recipient").all(),
        "sender_phone": sender_profile.phone_number if sender_profile else "",
        "websocket_token": websocket_access_token(request, "case", [referral.pk], "institution"),
    })


@login_required(login_url="/institution/login/")
def institution_global_map(request: HttpRequest) -> HttpResponse:
    if not _can_access_institution(request.user):
        return redirect("institution_login")
    profile = request.user.institution_profile
    if profile.force_password_change:
        return redirect("institution_portal")
    try:
        selected_case_id = int(request.GET.get("case", ""))
    except (TypeError, ValueError):
        selected_case_id = None
    referrals = Referral.objects.filter(
        recipient_admin=request.user,
    ).select_related("incident__request", "incident__assigned_area", "referred_by")
    case_rows = {}
    for referral in referrals:
        incident = referral.incident
        if incident.pk in case_rows:
            continue
        case_rows[incident.pk] = {
            "id": incident.pk,
            "reference": incident.request.request_id,
            "type": incident.request.get_emergency_type_display(),
            "priority": incident.request.get_priority_display(),
            "status": incident.get_status_display(),
            "area": incident.assigned_area.name if incident.assigned_area else "Unassigned",
            "lat": float(incident.request.latitude) if incident.request.latitude is not None else None,
            "lng": float(incident.request.longitude) if incident.request.longitude is not None else None,
            "url": reverse("institution_case", args=[referral.pk]),
            "selected": incident.pk == selected_case_id,
        }
    map_points = [row for row in case_rows.values() if row["lat"] is not None and row["lng"] is not None]
    selected_case = case_rows.get(selected_case_id)
    if selected_case:
        selected_incident = referrals.filter(incident_id=selected_case_id).first().incident
        selected_case["trail"] = _location_trail(selected_incident.request)
    return render(request, "institution/global_map.html", {
        "profile": profile,
        "map_points": map_points,
        "boundary_geojson": boundary_features([profile.area.name]),
        "sent_case_count": len(case_rows),
        "mapped_case_count": len(map_points),
        "selected_case": selected_case,
        "tracking_endpoint": reverse("institution_case_location", args=[selected_case_id]) if selected_case else "",
    })


@login_required(login_url="/institution/login/")
def institution_case_location(request: HttpRequest, incident_id: int) -> JsonResponse:
    if not _can_access_institution(request.user):
        return JsonResponse({"error": "Institution access is required."}, status=403)
    if request.user.institution_profile.force_password_change:
        return JsonResponse({"error": "Complete your institution passcode setup first."}, status=403)
    referral = Referral.objects.filter(
        incident_id=incident_id,
        recipient_admin=request.user,
    ).select_related("incident__request").order_by("-created_at").first()
    if referral is None:
        return JsonResponse({"error": "This case was not referred to your institution."}, status=403)
    case_request = referral.incident.request
    return JsonResponse({
        "latitude": float(case_request.latitude) if case_request.latitude is not None else None,
        "longitude": float(case_request.longitude) if case_request.longitude is not None else None,
        "trail": _location_trail(case_request),
        "tracking_active": case_request.tracking_active,
        "last_location_at": case_request.last_location_at.isoformat() if case_request.last_location_at else None,
        "status": referral.incident.status,
    })


def _group_incidents_by_area(incidents):
    grouped = {}
    for incident in incidents:
        area = incident.assigned_area or incident.request.area
        key = area.pk if area is not None else None
        bucket = grouped.setdefault(key, {
            "area": area,
            "name": area.name if area is not None else "Unassigned",
            "count": 0,
            "incidents": [],
        })
        bucket["incidents"].append(incident)
        bucket["count"] += 1
    return sorted(grouped.values(), key=lambda item: item["name"].lower())


def _area_activity_ranking(user, include_resolved=False, period="month"):
    period = period if period in {"month", "year"} else "month"
    if _is_parent_admin(user):
        areas = LocationArea.objects.filter(active=True)
    else:
        areas = user.response_profile.areas.filter(active=True)
    incidents = _visible_incidents(user)
    if not include_resolved:
        incidents = incidents.exclude(status__in=["resolved", "closed"])

    today = timezone.localdate()
    if period == "year":
        labels = []
        for offset in range(11, -1, -1):
            month_index = today.year * 12 + today.month - 1 - offset
            year, month_zero = divmod(month_index, 12)
            labels.append(today.replace(year=year, month=month_zero + 1, day=1))
    else:
        labels = [today - timedelta(days=offset) for offset in range(29, -1, -1)]

    palette = ["#2959b5", "#0f8b7d", "#b67329", "#d8615c", "#675ad4", "#7a8b2f", "#1d6f9d", "#a14a7e"]
    ranked = []
    for index, area in enumerate(areas):
        area_incidents = incidents.filter(assigned_area=area).select_related("request", "assigned_area").order_by("-request__created_at")
        count = area_incidents.count()
        if count == 0:
            continue
        trend_points = []
        risk_points = []
        for period_start in labels:
            if period == "year":
                period_incidents = area_incidents.filter(
                    request__created_at__year=period_start.year,
                    request__created_at__month=period_start.month,
                )
                label = period_start.strftime("%b %y")
            else:
                period_incidents = area_incidents.filter(request__created_at__date=period_start)
                label = period_start.strftime("%d %b")
            period_count = period_incidents.count()
            risk_total = sum({"critical": 4, "high": 3, "medium": 2, "normal": 1}.get(incident.request.priority, 0) for incident in period_incidents)
            trend_points.append({"label": label, "value": period_count})
            risk_points.append({"label": label, "value": risk_total})
        ranked.append({
            "area": area,
            "count": count,
            "incidents": list(area_incidents[:6]),
            "trend": trend_points,
            "risk": risk_points,
            "color": palette[index % len(palette)],
        })
    ranked.sort(key=lambda item: (-item["count"], item["area"].name.lower()))
    max_count = max((item["count"] for item in ranked), default=0)
    total_cases = sum(item["count"] for item in ranked)
    for item in ranked:
        item["share"] = (item["count"] / total_cases * 100) if total_cases else 0
        item["bar_width"] = (item["count"] / max_count * 100) if max_count else 0
        item["trend_points"] = _series_to_svg_points(item["trend"], max_value=max((point["value"] for point in item["trend"]), default=1), height=140, width=420)
        item["risk_points"] = _series_to_svg_points(item["risk"], max_value=max((point["value"] for point in item["risk"]), default=1), height=140, width=420)
    return ranked, total_cases


def _series_to_svg_points(series, max_value, width=420, height=140):
    if not series:
        return ""
    max_v = max(max_value, 1)
    values = [point["value"] for point in series]
    x_step = width / max(len(values) - 1, 1)
    points = []
    for index, value in enumerate(values):
        x = index * x_step
        y = height - (value / max_v) * (height - 18) - 8
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def _district_admin(area):
    if area is None:
        return None
    profiles = ResponseProfile.objects.filter(
        active=True,
        user__is_active=True,
        areas=area,
    ).select_related("user")
    if profiles.count() == 1:
        return profiles.first().user
    return None


def _institution_recipient(target_type, area, target_name=""):
    institution_type = {"police_station": "police", "hospital": "hospital"}.get(target_type)
    if not institution_type or area is None:
        return None
    institutions = InstitutionProfile.objects.filter(
        institution_type=institution_type,
        area=area,
        active=True,
        user__is_active=True,
    ).select_related("user")
    if target_type == "hospital" and target_name:
        matching = institutions.filter(
            Q(hospital_facility__name__iexact=target_name)
            | Q(institution_name__icontains=target_name)
            | Q(username__icontains=target_name)
        )
        if matching.exists():
            institutions = matching
    return institutions.first()


def _can_access_institution(user):
    if not user.is_authenticated or not user.is_active:
        return False
    try:
        return user.institution_profile.active
    except InstitutionProfile.DoesNotExist:
        return False


def _referral_message(incident):
    area = incident.assigned_area.name if incident.assigned_area else "the assigned response area"
    if incident.request.latitude is not None and incident.request.longitude is not None:
        location = (
            f"Coordinates: {incident.request.latitude}, {incident.request.longitude}. "
            f"Map: https://www.openstreetmap.org/?mlat={incident.request.latitude}&mlon={incident.request.longitude}"
        )
    else:
        location = "Coordinates: not available; open the case report for the complete location status."
    return (
        f"Emergency referral {incident.request.request_id}. "
        f"Type: {incident.request.get_emergency_type_display()}. "
        f"Priority: {incident.request.get_priority_display()}. "
        f"Area: {area}. Phone: {incident.request.phone_number}. {location}"
    )


def _referral_url(referral):
    subject = f"Emergency referral {referral.incident.request.request_id}"
    if referral.channel == "in_app":
        return reverse("dashboard_referral_inbox")
    if referral.channel == "whatsapp":
        phone = "".join(character for character in referral.target_contact if character.isdigit() or character == "+")
        return f"https://wa.me/{phone.lstrip('+')}?text={quote_plus(referral.message)}"
    if referral.channel == "email":
        return f"https://mail.google.com/mail/?view=cm&fs=1&to={quote_plus(referral.target_contact)}&su={quote_plus(subject)}&body={quote_plus(referral.message)}"
    return f"sms:{referral.target_contact}?body={quote_plus(referral.message)}"


def _issue_referral_token(request, referral):
    if referral.channel != "in_app":
        return None
    token = secrets.token_urlsafe(18)
    referral.referral_token_hash = hashlib.sha256(token.encode()).hexdigest()
    referral.save(update_fields=["referral_token_hash"])
    request.session["referral_token_notice"] = {
        "referral_id": referral.pk,
        "token": token,
    }
    return token


def _token_referral_access(request, incident_id):
    referral_id = request.session.get(f"referral_token_access_{incident_id}")
    if not referral_id:
        return None
    return Referral.objects.filter(
        pk=referral_id,
        incident_id=incident_id,
        channel="in_app",
        archived_at__isnull=True,
    ).first()


@login_required
def dashboard_home(request: HttpRequest) -> HttpResponse:
    return dashboard_area_activity(request)


def _public_alert_areas(user):
    if _is_parent_admin(user):
        return LocationArea.objects.filter(active=True)
    return user.response_profile.areas.filter(active=True)


def _can_send_national_alert(user):
    if user.is_superuser:
        return True
    profile = getattr(user, "response_profile", None)
    return bool(profile and profile.active and profile.role == "regional")


def _public_alert_incidents(user, area, issue_type=""):
    incidents = _visible_incidents(user).filter(
        assigned_area=area,
        status__in=["new", "acknowledged", "responding"],
    )
    if issue_type and issue_type != "all":
        incidents = incidents.filter(request__emergency_type=issue_type)
    return incidents


def _can_delete_public_alert(user, alert):
    if user.is_superuser:
        return True
    profile = getattr(user, "response_profile", None)
    if not profile or not profile.active:
        return False
    if alert.created_by_id == user.pk:
        return True
    return bool(
        alert.area_id
        and profile.areas.filter(active=True, pk=alert.area_id).exists()
    )


def _public_alert_metrics(user):
    type_labels = dict(EmergencyRequest.EMERGENCY_TYPES)
    metrics = []
    for area in _public_alert_areas(user):
        area_incidents = list(_public_alert_incidents(user, area).select_related("request"))
        issue_counts = {}
        for incident in area_incidents:
            issue_counts[incident.request.emergency_type] = issue_counts.get(incident.request.emergency_type, 0) + 1
        issue_options = [
            {
                "value": issue_type,
                "label": type_labels.get(issue_type, issue_type.title()),
                "count": count,
            }
            for issue_type, count in sorted(issue_counts.items(), key=lambda item: (-item[1], type_labels.get(item[0], item[0])))
        ]
        leading_issue = issue_options[0] if issue_options else None
        metrics.append({
            "id": area.pk,
            "name": area.name,
            "count": len(area_incidents),
            "leading_issue": leading_issue,
            "issues": issue_options,
        })
    return metrics


def _send_public_area_alert(alert, request):
    vapid_private_key = settings.WEBPUSH_VAPID_PRIVATE_KEY
    vapid_subject = settings.WEBPUSH_VAPID_SUBJECT
    if not vapid_private_key or not settings.WEBPUSH_VAPID_PUBLIC_KEY or not vapid_subject:
        return "not_configured", 0, 0, "Web Push is not configured yet. The alert is saved for the audit log."
    try:
        from pywebpush import webpush
        from py_vapid import Vapid
    except ImportError:
        logger.error("pywebpush is not installed; public area alerts cannot be delivered.")
        return "not_configured", 0, 0, "Install the Web Push dependency before sending public alerts."

    try:
        if os.path.isfile(vapid_private_key):
            vapid = Vapid.from_file(private_key_file=vapid_private_key)
        else:
            vapid = Vapid.from_string(private_key=vapid_private_key)
        public_numbers = vapid.public_key.public_numbers()
        derived_public_key = base64.urlsafe_b64encode(
            b"\x04"
            + public_numbers.x.to_bytes(32, "big")
            + public_numbers.y.to_bytes(32, "big")
        ).rstrip(b"=").decode()
    except Exception:
        logger.exception("The configured Web Push VAPID private key is invalid.")
        return "not_configured", 0, 0, "The Web Push private key is invalid. Check the VAPID environment variables."

    if derived_public_key != settings.WEBPUSH_VAPID_PUBLIC_KEY:
        logger.error("The configured Web Push VAPID public and private keys do not match.")
        return "not_configured", 0, 0, "The Web Push public and private keys do not match. Replace them with one matching VAPID key pair."

    payload = json.dumps({
        "title": alert.title,
        "body": alert.body,
        "severity": "critical",
        "area": "Uganda" if alert.is_national else alert.area.name,
        "national": alert.is_national,
        "alert_id": alert.pk,
        "created_at": alert.created_at.isoformat(),
        "expires_at": (alert.created_at + PUBLIC_ALERT_LIFETIME).isoformat(),
        "url": request.build_absolute_uri(reverse("public_area_alert_detail", args=[alert.pk])),
    })
    sent_count = 0
    failed_count = 0
    failure_message = ""
    recipient_subscriptions = PublicAlertSubscription.objects.filter(active=True)
    if not alert.is_national:
        recipient_subscriptions = recipient_subscriptions.filter(
            Q(receives_area_alerts=True, area=alert.area)
            | Q(receives_area_alerts=True, notification_areas=alert.area)
            | Q(travel_plans__route_areas=alert.area, travel_plans__active=True),
        ).distinct()
    for subscription in recipient_subscriptions.iterator():
        subscription_info = {
            "endpoint": subscription.endpoint,
            "keys": {
                "p256dh": subscription.p256dh,
                "auth": subscription.auth,
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": vapid_subject},
                headers={"Urgency": "high"},
                ttl=int(PUBLIC_ALERT_LIFETIME.total_seconds()),
                timeout=10,
            )
            sent_count += 1
        except Exception as error:  # Web Push providers return different exception types.
            failed_count += 1
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)
            if status_code in {404, 410}:
                subscription.active = False
                subscription.save(update_fields=["active", "last_seen_at"])
                failure_message = "A subscribed browser is no longer available and was removed. Ask that person to subscribe again."
            elif status_code in {401, 403}:
                failure_message = "The push provider rejected the VAPID credentials. Check that the public and private keys match."
            elif status_code:
                failure_message = f"The push provider returned HTTP {status_code}. Try again shortly."
            else:
                failure_message = "The push provider could not be reached. Check the server network connection and try again."
            logger.warning(
                "Public area alert delivery failed for subscription %s (HTTP %s): %s",
                subscription.pk,
                status_code or "connection error",
                error,
            )

    if sent_count == 0 and failed_count == 0:
        if alert.is_national:
            return "published", 0, 0, "National alert published. No subscribed browser was available for a push notification."
        return "no_subscribers", 0, 0, "Alert saved, but no people in this district have opted in to browser alerts."
    if sent_count and failed_count:
        return "partial", sent_count, failed_count, f"Alert delivered to {sent_count} subscribed browser(s); {failed_count} subscription(s) failed. {failure_message}"
    if failed_count:
        return "failed", 0, failed_count, failure_message or "The alert could not be delivered to the subscribed browsers."
    return "sent", sent_count, 0, f"Alert delivered to {sent_count} subscribed browser(s)."


def _create_public_area_alert(request, user):
    alert_scope = request.POST.get("alert_scope", "district").strip().lower()
    if alert_scope not in {"district", "national"}:
        messages.error(request, "Choose a valid alert audience.")
        return
    is_national = alert_scope == "national"
    if is_national and not _can_send_national_alert(user):
        messages.error(request, "Only a regional administrator or the main administrator can send a whole-country alert.")
        return
    area = None
    if not is_national:
        try:
            area_id = int(request.POST.get("alert_area", ""))
        except (TypeError, ValueError):
            messages.error(request, "Choose a district before sending an area alert.")
            return
        area = _public_alert_areas(user).filter(pk=area_id).first()
        if area is None:
            messages.error(request, "You can only send alerts to a district assigned to your account.")
            return
    issue_type = request.POST.get("alert_issue_type", "all").strip().lower()
    valid_issue_types = {value for value, _ in EmergencyRequest.EMERGENCY_TYPES}
    if issue_type != "all" and issue_type not in valid_issue_types:
        messages.error(request, "Choose a valid emergency issue group.")
        return
    if is_national:
        alert_incidents = _visible_incidents(user).filter(status__in=["new", "acknowledged", "responding"])
        if issue_type != "all":
            alert_incidents = alert_incidents.filter(request__emergency_type=issue_type)
        case_count = alert_incidents.count()
    else:
        case_count = _public_alert_incidents(user, area, issue_type).count()
    title = request.POST.get("alert_title", "").strip()[:120]
    body = request.POST.get("alert_body", "").strip()[:600]
    if not title or not body:
        messages.error(request, "Add a short alert title and public safety message.")
        return
    idempotency_key = _write_idempotency_key(request, "public-area-alert", alert_scope, area.pk if area else "uganda", issue_type)
    existing_alert = AreaAlert.objects.filter(idempotency_key=idempotency_key).first()
    if existing_alert:
        messages.info(request, "This area alert was already recorded.")
        return
    alert = AreaAlert.objects.create(
        area=area,
        created_by=user,
        title=title,
        body=body,
        issue_type="" if issue_type == "all" else issue_type,
        case_count_snapshot=case_count,
        is_national=is_national,
        idempotency_key=idempotency_key,
    )
    delivery_status, recipient_count, failed_count, delivery_message = _send_public_area_alert(alert, request)
    if is_national and delivery_status in {"not_configured", "no_subscribers", "failed"}:
        delivery_status = "published"
        delivery_message = f"National alert published for all users. {delivery_message}"
    alert.delivery_status = delivery_status
    alert.recipient_count = recipient_count
    alert.failed_count = failed_count
    alert.sent_at = timezone.now()
    alert.save(update_fields=["delivery_status", "recipient_count", "failed_count", "sent_at"])
    if delivery_status in {"sent", "partial"}:
        messages.success(request, delivery_message)
    else:
        messages.warning(request, delivery_message)


@login_required
def dashboard_global_map(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    if request.method == "POST" and request.POST.get("action") == "send_area_alert":
        if _rate_limited(request, "public-area-alert", limit=5, window=300):
            messages.error(request, "Please wait before sending another area alert.")
        else:
            _create_public_area_alert(request, request.user)
        return redirect("dashboard_global_map")
    if _is_parent_admin(request.user):
        areas = LocationArea.objects.filter(active=True)
    else:
        areas = request.user.response_profile.areas.filter(active=True)
    visible_incidents = _visible_incidents(request.user)
    try:
        selected_case_id = int(request.GET.get("case", ""))
    except (TypeError, ValueError):
        selected_case_id = None
    selected_case = visible_incidents.filter(pk=selected_case_id).first() if selected_case_id else None
    case_filter = Q(status__in=["new", "acknowledged", "responding"])
    if selected_case:
        case_filter |= Q(pk=selected_case.pk)
    incidents = visible_incidents.filter(case_filter)
    selected_trail = _location_trail(selected_case.request) if selected_case else []
    map_points = []
    for incident in incidents:
        if incident.request.latitude is None or incident.request.longitude is None:
            continue
        is_selected = bool(selected_case and incident.pk == selected_case.pk)
        map_points.append({
            "id": incident.pk,
            "reference": incident.request.request_id,
            "type": incident.request.get_emergency_type_display(),
            "priority": incident.request.get_priority_display(),
            "status": incident.get_status_display(),
            "area": incident.assigned_area.name if incident.assigned_area else "Unassigned",
            "lat": float(incident.request.latitude),
            "lng": float(incident.request.longitude),
            "url": reverse("dashboard_incident", args=[incident.pk]),
            "selected": is_selected,
            "trail": selected_trail if is_selected else [],
        })
    return render(request, "dashboard/global_map.html", {
        "map_points": map_points,
        "boundary_geojson": boundary_features(areas.values_list("name", flat=True)),
        "mapped_case_count": len(map_points),
        "handled_case_count": incidents.count(),
        "selected_case": selected_case,
        "tracking_endpoint": reverse("dashboard_incident_location", args=[selected_case.pk]) if selected_case else "",
        "alert_metrics": _public_alert_metrics(request.user),
        "can_send_national_alert": _can_send_national_alert(request.user),
        "emergency_types": EmergencyRequest.EMERGENCY_TYPES,
        "webpush_configured": bool(
            settings.WEBPUSH_VAPID_PUBLIC_KEY
            and settings.WEBPUSH_VAPID_PRIVATE_KEY
            and settings.WEBPUSH_VAPID_SUBJECT
        ),
    })


def _inhouse_conversation_for_users(user_a, user_b):
    user_one_id, user_two_id = sorted((user_a.pk, user_b.pk))
    return InHouseConversation.objects.filter(
        user_one_id=user_one_id,
        user_two_id=user_two_id,
    ).first()


@login_required
def inhouse_chat(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    is_feed_request = request.GET.get("format") == "json"
    if request.method == "GET" and not is_feed_request:
        InHouseMessage.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
    profiles = list(
        ResponseProfile.objects.filter(
            active=True,
            user__is_active=True,
        ).exclude(user_id=request.user.pk).select_related("user").prefetch_related("areas")
    )
    contact_ids = [profile.user_id for profile in profiles]
    unread_by_sender = dict(
        InHouseMessage.objects.filter(
            recipient=request.user,
            read_at__isnull=True,
            sender_id__in=contact_ids,
        ).values("sender_id").annotate(total=Count("pk")).values_list("sender_id", "total")
    )
    contacts = [
        {
            "user_id": profile.user_id,
            "code": _inhouse_admin_code(profile),
            "role": profile.get_role_display(),
            "unread": unread_by_sender.get(profile.user_id, 0),
        }
        for profile in profiles
    ]
    selected_peer_id = request.POST.get("peer") or request.GET.get("peer", "")
    try:
        selected_peer_id = int(selected_peer_id)
    except (TypeError, ValueError):
        selected_peer_id = None
    selected_profile = next((profile for profile in profiles if profile.user_id == selected_peer_id), None)
    conversation = None
    if selected_profile:
        user_one_id, user_two_id = sorted((request.user.pk, selected_profile.user_id))
        conversation, _ = InHouseConversation.objects.get_or_create(
            user_one_id=user_one_id,
            user_two_id=user_two_id,
        )
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        attachment = request.FILES.get("file")
        if selected_profile is None:
            if is_ajax:
                return JsonResponse({"error": "Choose an admin before sending."}, status=400)
            messages.error(request, "Choose an admin before sending a message.")
        elif not body and not attachment:
            if is_ajax:
                return JsonResponse({"error": "Write a message or attach a file."}, status=400)
            messages.error(request, "Write a message or attach a file.")
        elif attachment and not _is_allowed_chat_file(attachment):
            if is_ajax:
                return JsonResponse({"error": "This file type is not allowed or the file is larger than 20 MB."}, status=400)
            messages.error(request, "This file type is not allowed or the file is larger than 20 MB.")
        elif len(body) > 4000:
            if is_ajax:
                return JsonResponse({"error": "Messages cannot be longer than 4,000 characters."}, status=400)
            messages.error(request, "Messages cannot be longer than 4,000 characters.")
        else:
            attachment_fingerprint = f"{attachment.name}:{attachment.size}" if attachment else ""
            message_key = _write_idempotency_key(request, "inhouse-message", conversation.pk, body, attachment_fingerprint)
            InHouseMessage.objects.get_or_create(
                idempotency_key=message_key,
                defaults={
                    "conversation": conversation,
                    "sender": request.user,
                    "recipient": selected_profile.user,
                    "body": body[:4000],
                    **(_chat_file_fields(attachment) if attachment else {}),
                },
            )
            conversation.save(update_fields=["updated_at"])
            broadcast_inhouse_chat_update(conversation.pk)
            if is_ajax:
                return JsonResponse({"ok": True})
        return redirect(f"{reverse('inhouse_chat')}?peer={selected_profile.user_id if selected_profile else ''}")

    if conversation and is_feed_request:
        InHouseMessage.objects.filter(
            conversation=conversation,
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        current_profile = getattr(request.user, "response_profile", None)
        sender_codes = {
            request.user.pk: _inhouse_admin_code(current_profile),
            selected_profile.user_id: _inhouse_admin_code(selected_profile),
        }
        return JsonResponse({
            "messages": [
                {
                    "id": item.pk,
                    "body": item.body,
                    "attachment_url": reverse("inhouse_chat_file", args=[item.pk]) if item.attachment else "",
                    "attachment_name": item.attachment_name,
                    "attachment_size": item.attachment_size,
                    "mine": item.sender_id == request.user.pk,
                    "sender_code": sender_codes.get(item.sender_id, "non"),
                    "created_at": timezone.localtime(item.created_at).strftime("%d %b %Y · %H:%M"),
                }
                for item in conversation.messages.select_related("sender").all()
            ],
            "unread": conversation.messages.filter(recipient=request.user, read_at__isnull=True).count(),
        })

    current_profile = getattr(request.user, "response_profile", None)
    conversation_messages = conversation.messages.select_related("sender").all() if conversation else []
    return render(request, "dashboard/inhouse_chat.html", {
        "contacts": contacts,
        "current_code": _inhouse_admin_code(current_profile),
        "selected_profile": selected_profile,
        "selected_code": _inhouse_admin_code(selected_profile) if selected_profile else "",
        "conversation": conversation,
        "conversation_messages": conversation_messages,
        "websocket_token": websocket_access_token(request, "inhouse", [conversation.pk]) if conversation else "",
    })


@login_required
def inhouse_chat_file(request: HttpRequest, message_id: int) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return HttpResponseForbidden("Dashboard access is required.")
    message = InHouseMessage.objects.select_related("conversation").filter(pk=message_id).first()
    if message is None or not message.attachment:
        return HttpResponse(status=404)
    conversation = message.conversation
    if request.user.pk not in {conversation.user_one_id, conversation.user_two_id}:
        return HttpResponseForbidden("In-house chat access is required.")
    filename = Path(message.attachment_name or message.attachment.name).name.replace('"', "")
    try:
        file_handle = message.attachment.open("rb")
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(
        file_handle,
        content_type=message.attachment_content_type or mimetypes.guess_type(message.attachment.name)[0] or "application/octet-stream",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def dashboard_area_activity(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    period = request.GET.get("period", "month").strip().lower()
    period = period if period in {"month", "year"} else "month"
    ranking, total_cases = _area_activity_ranking(request.user, period=period)
    if _is_parent_admin(request.user):
        areas = LocationArea.objects.filter(active=True)
    else:
        areas = request.user.response_profile.areas.filter(active=True)
    all_incidents = _visible_incidents(request.user)
    map_incidents = all_incidents.exclude(status__in=["resolved", "closed"])
    map_points = [
        {
            "id": incident.pk,
            "reference": incident.request.request_id,
            "type": incident.request.get_emergency_type_display(),
            "priority": incident.request.get_priority_display(),
            "status": incident.get_status_display(),
            "area": incident.assigned_area.name if incident.assigned_area else "Unassigned",
            "lat": float(incident.request.latitude),
            "lng": float(incident.request.longitude),
            "url": reverse("dashboard_incident", args=[incident.pk]),
        }
        for incident in map_incidents
        if incident.request.latitude is not None and incident.request.longitude is not None
    ]
    boundary_geojson = boundary_features(areas.values_list("name", flat=True))
    area_chart_data = [
        {
            "label": item["area"].name,
            "color": item["color"],
            "count": item["count"],
            "trend": item["trend"],
        }
        for item in ranking
    ]
    if request.GET.get("format") == "json":
        return JsonResponse({
            "districts": area_chart_data,
            "total_cases": total_cases,
            "updated_at": timezone.now().isoformat(),
        })
    top_area = ranking[0] if ranking else None
    return render(request, "dashboard/area_activity.html", {
        "area_ranking": ranking,
        "total_cases": total_cases,
        "active_areas": len(ranking),
        "top_area": top_area,
        "period": period,
        "period_label": "Last 12 months" if period == "year" else "Last 30 days",
        "stats": {
            "active": all_incidents.filter(status="new", opened_at__isnull=True).count(),
            "critical": all_incidents.filter(
                request__priority="critical",
                status="new",
                opened_at__isnull=True,
            ).count(),
            "new": all_incidents.filter(status="new", opened_at__isnull=True).count(),
            "resolved": all_incidents.filter(status="resolved").count(),
        },
        "area_chart_data": area_chart_data,
        "map_points": map_points,
        "boundary_geojson": boundary_geojson,
        "report_incidents": all_incidents,
    })


@login_required
def dashboard_profile(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    profile = getattr(request.user, "response_profile", None)
    if request.method == "POST" and request.POST.get("action") == "set_favorites_passcode":
        passcode = request.POST.get("favorites_passcode", "")
        confirmation = request.POST.get("favorites_passcode_confirmation", "")
        if profile is None:
            messages.error(request, "A responder profile is required before setting a favorites passcode.")
        elif len(passcode) < 8:
            messages.error(request, "The favorites passcode must contain at least eight characters.")
        elif passcode != confirmation:
            messages.error(request, "The favorites passcode and confirmation do not match.")
        else:
            profile.set_favorites_passcode(passcode)
            profile.save(update_fields=["favorites_passcode_hash"])
            messages.success(request, "Your Favorites page passcode was updated.")
        return redirect("dashboard_profile")
    favorites_passcode_configured = bool(profile and profile.favorites_passcode_hash)
    show_passcode_form = not favorites_passcode_configured or request.GET.get("change_passcode") == "1"
    mfa_profile = _mfa_profile(request.user)
    assigned_areas = profile.areas.filter(active=True) if profile else LocationArea.objects.none()
    assigned_areas = list(assigned_areas)
    area_rows = [{"area": area, "code": area_routing_code(area)} for area in assigned_areas]
    visible_incidents = _visible_incidents(request.user)
    return render(request, "dashboard/profile.html", {
        "profile": profile,
        "area_rows": area_rows,
        "is_parent_admin": _is_parent_admin(request.user),
        "favorites_passcode_configured": favorites_passcode_configured,
        "show_passcode_form": show_passcode_form,
        "mfa_profile": mfa_profile,
        "stats": {
            "solved": Incident.objects.filter(assigned_admin=request.user, status__in=["resolved", "closed"]).count(),
            "incoming": visible_incidents.filter(status="new", opened_at__isnull=True).count(),
            "handled": Incident.objects.filter(assigned_admin=request.user).count(),
            "districts": len(assigned_areas),
        },
    })


@login_required
def dashboard_favorites(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    profile = getattr(request.user, "response_profile", None)
    access_key = f"favorites_access_{request.user.pk}"
    if request.method == "POST" and request.POST.get("action") == "lock":
        request.session.pop(access_key, None)
        return redirect("dashboard_favorites")
    if not profile or not request.session.get(access_key):
        error = None
        if request.method == "POST":
            passcode = request.POST.get("passcode", "")
            if profile and profile.check_favorites_passcode(passcode):
                request.session[access_key] = True
                return redirect("dashboard_favorites")
            error = "The favorites passcode is incorrect or has not been configured."
        return render(request, "dashboard/favorites.html", {
            "locked": True,
            "error": error,
            "configured": bool(profile and profile.favorites_passcode_hash),
        })
    favorites = IncidentFavorite.objects.filter(user=request.user).select_related(
        "incident__request", "incident__assigned_area", "incident__assigned_admin"
    )
    return render(request, "dashboard/favorites.html", {"locked": False, "favorites": favorites})


@login_required
def operations_center(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only super administrators can access the main Operations Center.")
    access = OperationsAccess.objects.exclude(passcode_hash="").order_by("pk").first()
    if access is None:
        access = OperationsAccess.objects.order_by("pk").first()
    if request.method == "POST" and request.POST.get("action") == "lock":
        request.session.pop("operations_center_access", None)
        return redirect("operations_center")
    if not request.session.get("operations_center_access"):
        error = None
        if request.method == "POST":
            passcode = request.POST.get("passcode", "")
            if access and access.check_passcode(passcode):
                request.session["operations_center_access"] = True
                return redirect("operations_center")
            error = "The level five passcode is incorrect or has not been configured."
        return render(request, "dashboard/operations_center.html", {
            "locked": True,
            "error": error,
            "configured": bool(access and access.passcode_hash),
            "access_admin_url": reverse("admin:incidents_operationsaccess_change", args=[access.pk]) if access else reverse("admin:incidents_operationsaccess_add"),
        })

    query = request.GET.get("q", "").strip()
    district_search = request.GET.get("district_search", "").strip()
    selected_district = request.GET.get("district", "").strip()
    case_register = Incident.objects.select_related(
        "request", "assigned_area", "assigned_admin"
    ).prefetch_related("recordings")

    district_rows = case_register.values(
        "assigned_area_id", "assigned_area__name"
    ).annotate(
        total=Count("pk"),
        active=Count("pk", filter=~Q(status__in=["resolved", "closed"])),
    ).order_by("assigned_area__name")
    district_cards = []
    for row in district_rows:
        district_name = row["assigned_area__name"] or "Unassigned"
        district_key = str(row["assigned_area_id"] or "unassigned")
        if district_search and district_search.casefold() not in district_name.casefold():
            continue
        district_cards.append({
            "key": district_key,
            "name": district_name,
            "total": row["total"],
            "active": row["active"],
        })

    if selected_district == "unassigned":
        case_register = case_register.filter(assigned_area__isnull=True)
    elif selected_district.isdigit():
        case_register = case_register.filter(assigned_area_id=int(selected_district))
    elif selected_district:
        selected_district = ""

    cases = case_register
    if query:
        search_filter = Q(
            request__request_id__icontains=query
        ) | Q(
            request__phone_number__icontains=query
        ) | Q(
            request__location_description__icontains=query
        ) | Q(
            request__message__icontains=query
        ) | Q(
            request__area__name__icontains=query
        ) | Q(
            assigned_area__name__icontains=query
        ) | Q(
            assigned_admin__username__icontains=query
        )
        if query.isdigit():
            case_number = int(query)
            if Incident.objects.filter(pk=case_number).exists():
                search_filter = Q(pk=case_number)
            else:
                search_filter = Q(request__phone_number__icontains=query)
        cases = cases.filter(search_filter).distinct()
    cases = cases.order_by("-request__created_at", "-pk")
    selected_card = next(
        (card for card in district_cards if card["key"] == selected_district),
        None,
    )
    show_case_results = bool(selected_district or query)
    page = Paginator(cases, 25).get_page(request.GET.get("page"))
    for incident in page.object_list:
        incident.operations_number = incident.pk
    return render(request, "dashboard/operations_center.html", {
        "locked": False,
        "district_cards": district_cards,
        "district_search": district_search,
        "selected_district": selected_district,
        "selected_card": selected_card,
        "show_case_results": show_case_results,
        "cases": page,
        "query": query,
        "total_cases": Incident.objects.count(),
        "active_cases": Incident.objects.exclude(status__in=["resolved", "closed"]).count(),
        "resolved_cases": Incident.objects.filter(status__in=["resolved", "closed"]).count(),
    })


@login_required
def dashboard_incoming(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    active_incoming = _visible_incidents(request.user).filter(status="new").order_by("-request__created_at", "-pk")
    view_filter = request.GET.get("view", "")
    priority_filter = request.GET.get("priority", "")
    district_filter = request.GET.get("district", "")
    if view_filter == "opened":
        incoming = active_incoming.filter(opened_at__isnull=False)
    else:
        view_filter = "unopened"
        incoming = active_incoming.filter(opened_at__isnull=True)
    if priority_filter:
        incoming = incoming.filter(request__priority=priority_filter)
    selected_area = None
    if district_filter:
        selected_area = LocationArea.objects.filter(pk=district_filter).first()
    if selected_area:
        incoming = incoming.filter(assigned_area=selected_area)
    unopened_incoming = active_incoming.filter(opened_at__isnull=True)
    grouped_incidents = _group_incidents_by_area(incoming)
    chat_alert_ids = set(EmergencyChatRoom.objects.filter(
        incident__in=unopened_incoming,
        accepted_at__isnull=False,
    ).values_list("incident_id", flat=True))
    return render(request, "dashboard/incoming.html", {
        "incidents": incoming,
        "grouped_incidents": grouped_incidents,
        "chat_alert_ids": chat_alert_ids,
        "selected_area": selected_area,
        "view_filter": view_filter,
        "priority_filter": priority_filter,
        "district_filter": district_filter,
        "counts": {
            "all": unopened_incoming.count(),
            "unopened": unopened_incoming.count(),
            "opened": active_incoming.filter(opened_at__isnull=False).count(),
        },
    })


@login_required
def dashboard_cases(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    cases = _visible_incidents(request.user).filter(
        Q(status__in=["acknowledged", "responding", "resolved", "closed"])
        | Q(opened_at__isnull=False)
    ).distinct()
    status_filter = request.GET.get("status", "")
    district_filter = request.GET.get("district", "")
    if status_filter:
        cases = cases.filter(status=status_filter)
    selected_area = None
    if district_filter:
        selected_area = LocationArea.objects.filter(pk=district_filter).first()
        if selected_area:
            cases = cases.filter(assigned_area=selected_area)
    grouped_cases = _group_incidents_by_area(cases)
    public_alerts = AreaAlert.objects.filter(
        Q(is_national=True) | Q(area__in=_public_alert_areas(request.user)),
    ).select_related("area", "created_by").order_by("-created_at", "-pk")
    if selected_area:
        public_alerts = public_alerts.filter(Q(is_national=True) | Q(area=selected_area))
    return render(request, "dashboard/cases.html", {
        "cases": cases,
        "grouped_cases": grouped_cases,
        "public_alerts": public_alerts,
        "selected_area": selected_area,
        "status_filter": status_filter,
        "district_filter": district_filter,
    })


@login_required
def dashboard_alert_delete(request: HttpRequest, alert_id: int) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    if request.method != "POST":
        return HttpResponseForbidden("Alerts can only be deleted with a POST request.")

    alert = get_object_or_404(AreaAlert, pk=alert_id)
    if not _can_delete_public_alert(request.user, alert):
        record_security_event(
            request,
            "public_alert_delete_failure",
            user=request.user,
            details={"alert_id": alert.pk, "reason": "not_authorized"},
        )
        messages.error(request, "You are not allowed to delete this public alert.")
        return redirect("dashboard_cases")

    alert_title = alert.title
    alert.delete()
    record_security_event(
        request,
        "public_alert_delete_success",
        user=request.user,
        details={"alert_id": alert_id, "title": alert_title},
    )
    messages.success(request, "The public alert was deleted from the archive.")
    return redirect("dashboard_cases")


@login_required
def dashboard_incident(request: HttpRequest, incident_id: int) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    if request.session.get("operations_center_access"):
        visible_incidents = Incident.objects.select_related(
            "request", "assigned_area", "assigned_admin"
        ).prefetch_related("recordings")
    else:
        visible_incidents = _visible_incidents(request.user)
    token_referral = None
    if not visible_incidents.filter(pk=incident_id).exists():
        token_referral = _token_referral_access(request, incident_id)
        if token_referral:
            visible_incidents = Incident.objects.select_related(
                "request", "assigned_area", "assigned_admin"
            ).prefetch_related("recordings").filter(pk=incident_id)
        else:
            restricted_incident = get_object_or_404(
                Incident.objects.select_related("assigned_area", "assigned_admin"),
                pk=incident_id,
            )
            record_security_event(
                request,
                "access_denied",
                user=request.user,
                details={"surface": "dashboard_incident", "incident_id": incident_id},
            )
            district_admin = restricted_incident.assigned_admin or _district_admin(restricted_incident.assigned_area)
            district_admin_label = masked_admin_label(district_admin) if district_admin else "the assigned district administrator"
            district_name = restricted_incident.assigned_area.name if restricted_incident.assigned_area else "the assigned district"
            return render(request, "dashboard/access_denied.html", {
                "district_admin_label": district_admin_label,
                "district_name": district_name,
            }, status=403)
    incident = get_object_or_404(visible_incidents, pk=incident_id)
    _ensure_emergency_chat_room(incident)
    emergency_chat_room = _active_emergency_chat_room(incident)
    if incident.opened_at is None:
        opened_at = timezone.now()
        incident.opened_at = opened_at
        update_fields = ["opened_at"]
        if incident.status == "new":
            incident.status = "acknowledged"
            incident.acknowledged_at = opened_at
            update_fields.extend(["status", "acknowledged_at"])
        incident.save(update_fields=update_fields)
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete_case":
            if not request.user.is_superuser:
                record_security_event(
                    request,
                    "case_delete_failure",
                    user=request.user,
                    details={"incident_id": incident.pk, "reason": "not_superuser"},
                )
                return HttpResponseForbidden("Only the parent administrator can delete case data.")
            if incident.status not in {"resolved", "closed"}:
                messages.error(request, "Only resolved or closed cases can be permanently deleted.")
                return redirect("dashboard_incident", incident_id=incident.pk)
            if _rate_limited(request, f"case-delete:{request.user.pk}", limit=5, window=300):
                record_security_event(
                    request,
                    "case_delete_failure",
                    user=request.user,
                    details={"incident_id": incident.pk, "reason": "throttled"},
                )
                messages.error(request, "Too many deletion attempts. Please wait five minutes.")
                return redirect("dashboard_incident", incident_id=incident.pk)
            if not check_password(request.POST.get("delete_passcode", ""), settings.CASE_DELETE_PASSWORD_HASH):
                record_security_event(
                    request,
                    "case_delete_failure",
                    user=request.user,
                    details={"incident_id": incident.pk, "reason": "invalid_passcode"},
                )
                messages.error(request, "The case deletion passcode is incorrect.")
                return redirect("dashboard_incident", incident_id=incident.pk)

            incident_id = incident.pk
            case_request = incident.request
            request_id = case_request.request_id
            media_files = list(
                Recording.objects.filter(incident=incident).exclude(file="").values_list("file", flat=True)
            )
            media_files.extend(
                EmergencyChatMessage.objects.filter(room__incident=incident)
                .exclude(audio="")
                .values_list("audio", flat=True)
            )
            media_files.extend(
                EmergencyChatMessage.objects.filter(room__incident=incident)
                .exclude(attachment="")
                .values_list("attachment", flat=True)
            )
            media_files.extend(
                CaseMessage.objects.filter(incident=incident)
                .exclude(attachment="")
                .values_list("attachment", flat=True)
            )
            with transaction.atomic():
                incident.delete()
                case_request.delete()
                record_security_event(
                    request,
                    "case_delete_success",
                    user=request.user,
                    details={
                        "incident_id": incident_id,
                        "request_id": request_id,
                        "media_files": len(set(media_files)),
                    },
                )
            _delete_incident_files(media_files)
            messages.success(request, f"Case {request_id} and its attached data were permanently deleted.")
            return redirect("dashboard_cases")
        if action == "favorite":
            desired_state = request.POST.get("favorite_state")
            if desired_state == "on":
                IncidentFavorite.objects.get_or_create(incident=incident, user=request.user)
                messages.success(request, f"{incident.request.request_id} added to your favorites.")
            elif desired_state == "off":
                IncidentFavorite.objects.filter(incident=incident, user=request.user).delete()
                messages.success(request, f"{incident.request.request_id} removed from your favorites.")
            else:
                favorite = IncidentFavorite.objects.filter(incident=incident, user=request.user).first()
                if favorite:
                    favorite.delete()
                    messages.success(request, f"{incident.request.request_id} removed from your favorites.")
                else:
                    IncidentFavorite.objects.get_or_create(incident=incident, user=request.user)
                    messages.success(request, f"{incident.request.request_id} added to your favorites.")
            return redirect("dashboard_incident", incident_id=incident.pk)
        if action == "note":
            note_text = request.POST.get("note", "").strip()
            if note_text:
                note_key = _write_idempotency_key(request, "incident-note", incident.pk, note_text)
                IncidentNote.objects.get_or_create(
                    idempotency_key=note_key,
                    defaults={"incident": incident, "author": request.user, "note": note_text},
                )
                messages.success(request, "Case clue note added.")
            else:
                messages.error(request, "Enter a clue or note before saving.")
            return redirect("dashboard_incident", incident_id=incident.pk)
        if action == "case_message":
            referral = get_object_or_404(
                Referral,
                pk=request.POST.get("referral"),
                incident=incident,
                referred_by=request.user,
                recipient_admin__institution_profile__isnull=False,
            )
            body = request.POST.get("body", "").strip()
            attachment = request.FILES.get("file")
            if body or attachment:
                if attachment and not _is_allowed_chat_file(attachment):
                    messages.error(request, "This file type is not allowed or the file is larger than 20 MB.")
                    return redirect("dashboard_incident", incident_id=incident.pk)
                attachment_fingerprint = f"{attachment.name}:{attachment.size}" if attachment else ""
                message_key = _write_idempotency_key(request, "case-message", referral.pk, body, attachment_fingerprint)
                CaseMessage.objects.get_or_create(
                    idempotency_key=message_key,
                    defaults={
                        "referral": referral,
                        "incident": incident,
                        "sender": request.user,
                        "recipient": referral.recipient_admin,
                        "body": body[:4000],
                        **(_chat_file_fields(attachment) if attachment else {}),
                    },
                )
                broadcast_case_chat_update(referral.pk)
                messages.success(request, "Message sent to the receiving institution.")
            else:
                messages.error(request, "Write a message or attach a file.")
            return redirect("dashboard_incident", incident_id=incident.pk)
        if action == "call_response":
            call_request = get_object_or_404(
                CallRequest,
                pk=request.POST.get("call_request"),
                recipient=request.user,
                referral__incident=incident,
            )
            response_status = request.POST.get("call_status")
            if response_status in {"accepted", "declined", "completed"}:
                call_request.status = response_status
                call_request.responded_at = timezone.now()
                call_request.save(update_fields=["status", "responded_at"])
            return redirect("dashboard_incident", incident_id=incident.pk)
        if action == "refer":
            referral_form = ReferralForm(request.POST)
            if referral_form.is_valid():
                referral = referral_form.save(commit=False)
                referral.incident = incident
                referral.referred_by = request.user
                referral.idempotency_key = _write_idempotency_key(request, "referral", incident.pk)
                existing_referral = Referral.objects.filter(idempotency_key=referral.idempotency_key).first()
                if existing_referral:
                    return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={existing_referral.pk}")
                if not referral.message:
                    referral.message = _referral_message(incident)
                try:
                    with transaction.atomic():
                        referral.save()
                except IntegrityError:
                    existing_referral = Referral.objects.filter(idempotency_key=referral.idempotency_key).first()
                    if existing_referral:
                        return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={existing_referral.pk}")
                    raise
                _issue_referral_token(request, referral)
                messages.success(request, f"Referral prepared for {referral.target_name}.")
                return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={referral.pk}")
        else:
            referral_form = ReferralForm()
        new_status = request.POST.get("status")
        allowed_statuses = {value for value, _ in Incident.STATUS_CHOICES}
        if new_status in allowed_statuses:
            incident.status = new_status
            if new_status == "acknowledged" and not incident.acknowledged_at:
                incident.acknowledged_at = timezone.now()
            if new_status in {"resolved", "closed"} and not incident.resolved_at:
                incident.resolved_at = timezone.now()
            if not incident.assigned_admin:
                incident.assigned_admin = request.user
            incident.save()
            messages.success(request, f"{incident.request.request_id} updated to {incident.get_status_display()}.")
        return redirect("dashboard_incident", incident_id=incident.pk)
    else:
        referral_form = ReferralForm(initial={"message": _referral_message(incident)})
    emergency_chat_allowed, _ = _can_access_emergency_chat(request, incident)
    chat_referrals = list(incident.referrals.filter(
        channel="in_app",
        recipient_admin__isnull=False,
    ).select_related("recipient_admin"))
    referral_rows = [{"referral": referral, "url": _referral_url(referral)} for referral in incident.referrals.all()]
    return render(request, "dashboard/incident.html", {
        "incident": incident,
        "referral_form": referral_form,
        "referral_rows": referral_rows,
        "is_favorite": IncidentFavorite.objects.filter(incident=incident, user=request.user).exists(),
        "notes": incident.notes.select_related("author").all(),
        "case_messages": incident.case_messages.select_related("sender", "recipient", "referral").all(),
        "call_requests": CallRequest.objects.filter(
            referral__incident=incident,
            referral__recipient_admin__institution_profile__isnull=False,
        ).select_related("caller", "recipient", "referral"),
        "chat_referrals": chat_referrals,
        "can_delete_case": request.user.is_superuser and incident.status in {"resolved", "closed"},
        "websocket_token": websocket_access_token(
            request,
            "case",
            [referral.pk for referral in chat_referrals],
            "admin",
        ) if chat_referrals else "",
        "new_referral": incident.referrals.filter(pk=request.GET.get("referral")).first() if request.GET.get("referral") else None,
        "referral_token": (
            request.session.pop("referral_token_notice", {}).get("token")
            if request.GET.get("referral") else None
        ),
        "opened_via_referral_token": bool(token_referral),
        "emergency_chat_room": emergency_chat_room,
        "emergency_chat_allowed": emergency_chat_allowed,
    })


@login_required
def dashboard_recording(request: HttpRequest, recording_id: int) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return HttpResponseForbidden("Dashboard access is required.")
    recording = Recording.objects.select_related("incident__request").filter(pk=recording_id).first()
    if recording is None:
        return HttpResponse(status=404)
    incident = recording.incident
    has_access = bool(request.session.get("operations_center_access")) or _visible_incidents(request.user).filter(pk=incident.pk).exists()
    if not has_access and _token_referral_access(request, incident.pk):
        has_access = True
    if not has_access:
        record_security_event(
            request,
            "access_denied",
            user=request.user,
            details={"surface": "dashboard_recording", "recording_id": recording_id},
        )
        return HttpResponseForbidden("This recording is not assigned to your account.")
    if not recording.file:
        return HttpResponse(status=404)
    filename = Path(recording.file.name).name.replace('"', "")
    try:
        file_handle = recording.file.open("rb")
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(
        file_handle,
        content_type=mimetypes.guess_type(recording.file.name)[0] or "application/octet-stream",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def emergency_chat_audio(request: HttpRequest, message_id: int) -> HttpResponse:
    message = EmergencyChatMessage.objects.select_related("room__incident").filter(pk=message_id).first()
    if message is None or not message.audio:
        return HttpResponse(status=404)
    room = message.room
    if room.expires_at <= timezone.now():
        return HttpResponse(status=404)
    allowed, _ = _can_access_emergency_chat(request, room.incident)
    if not allowed:
        return HttpResponseForbidden("Emergency chat access is required.")
    filename = Path(message.audio.name).name.replace('"', "")
    try:
        file_handle = message.audio.open("rb")
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(
        file_handle,
        content_type=mimetypes.guess_type(message.audio.name)[0] or "application/octet-stream",
    )
    response["Content-Disposition"] = f'inline; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


def emergency_chat_file(request: HttpRequest, message_id: int) -> HttpResponse:
    message = EmergencyChatMessage.objects.select_related("room__incident").filter(pk=message_id).first()
    if message is None or not message.attachment:
        return HttpResponse(status=404)
    room = message.room
    if room.expires_at <= timezone.now():
        return HttpResponse(status=404)
    allowed, _ = _can_access_emergency_chat(request, room.incident)
    if not allowed:
        return HttpResponseForbidden("Emergency chat access is required.")
    filename = Path(message.attachment_name or message.attachment.name).name.replace('"', "")
    try:
        file_handle = message.attachment.open("rb")
    except (FileNotFoundError, ValueError):
        return HttpResponse(status=404)
    response = FileResponse(
        file_handle,
        content_type=message.attachment_content_type or mimetypes.guess_type(message.attachment.name)[0] or "application/octet-stream",
    )
    disposition = "attachment" if request.GET.get("download") == "1" else "inline"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def dashboard_incident_location(request: HttpRequest, incident_id: int) -> JsonResponse:
    if not _can_access_dashboard(request.user):
        return JsonResponse({"error": "Dashboard access is required."}, status=403)
    if request.session.get("operations_center_access"):
        incident = Incident.objects.select_related("request").filter(pk=incident_id).first()
    else:
        incident = _visible_incidents(request.user).filter(pk=incident_id).first()
        if incident is None and _token_referral_access(request, incident_id):
            incident = Incident.objects.select_related("request").filter(pk=incident_id).first()
    if incident is None:
        return JsonResponse({"error": "This case is not assigned to your account."}, status=403)
    case_request = incident.request
    return JsonResponse({
        "latitude": float(case_request.latitude) if case_request.latitude is not None else None,
        "longitude": float(case_request.longitude) if case_request.longitude is not None else None,
        "trail": _location_trail(case_request),
        "tracking_active": case_request.tracking_active,
        "last_location_at": case_request.last_location_at.isoformat() if case_request.last_location_at else None,
        "status": incident.status,
    })


@login_required
def dashboard_referral_create(request: HttpRequest, incident_id: int) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    if request.session.get("operations_center_access"):
        visible_incidents = Incident.objects.select_related("request", "assigned_area", "assigned_admin")
    else:
        visible_incidents = _visible_incidents(request.user)
    incident = get_object_or_404(visible_incidents, pk=incident_id)
    form = ReferralForm(request.POST or None, initial={"message": _referral_message(incident)})
    form.fields["recipient_admin"].queryset = form.fields["recipient_admin"].queryset.exclude(pk=request.user.pk)
    if request.method == "POST" and form.is_valid():
        referral = form.save(commit=False)
        referral.incident = incident
        referral.referred_by = request.user
        referral.idempotency_key = _write_idempotency_key(request, "referral", incident.pk)
        existing_referral = Referral.objects.filter(idempotency_key=referral.idempotency_key).first()
        if existing_referral:
            return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={existing_referral.pk}")
        target_type = form.cleaned_data["target_type"]
        if target_type == "admin":
            recipient = form.cleaned_data["recipient_admin"]
            referral.recipient_admin = recipient
            referral.target_name = masked_admin_label(recipient)
            referral.target_contact = ""
            referral.channel = "in_app"
        elif form.cleaned_data.get("destination"):
            destination = form.cleaned_data["destination"]
            referral.destination = destination
            referral.target_name = destination.name
            referral.target_contact = destination.contact or destination.email
            if destination.assigned_admin:
                referral.recipient_admin = destination.assigned_admin
                referral.channel = "in_app"
        if target_type in {"police_station", "hospital", "government", "company"}:
            referral.destination_area = form.cleaned_data.get("destination_area")
            destination = form.cleaned_data.get("destination")
            hospital = form.cleaned_data.get("hospital_facility")
            if target_type == "hospital" and hospital:
                referral.destination_area = hospital.district
                referral.target_name = hospital.name
                referral.target_contact = ""
            if destination:
                referral.destination = destination
                referral.target_name = destination.name
                referral.target_contact = destination.contact or destination.email
                if destination.assigned_admin:
                    referral.recipient_admin = destination.assigned_admin
                    referral.channel = "in_app"
            elif referral.channel == "in_app":
                referral.recipient_admin = _district_admin(referral.destination_area)
            institution = _institution_recipient(
                target_type,
                referral.destination_area,
                referral.target_name,
            )
            if institution:
                referral.recipient_admin = institution.user
                referral.channel = "in_app"
        if not referral.message:
            referral.message = _referral_message(incident)
        try:
            with transaction.atomic():
                referral.save()
        except IntegrityError:
            existing_referral = Referral.objects.filter(idempotency_key=referral.idempotency_key).first()
            if existing_referral:
                return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={existing_referral.pk}")
            raise
        _issue_referral_token(request, referral)
        messages.success(request, f"Referral sent to {referral.target_name}.")
        return redirect(f"{reverse('dashboard_incident', args=[incident.pk])}?referral={referral.pk}")
    return render(request, "dashboard/referral_create.html", {
        "incident": incident,
        "referral_form": form,
    })


@login_required
def dashboard_referral_admin_search(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return JsonResponse({"results": []}, status=403)
    query = request.GET.get("q", "").strip().casefold()
    admins = get_user_model().objects.filter(
        Q(is_active=True) & (Q(is_superuser=True) | Q(response_profile__active=True)),
    ).exclude(pk=request.user.pk).distinct().prefetch_related("response_profile__areas")
    results = []
    for admin in admins:
        label = masked_admin_label(admin)
        try:
            district_names = list(admin.response_profile.areas.values_list("name", flat=True))
        except AttributeError:
            district_names = []
        searchable = " ".join([
            admin.get_username(),
            admin.first_name,
            admin.last_name,
            label,
        ] + district_names).casefold()
        if not query or query in searchable:
            results.append({"value": admin.pk, "label": label})
    return JsonResponse({"results": results})


@login_required
def dashboard_referral_inbox(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    view = request.GET.get("view") or request.POST.get("view", "inbox")
    if view not in {"inbox", "history"}:
        view = "inbox"
    if request.method == "POST":
        referral = get_object_or_404(Referral, pk=request.POST.get("referral"), recipient_admin=request.user)
        action = request.POST.get("action", "read")
        if action == "archive":
            referral.archived_at = timezone.now()
            referral.read_at = referral.read_at or timezone.now()
            referral.save(update_fields=["archived_at", "read_at"])
        elif action == "restore":
            referral.archived_at = None
            referral.save(update_fields=["archived_at"])
        else:
            referral.read_at = timezone.now()
            referral.save(update_fields=["read_at"])
        return redirect(f"{reverse('dashboard_referral_inbox')}?view={view}")
    all_referrals = Referral.objects.filter(recipient_admin=request.user).select_related(
        "incident__request", "incident__assigned_area", "referred_by"
    ).order_by("-created_at", "-pk")
    active_referrals = all_referrals.filter(archived_at__isnull=True)
    history_referrals = all_referrals.filter(archived_at__isnull=False)
    referrals = history_referrals if view == "history" else active_referrals
    referral_rows = [{"referral": referral, "sender_label": masked_admin_label(referral.referred_by)} for referral in referrals]
    return render(request, "dashboard/referral_inbox.html", {
        "referrals": referral_rows,
        "view": view,
        "inbox_count": active_referrals.count(),
        "history_count": history_referrals.count(),
        "unread_count": active_referrals.filter(read_at__isnull=True).count(),
    })


@login_required
def dashboard_referral_token(request: HttpRequest) -> HttpResponse:
    if not _can_access_dashboard(request.user):
        return _dashboard_inactive_redirect(request)
    error = None
    if request.method == "POST":
        token = request.POST.get("token", "").strip()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        referral = Referral.objects.filter(
            referral_token_hash=token_hash,
            channel="in_app",
            archived_at__isnull=True,
        ).select_related("incident").first()
        if referral is None:
            error = "That referral token is invalid, expired, or has already been archived."
        else:
            request.session[f"referral_token_access_{referral.incident_id}"] = referral.pk
            referral.read_at = referral.read_at or timezone.now()
            referral.save(update_fields=["read_at"])
            return redirect("dashboard_incident", incident_id=referral.incident_id)
    return render(request, "dashboard/referral_token.html", {"error": error})
