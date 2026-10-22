import time

from django.conf import settings
from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from urllib.parse import urlencode


class WorkspaceInactivityMiddleware:
    """Expire authenticated responder and institution sessions after five minutes."""

    timeout_seconds = 5 * 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and self._is_workspace_path(request):
            now = int(time.time())
            last_activity = request.session.get("workspace_last_activity")
            if last_activity and now - last_activity > self.timeout_seconds:
                logout(request)
                if self._expects_json(request):
                    response = JsonResponse({"error": "Your session expired after five minutes of inactivity."}, status=401)
                    return self._secure_workspace_response(request, response)
                login_path = "/institution/login/" if request.path.startswith("/institution/") else "/dashboard/login/"
                response = redirect(f"{login_path}?reason=inactivity")
                return self._secure_workspace_response(request, response)
            request.session["workspace_last_activity"] = now
        response = self.get_response(request)
        return self._secure_workspace_response(request, response)

    @staticmethod
    def _is_workspace_path(request):
        path = request.path
        if path.startswith(("/dashboard/", "/institution/")):
            return True
        if path == "/session/keepalive/":
            return True
        if path.startswith("/chat/"):
            has_public_session = bool(request.session.get("request_id"))
            has_public_token = bool(request.GET.get("access") or request.POST.get("access"))
            return not (has_public_session or has_public_token)
        return False

    @staticmethod
    def _expects_json(request):
        return request.path.startswith("/chat/") or "application/json" in request.headers.get("Accept", "")

    @staticmethod
    def _secure_workspace_response(request, response):
        if request.path.startswith(("/dashboard/", "/institution/", "/chat/", "/inhouse/", "/admin/", "/auth/mfa/", "/track/", "/session/")):
            response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response["Pragma"] = "no-cache"
            response["Expires"] = "0"
            response["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=(self)"
        return response


class AdminMFAEnforcementMiddleware:
    """Require the same MFA challenge for authenticated Django admin sessions."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        profile = getattr(request.user, "mfa_profile", None) if request.user.is_authenticated else None
        if (
            (settings.MFA_REQUIRED or bool(profile and profile.enabled))
            and request.path.startswith("/admin/")
            and request.path not in {"/admin/login/", "/admin/logout/"}
            and request.user.is_authenticated
            and request.user.is_superuser
            and request.session.get("mfa_verified_user") != request.user.pk
        ):
            request.session["mfa_pending_user_id"] = request.user.pk
            request.session["mfa_pending_surface"] = "admin"
            request.session["mfa_return_path"] = request.get_full_path()
            request.session["mfa_started_at"] = int(time.time())
            has_mfa = bool(profile and profile.enabled)
            return redirect("mfa_verify" if has_mfa else "mfa_setup")
        return self.get_response(request)


class AdminSectionPasswordMiddleware:
    """Require the dashboard admin-section password before Django admin access."""

    timeout_seconds = 10 * 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/admin/"):
            unlocked_at = request.session.get("admin_section_unlocked_at")
            if not unlocked_at or int(time.time()) - int(unlocked_at) > self.timeout_seconds:
                request.session.pop("admin_section_unlocked_at", None)
                gate_url = reverse("admin_section_gate")
                return redirect(f"{gate_url}?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)
