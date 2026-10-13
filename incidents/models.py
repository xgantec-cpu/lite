import uuid
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password, make_password
from django.db import models
from django.utils import timezone

from .fields import EncryptedDecimalField, EncryptedTextField


class LocationArea(models.Model):
    name = models.CharField(max_length=120, unique=True)
    routing_code = models.CharField(max_length=8, unique=True, null=True, blank=True)
    district = models.CharField(max_length=120, blank=True)
    region = models.CharField(max_length=120, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class HospitalFacility(models.Model):
    OWNERSHIP_CHOICES = [
        ("government", "Government"),
        ("pnfp", "Private not-for-profit"),
        ("private", "Private for-profit"),
    ]
    name = models.CharField(max_length=180)
    district = models.ForeignKey(LocationArea, on_delete=models.PROTECT, related_name="hospital_facilities")
    ownership = models.CharField(max_length=20, choices=OWNERSHIP_CHOICES, default="government")
    level = models.CharField(max_length=40, blank=True)
    external_id = models.CharField(max_length=80, blank=True)
    source_url = models.URLField(blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["ownership", "name"]
        constraints = [models.UniqueConstraint(fields=["name", "district"], name="unique_hospital_per_district")]

    def __str__(self):
        return f"{self.name} — {self.district.name}"


def area_routing_code(area):
    if area is None:
        return "NON"
    if area.routing_code:
        return area.routing_code.upper()
    letters = re.sub(r"[^A-Z]", "", area.name.upper())
    consonants = "".join(letter for letter in letters if letter not in "AEIOU")
    vowels = "".join(letter for letter in letters if letter in "AEIOU")
    code = (consonants + vowels)[:4]
    return code.ljust(4, "X")


class ResponseProfile(models.Model):
    ROLE_CHOICES = [
        ("regional", "Regional administrator"),
        ("area", "Area administrator"),
        ("officer", "Emergency officer"),
    ]
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, related_name="response_profile")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="area")
    areas = models.ManyToManyField(LocationArea, blank=True, related_name="response_profiles")
    phone_number = EncryptedTextField(max_length=32, blank=True)
    whatsapp_number = EncryptedTextField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    favorites_passcode_hash = models.CharField(max_length=128, blank=True, editable=False)

    def set_favorites_passcode(self, raw_passcode):
        self.favorites_passcode_hash = make_password(raw_passcode)

    def check_favorites_passcode(self, raw_passcode):
        return bool(self.favorites_passcode_hash) and check_password(raw_passcode, self.favorites_passcode_hash)

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_role_display()})"


class InHouseConversation(models.Model):
    user_one = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="inhouse_conversations_as_one")
    user_two = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="inhouse_conversations_as_two")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["user_one", "user_two"], name="unique_inhouse_user_pair"),
        ]

    def __str__(self):
        return f"In-house chat: {self.user_one} / {self.user_two}"


class InHouseMessage(models.Model):
    conversation = models.ForeignKey(InHouseConversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="inhouse_messages_sent")
    recipient = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="inhouse_messages_received")
    body = EncryptedTextField(max_length=4000)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"In-house message from {self.sender}"


