# Emergency Assistance and Rapid Response System

> **Full presentation and user documentation:** [docs/SYSTEM_DOCUMENTATION.md](docs/SYSTEM_DOCUMENTATION.md)

This is the first Django MVP for a location-aware emergency request platform.

## Included

- Anonymous public emergency request form with phone number, area, landmark, category, priority, and optional GPS coordinates.
- Device location capture with a manual-location fallback.
- Automatic creation of an `EmergencyRequest` and an `Incident`.
- Configurable areas for location-based queues.
- Django Admin management for incidents, areas, response profiles, and recordings.
- Incident statuses: New, Acknowledged, Responding, Resolved, and Closed.
- Active/inactive controls for response profiles and standard Django admin users.
- Idempotent emergency submissions, messages, notes, referrals, and call requests with database uniqueness safeguards.
- Authenticated responder/institution endpoint checks, CSRF protection, upload limits, rate limits, and server-side five-minute inactivity locks.
- Security-event records for responder and institution sign-ins, throttling, session expiry, and denied case access.
- Protected recording and audio endpoints so emergency media is not exposed through direct public file URLs.
- Application-level encryption for incident contacts, coordinates, descriptions, messages, referral details, and MFA secrets.
- TOTP multi-factor authentication for responder, institution, and production Django admin access, with replay protection.
- PostgreSQL configuration through `DATABASE_URL`, with an explicit `DJANGO_USE_SQLITE=1` option for SQLite deployments.
- A separate parent-administrator password gate protects the Django admin section from the responder dashboard.

## Run locally

```bash
python3 manage.py migrate
python3 manage.py createsuperuser
python3 manage.py runserver
```

Open `http://127.0.0.1:8000/` for the public form and `/admin/` for operations.

Create `LocationArea` records in the admin before directing users to the form. Create response profiles and assign them to areas to define the operational ownership.

Local development can use SQLite with WAL mode, foreign-key enforcement, and a busy timeout. Production uses PostgreSQL through `DATABASE_URL`; do not run production responders against a shared SQLite file.

To explicitly use SQLite, set `DJANGO_USE_SQLITE=1`. On Render, SQLite data is stored on the service filesystem and can be lost when the service is redeployed or restarted unless a persistent disk is attached. PostgreSQL is recommended for production responders.

To use PostgreSQL locally, export a connection string before running Django:

```bash
export DATABASE_URL='postgresql://user:password@127.0.0.1:5432/rapid_response?sslmode=prefer'
python3 manage.py migrate
python3 manage.py runserver
```

Copy `.env.example` for deployment configuration. Keep the real `.env`, database password, Django secret, and field-encryption key outside source control.

## WebSockets and district boundaries

The emergency and in-app referral chats use Django Channels over WebSockets,
with signed, expiring per-page access tokens and HTTP polling retained as a
degraded-network fallback. Local development uses an in-memory channel layer.
Production should set `REDIS_URL` and run an ASGI server, for example
`daphne -b 0.0.0.0 -p 8000 emergency_platform.asgi:application`.

Incident maps and GPS routing use the bundled Uganda district polygons in
`incidents/data/uganda_districts.geojson`. The file covers 136 districts;
legacy city records outside that boundary release still use the user's chosen
area as a safe fallback and are not treated as polygon-verified.

## Responder dashboard

Mini-admins sign in at `http://127.0.0.1:8000/dashboard/login/`. A main administrator enables access by creating a `ResponseProfile`, setting it active, and assigning one or more areas. The dashboard only exposes incidents assigned to those areas. Superusers can see the full queue. Mini-admins can update incidents through `New`, `Acknowledged`, `Responding`, `Resolved`, and `Closed`.

## Next integrations

Before deployment, set either `DATABASE_URL=postgresql://user:password@host:5432/database?sslmode=require` or `DJANGO_USE_SQLITE=1`, along with a strong `DJANGO_SECRET_KEY`, a separately stored Fernet `DJANGO_FIELD_ENCRYPTION_KEY`, `DJANGO_DEBUG=0`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DJANGO_SECURE_COOKIES=1` over HTTPS. MFA is required automatically when debug mode is disabled; `DJANGO_MFA_REQUIRED=1` can enforce it explicitly. Override the development admin-gate password with `DJANGO_ADMIN_SECTION_PASSWORD` or provide a precomputed `DJANGO_ADMIN_SECTION_PASSWORD_HASH`. Set `DJANGO_CASE_DELETE_PASSWORD=778899` (or provide `DJANGO_CASE_DELETE_PASSWORD_HASH`) to enable the parent-admin passcode required for permanent solved-case deletion. Set `DJANGO_TRUST_PROXY_HEADERS=1` only when a trusted HTTPS reverse proxy overwrites forwarding headers. The production cookie, HSTS, content-type, referrer, and SSL settings are enabled when debug mode is disabled. Use `REDIS_URL` for Channels if more than one worker is used. Back up the encryption key separately from PostgreSQL, and test key-and-database restoration together. Do not treat IP/VPN detection as proof of a user's location; device GPS or user-confirmed location is preferred.
The dashboard's main view contains only new incidents that need attention. Once a responder acknowledges or advances a case, it moves to the Cases archive. From an incident page, a responder can prepare a referral to a person or organisation and choose WhatsApp, Email/Gmail, or SMS/Messages. The system records the referral and provides the appropriate channel link; live provider APIs can be connected later for automated sending.

Browser voice calls use Django Channels for signaling and WebRTC for audio. Set `RTC_ICE_SERVERS` to a JSON list containing STUN and a short-lived TURN credential; STUN alone often fails between phones on different mobile networks. Use HTTPS and an ASGI server for production calls.

# helpug
# helpug
# helpug
# helpug
# lite
# lite
