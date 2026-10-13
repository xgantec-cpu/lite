from django.contrib import admin
from django import forms

from .models import CallRequest, CaseMessage, EmergencyChatCall, EmergencyChatMessage, EmergencyChatRoom, EmergencyRequest, HospitalFacility, Incident, IncidentFavorite, IncidentNote, InHouseConversation, InHouseMessage, InstitutionProfile, LocationArea, LocationPing, MFAProfile, OperationsAccess, Recording, Referral, ResponseProfile, SecurityEvent


class ResponseProfileAdminForm(forms.ModelForm):
    class Meta:
        model = ResponseProfile
        fields = "__all__"

    def clean_areas(self):
        areas = self.cleaned_data["areas"]
        if areas.count() > 4:
            raise forms.ValidationError("Each responder can be assigned a maximum of four districts.")
        if self.cleaned_data.get("active") and areas.exists():
            assigned_elsewhere = ResponseProfile.objects.filter(
                active=True,
                areas__in=areas,
            ).exclude(pk=self.instance.pk).distinct()
            if assigned_elsewhere.exists():
                raise forms.ValidationError("Each active district can be assigned to only one responder.")
        return areas


@admin.register(LocationArea)
class LocationAreaAdmin(admin.ModelAdmin):
    list_display = ("name", "routing_code", "district", "region", "active")
    list_filter = ("active", "district", "region")
    search_fields = ("name", "routing_code", "district", "region")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(HospitalFacility)
class HospitalFacilityAdmin(admin.ModelAdmin):
    list_display = ("name", "district", "ownership", "level", "active")
    list_filter = ("ownership", "active", "district")
    search_fields = ("name", "district__name", "external_id")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(ResponseProfile)
class ResponseProfileAdmin(admin.ModelAdmin):
    form = ResponseProfileAdminForm
    list_display = ("user", "role", "active", "phone_number")
    list_filter = ("role", "active")
    search_fields = ("user__username", "user__first_name", "user__last_name")
    filter_horizontal = ("areas",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(InHouseConversation)
class InHouseConversationAdmin(admin.ModelAdmin):
    list_display = ("user_one", "user_two", "updated_at")
    search_fields = ("user_one__username", "user_two__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(InHouseMessage)
class InHouseMessageAdmin(admin.ModelAdmin):
    list_display = ("conversation", "sender", "recipient", "created_at", "read_at")
    search_fields = ("sender__username", "recipient__username")
    list_filter = ("read_at", "created_at")
    readonly_fields = ("created_at",)


@admin.register(InstitutionProfile)
class InstitutionProfileAdmin(admin.ModelAdmin):
    list_display = ("institution_name", "institution_type", "username", "area", "hospital_facility", "active", "force_password_change")
    list_filter = ("institution_type", "active", "area")
    search_fields = ("institution_name", "username", "area__name", "hospital_facility__name")
    readonly_fields = ("user", "created_at", "default_passcode_note")
    fields = (
        "username", "institution_type", "institution_name", "area", "hospital_facility", "phone_number",
        "active", "force_password_change", "default_passcode_note", "user", "created_at",
    )

    @admin.display(description="Initial passcode")
    def default_passcode_note(self, obj):
        return "New institution accounts start with passcode 2564. Require a change after first sign-in."

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class OperationsAccessAdminForm(forms.ModelForm):
    passcode = forms.CharField(
        label="Level five passcode",
        min_length=8,
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Use at least eight characters. The passcode is stored securely, never as plain text.",
    )
    confirm_passcode = forms.CharField(
        label="Confirm passcode",
        required=False,
        strip=False,
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = OperationsAccess
        fields = ("label",)

    def clean(self):
        cleaned_data = super().clean()
        passcode = cleaned_data.get("passcode")
        confirmation = cleaned_data.get("confirm_passcode")
        if not self.instance.pk and not passcode:
            raise forms.ValidationError("Set a passcode before saving the Operations Center access.")
        if passcode and passcode != confirmation:
            raise forms.ValidationError("The passcode and confirmation do not match.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.cleaned_data.get("passcode"):
            instance.set_passcode(self.cleaned_data["passcode"])
        if commit:
            instance.save()
        return instance


@admin.register(OperationsAccess)
class OperationsAccessAdmin(admin.ModelAdmin):
    form = OperationsAccessAdminForm
    list_display = ("label", "updated_at")
    readonly_fields = ("passcode_hash", "updated_at")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser and not OperationsAccess.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmergencyRequest)
class EmergencyRequestAdmin(admin.ModelAdmin):
    list_display = ("request_id", "emergency_type", "priority", "area", "phone_number", "client_reference", "created_at", "vpn_detected")
    list_filter = ("priority", "emergency_type", "area", "vpn_detected", "created_at")
    search_fields = ("request_id", "client_uuid")
    readonly_fields = ("request_id", "client_uuid", "created_at", "ip_address", "browser")
    date_hierarchy = "created_at"

    @admin.display(description="Client reference", ordering="client_uuid")
    def client_reference(self, obj):
        return str(obj.client_uuid)[:8] if obj.client_uuid else "Not activated"

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LocationPing)
class LocationPingAdmin(admin.ModelAdmin):
    list_display = ("request", "latitude", "longitude", "location_accuracy", "created_at")
    search_fields = ("request__request_id",)
    list_filter = ("created_at",)
    readonly_fields = ("request", "latitude", "longitude", "location_accuracy", "idempotency_key", "created_at")


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "event_type", "user", "ip_address", "path")
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username", "ip_address", "path")
    readonly_fields = ("event_type", "user", "ip_address", "path", "method", "details", "created_at")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MFAProfile)
class MFAProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "enabled", "confirmed_at", "updated_at")
    list_filter = ("enabled", "confirmed_at")
    search_fields = ("user__username", "user__email")
    exclude = ("secret",)
    readonly_fields = ("user", "enabled", "last_used_counter", "confirmed_at", "updated_at")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("request", "status", "assigned_area", "assigned_admin", "similar_case", "priority", "updated_at")
    list_filter = ("status", "assigned_area", "request__priority", "similarity_signal")
    search_fields = ("request__request_id", "similar_to__request__request_id")
    list_select_related = ("request", "assigned_area", "assigned_admin", "similar_to", "similar_to__request")
    autocomplete_fields = ("assigned_admin",)
    readonly_fields = ("similar_to", "similarity_signal", "similarity_checked_at")

    @admin.display(description="Similar case", ordering="similar_to__request__request_id")
    def similar_case(self, obj):
        return obj.similar_to.request.request_id if obj.similar_to_id else "—"

    @admin.display(description="Priority", ordering="request__priority")
    def priority(self, obj):
        return obj.request.get_priority_display()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(IncidentFavorite)
class IncidentFavoriteAdmin(admin.ModelAdmin):
    list_display = ("incident", "user", "created_at")
    search_fields = ("incident__request__request_id", "user__username")
    readonly_fields = ("created_at",)


@admin.register(IncidentNote)
class IncidentNoteAdmin(admin.ModelAdmin):
    list_display = ("incident", "author", "created_at")
    search_fields = ("incident__request__request_id", "author__username")
    readonly_fields = ("created_at",)


@admin.register(Recording)
class RecordingAdmin(admin.ModelAdmin):
    list_display = ("incident", "duration_seconds", "created_at")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Referral)
class ReferralAdmin(admin.ModelAdmin):
    list_display = ("incident", "target_name", "target_type", "recipient_admin", "channel", "referred_by", "created_at")
    list_filter = ("target_type", "channel", "created_at")
    search_fields = ("incident__request__request_id", "target_name")
    readonly_fields = ("created_at", "archived_at")


@admin.register(CaseMessage)
class CaseMessageAdmin(admin.ModelAdmin):
    list_display = ("incident", "sender", "recipient", "created_at", "read_at")
    search_fields = ("incident__request__request_id", "sender__username", "recipient__username")
    readonly_fields = ("created_at",)


@admin.register(CallRequest)
class CallRequestAdmin(admin.ModelAdmin):
    list_display = ("referral", "caller", "recipient", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("referral__incident__request__request_id", "caller__username", "recipient__username")
    readonly_fields = ("created_at", "responded_at")


@admin.register(EmergencyChatRoom)
class EmergencyChatRoomAdmin(admin.ModelAdmin):
    list_display = ("incident", "accepted_at", "expires_at", "updated_at")
    list_filter = ("accepted_at", "expires_at")
    search_fields = ("incident__request__request_id",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(EmergencyChatMessage)
class EmergencyChatMessageAdmin(admin.ModelAdmin):
    list_display = ("room", "channel", "sender_type", "sender", "created_at", "read_at")
    list_filter = ("channel", "sender_type", "created_at")
    search_fields = ("room__incident__request__request_id",)
    readonly_fields = ("created_at",)


@admin.register(EmergencyChatCall)
class EmergencyChatCallAdmin(admin.ModelAdmin):
    list_display = ("room", "requester_type", "recipient", "status", "created_at", "responded_at")
    list_filter = ("status", "requester_type", "created_at")
    search_fields = ("room__incident__request__request_id", "recipient__username")
    readonly_fields = ("created_at", "responded_at")