class OperationsAccess(models.Model):
    label = models.CharField(max_length=120, default="Operations Center")
    passcode_hash = models.CharField(max_length=128, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def set_passcode(self, raw_passcode):
        self.passcode_hash = make_password(raw_passcode)

    def check_passcode(self, raw_passcode):
        return bool(self.passcode_hash) and check_password(raw_passcode, self.passcode_hash)

    def __str__(self):
        return self.label


class EmergencyRequest(models.Model):
    EMERGENCY_TYPES = [
        ("danger", "I am in danger"),
        ("urgent", "I need urgent help"),
        ("travel", "Vehicle / travel problem"),
        ("lost", "I am lost"),
        ("security", "Security problem"),
        ("medical", "Medical emergency"),
        ("contact", "I need to contact someone"),
        ("other", "Other"),
    ]
    PRIORITIES = [("critical", "Critical"), ("high", "High"), ("medium", "Medium"), ("normal", "Normal")]
    request_id = models.CharField(max_length=32, unique=True, editable=False)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    phone_number = EncryptedTextField(max_length=32)
    latitude = EncryptedDecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = EncryptedDecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_accuracy = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    location_source = models.CharField(max_length=20, choices=[("gps", "Device GPS"), ("user", "User provided"), ("network", "Network estimate")], default="user")
    location_description = EncryptedTextField(max_length=255, blank=True)
    area = models.ForeignKey(LocationArea, null=True, blank=True, on_delete=models.SET_NULL, related_name="requests")
    emergency_type = models.CharField(max_length=20, choices=EMERGENCY_TYPES, default="other")
    message = EncryptedTextField(blank=True)
    device_type = models.CharField(max_length=120, blank=True)
    browser = models.CharField(max_length=120, blank=True)
    operating_system = models.CharField(max_length=120, blank=True)
    client_uuid = models.UUIDField(null=True, blank=True, db_index=True)
    ip_address = EncryptedTextField(max_length=64, null=True, blank=True)
    vpn_detected = models.BooleanField(default=False)
    priority = models.CharField(max_length=10, choices=PRIORITIES, default="high")
    tracking_enabled = models.BooleanField(default=False)
    tracking_active = models.BooleanField(default=False)
    tracking_started_at = models.DateTimeField(null=True, blank=True)
    tracking_stopped_at = models.DateTimeField(null=True, blank=True)
    last_location_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.request_id:
            code = area_routing_code(self.area)
            date_code = timezone.localdate().strftime("%Y%m%d")
            unique_code = uuid.uuid4().hex[:6].upper()
            self.request_id = f"EMG-{code}-{date_code}-{unique_code}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.request_id


class LocationPing(models.Model):
    request = models.ForeignKey(EmergencyRequest, on_delete=models.CASCADE, related_name="location_pings")
    latitude = EncryptedDecimalField(max_digits=9, decimal_places=6)
    longitude = EncryptedDecimalField(max_digits=9, decimal_places=6)
    location_accuracy = EncryptedDecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    idempotency_key = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def __str__(self):
        return f"Location update for {self.request.request_id}"


class SecurityEvent(models.Model):
    EVENT_TYPES = [
        ("login_success", "Login succeeded"),
        ("login_failure", "Login failed"),
        ("login_throttled", "Login throttled"),
        ("session_expired", "Session expired"),
        ("access_denied", "Access denied"),
        ("mfa_enabled", "MFA enabled"),
        ("mfa_failure", "MFA failed"),
        ("case_delete_success", "Case data deleted"),
        ("case_delete_failure", "Case data deletion failed"),
    ]
    event_type = models.CharField(max_length=32, choices=EVENT_TYPES)
    user = models.ForeignKey(
        get_user_model(),
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="security_events",
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    path = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=10, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} · {self.created_at:%Y-%m-%d %H:%M}"


class MFAProfile(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE, related_name="mfa_profile")
    secret = EncryptedTextField(blank=True, editable=False)
    enabled = models.BooleanField(default=False)
    last_used_counter = models.BigIntegerField(null=True, blank=True, editable=False)
    confirmed_at = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    def set_secret(self, secret):
        self.secret = secret
        self.enabled = False
        self.last_used_counter = None
        self.confirmed_at = None

    def __str__(self):
        return f"MFA for {self.user.get_username()}"


class Incident(models.Model):
    STATUS_CHOICES = [
        ("new", "New"),
        ("acknowledged", "Acknowledged"),
        ("responding", "Responding"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]
    request = models.OneToOneField(EmergencyRequest, on_delete=models.CASCADE, related_name="incident")
    assigned_area = models.ForeignKey(LocationArea, null=True, blank=True, on_delete=models.SET_NULL, related_name="incidents")
    assigned_admin = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="assigned_incidents")
    similar_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="repeat_incidents")
    similarity_signal = models.CharField(
        max_length=40,
        choices=[
            ("client_uuid", "Client device token"),
        ],
        blank=True,
    )
    similarity_checked_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="new")
    opened_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-request__created_at", "-pk"]

    def save(self, *args, **kwargs):
        if self.assigned_admin_id is None and self.assigned_area_id:
            profile = ResponseProfile.objects.filter(
                active=True,
                user__is_active=True,
                areas=self.assigned_area_id,
            ).select_related("user").order_by("pk").first()
            if profile:
                self.assigned_admin = profile.user
        super().save(*args, **kwargs)

    def __str__(self):
        return self.request.request_id


class EmergencyChatRoom(models.Model):
    incident = models.OneToOneField(Incident, on_delete=models.CASCADE, related_name="emergency_chat_room")
    accepted_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Public chat for {self.incident}"


class EmergencyChatMessage(models.Model):
    CHANNEL_CHOICES = [
        ("text", "Text message"),
        ("audio", "Audio note"),
        ("system", "System event"),
    ]
    SENDER_TYPES = [
        ("public", "Request sender"),
        ("admin", "Responder admin"),
        ("system", "System"),
    ]
    room = models.ForeignKey(EmergencyChatRoom, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="emergency_chat_messages")
    sender_type = models.CharField(max_length=20, choices=SENDER_TYPES)
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="text")
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    body = EncryptedTextField(blank=True, max_length=4000)
    audio = models.FileField(upload_to="emergency_chat_audio/", blank=True)
    audio_duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.sender_type} message for {self.room.incident}"


class EmergencyChatCall(models.Model):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("ended", "Ended"),
    ]
    REQUESTER_TYPES = [
        ("public", "Request sender"),
        ("admin", "Responder admin"),
    ]
    room = models.ForeignKey(EmergencyChatRoom, on_delete=models.CASCADE, related_name="calls")
    requested_by = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="emergency_chat_calls")
    recipient = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="emergency_chat_call_requests")
    requester_type = models.CharField(max_length=20, choices=REQUESTER_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="requested")
    on_hold = models.BooleanField(default=False)
    caller_muted = models.BooleanField(default=False)
    recipient_muted = models.BooleanField(default=False)
    started_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["room"],
                condition=models.Q(status="requested"),
                name="unique_requested_emergency_call",
            ),
        ]

    def __str__(self):
        return f"{self.status} voice call for {self.room.incident}"


class IncidentFavorite(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="favorites")
    user = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="incident_favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["incident", "user"], name="unique_incident_favorite")]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} favorited {self.incident}"


class IncidentNote(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="incident_notes")
    note = EncryptedTextField(max_length=2000)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Note for {self.incident}"


class ReferralDestination(models.Model):
    DESTINATION_TYPES = [
        ("police_station", "Police station"),
        ("hospital", "Hospital"),
        ("government", "Government institution"),
        ("company", "Company / organisation"),
    ]
    name = models.CharField(max_length=180)
    destination_type = models.CharField(max_length=30, choices=DESTINATION_TYPES)
    area = models.ForeignKey(LocationArea, null=True, blank=True, on_delete=models.SET_NULL, related_name="referral_destinations")
    assigned_admin = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="referral_destinations")
    contact = EncryptedTextField(max_length=160, blank=True)
    email = EncryptedTextField(max_length=254, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["destination_type", "name"]

    def __str__(self):
        return self.name


class Recording(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="recordings")
    file = models.FileField(upload_to="emergency_recordings/")
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Recording for {self.incident}"


class Referral(models.Model):
    TARGET_TYPES = [
        ("admin", "Another responder admin"),
        ("person", "Person"),
        ("police_station", "Police station"),
        ("hospital", "Hospital"),
        ("company", "Company / organisation"),
        ("government", "Government institution"),
        ("organization", "Organisation / office"),
    ]
    CHANNELS = [
        ("in_app", "In-app transfer"),
        ("whatsapp", "WhatsApp"),
        ("email", "Email / Gmail"),
        ("sms", "SMS / Messages"),
    ]
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="referrals")
    referred_by = models.ForeignKey(get_user_model(), on_delete=models.PROTECT, related_name="referrals_made")
    target_type = models.CharField(max_length=20, choices=TARGET_TYPES)
    target_name = models.CharField(max_length=160)
    target_contact = EncryptedTextField(max_length=160)
    channel = models.CharField(max_length=20, choices=CHANNELS)
    message = EncryptedTextField()
    destination = models.ForeignKey(ReferralDestination, null=True, blank=True, on_delete=models.SET_NULL, related_name="referrals")
    destination_area = models.ForeignKey(LocationArea, null=True, blank=True, on_delete=models.SET_NULL, related_name="direct_referrals")
    recipient_admin = models.ForeignKey(get_user_model(), null=True, blank=True, on_delete=models.SET_NULL, related_name="received_referrals")
    referral_token_hash = models.CharField(max_length=64, blank=True, editable=False)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    read_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.incident} → {self.target_name}"


class InstitutionProfile(models.Model):
    INSTITUTION_TYPES = [
        ("police", "Police station"),
        ("hospital", "Hospital"),
    ]
    user = models.OneToOneField(get_user_model(), null=True, blank=True, on_delete=models.CASCADE, related_name="institution_profile")
    username = models.CharField(max_length=150, unique=True)
    institution_type = models.CharField(max_length=20, choices=INSTITUTION_TYPES)
    institution_name = models.CharField(max_length=180)
    area = models.ForeignKey(LocationArea, on_delete=models.PROTECT, related_name="institution_profiles")
    hospital_facility = models.ForeignKey(HospitalFacility, null=True, blank=True, on_delete=models.SET_NULL, related_name="institution_profiles")
    phone_number = EncryptedTextField(max_length=32, blank=True)
    active = models.BooleanField(default=True)
    force_password_change = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["institution_type", "institution_name"]

    def save(self, *args, **kwargs):
        user_model = get_user_model()
        if self.user_id is None:
            self.user = user_model.objects.create_user(
                username=self.username,
                password="2564",
                is_active=self.active,
            )
        else:
            self.user.username = self.username
            self.user.is_active = self.active
            self.user.save(update_fields=["username", "is_active"])
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.institution_name} · {self.area}"


class CaseMessage(models.Model):
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE, related_name="messages")
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, related_name="case_messages")
    sender = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="sent_case_messages")
    recipient = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="received_case_messages")
    body = EncryptedTextField(max_length=4000)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message for {self.referral}"


class CallRequest(models.Model):
    STATUS_CHOICES = [
        ("requested", "Requested"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("completed", "Completed"),
    ]
    referral = models.ForeignKey(Referral, on_delete=models.CASCADE, related_name="call_requests")
    caller = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="calls_started")
    recipient = models.ForeignKey(get_user_model(), on_delete=models.CASCADE, related_name="calls_received")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="requested")
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["referral"],
                condition=models.Q(status="requested"),
                name="unique_requested_referral_call",
            ),
        ]

    def __str__(self):
        return f"Call request for {self.referral}"
