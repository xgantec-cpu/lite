# Rapid Response Emergency Assistance System

## 1. The idea in one sentence

This system helps a person ask for emergency help, then sends the request to the correct response team quickly and safely.

## 2. A very simple story

Imagine someone in Masaka is in danger.

1. The person opens the website.
2. The website asks for the person's location.
3. The person sends a short message, or sends a quick video.
4. The system gives the request a reference number.
5. The system sends the request to the responder responsible for that district.
6. The responder sees the case on a map, talks to the sender, and takes action.
7. If more help is needed, the responder sends the case to a police station, hospital, or another official.

The main goal is simple: **the right person should see the right emergency without wasting time.**

## 3. The problem this project solves

Many emergency reports are difficult to manage because:

- A report can be sent to the wrong office.
- Important location information can be missing.
- A responder may not know which cases are new.
- Police, hospitals, and response teams may not share one communication space.
- It is hard to follow what happened to a case.
- Sensitive information needs protection.

Rapid Response brings these activities into one organized system.

## 4. Who uses the system?

### A. Person asking for help

The public user can:

- Open the public emergency page.
- Allow location sharing using the browser GPS feature.
- Enter a phone number, district, emergency type, and message.
- Send a short emergency video.
- Continue chatting with the response team.
- Send audio notes and files in the secure chat.
- Request a real voice call when the browser and network allow it.

### B. District responder or mini-admin

The responder can:

- Sign in to the responder dashboard.
- See only cases assigned to their districts.
- See new and already opened cases separately.
- Open a case and view its map location.
- See device, browser, location, and emergency information.
- Add notes and mark a case as a favorite.
- Update the case status.
- Chat with official partners.
- Send files and make a live voice call through the chat.
- Refer the case to a police station, hospital, or another responder.
- Print or save a report as a PDF.

### C. Police or hospital officer

The institution officer can:

- Sign in using the account created for the institution.
- See forwarded cases.
- See new cases and archived cases.
- Open the case map.
- Chat with the referring responder.
- Send files and use the live voice call controls.
- Archive a case after action is complete.

### D. Parent administrator

The parent administrator manages the system from Django Admin. They can:

- Create and deactivate responder accounts.
- Assign districts to responders.
- Manage police stations and hospitals.
- Manage referral destinations.
- Manage system access and passcodes.
- Review the full operations center.
- Manage security and multi-factor authentication settings.

## 5. How one emergency moves through the system

```text
Public user
    ↓
Emergency form or quick video
    ↓
Location and district routing
    ↓
Assigned district responder
    ↓
Chat, map, notes, referral, and status update
    ↓
Police / hospital / another official
    ↓
Archive and final report
```

### Case statuses

- **New:** The request has arrived and needs attention.
- **Acknowledged:** A responder has seen the request.
- **Responding:** The team is actively helping.
- **Resolved:** The emergency has been handled.
- **Closed:** The case is finished and ready for archive or review.

When a responder opens or acts on a case, it leaves the main attention queue. This keeps the new-case area clear.

## 6. Important features to demonstrate

### Location and maps

The system uses the browser's HTML5 geolocation feature. With permission, the user's coordinates can be shown on the case map. If no usable coordinates are available, the case clearly says that the location is not tagged instead of inventing a location.

The dashboard can show:

- The originating location.
- The district responsible for the case.
- The location trail for an eligible active case.
- Other cases handled by the responder.
- Uganda district boundary information.

On the travel-watch page, the server can use Google's traffic-aware Routes API to calculate the road distance, drive time, and traffic delay from the traveller's GPS position to the destination. The map labels conditions as light, moderate, or heavy and shows the delay. If `GOOGLE_MAPS_API_KEY` is not configured or Google cannot respond, the page clearly falls back to an approximate route instead of inventing traffic data.

### Quick video help

Someone in danger may not have time to type. The quick video page gives them a large record button. It can use the front or back camera, record a short clip, and send the video with the emergency request.

### Secure communication

The chat system supports:

- Text messages.
- Audio notes.
- File attachments.
- Live updates through Django Channels.
- Real browser voice calls using WebRTC.
- Microphone status, mute, speaker, answer, decline, and end-call controls.

Voice calls require HTTPS, microphone permission, and a working ASGI/WebSocket service. A TURN server is recommended for production networks where two phones cannot connect directly.

The application reads the browser ICE server list from `RTC_ICE_SERVERS`. Keep the public STUN entry and add a TURN entry with a short-lived username and credential, for example:

```text
RTC_ICE_SERVERS=[{"urls":["stun:stun.l.google.com:19302"]},{"urls":["turn:turn.example.com:3478"],"username":"temporary-user","credential":"temporary-password"}]
```

The TURN credential is sent to the browser because WebRTC needs it to relay audio; use temporary credentials and rotate them. Django Channels carries call signaling, while the media travels directly between browsers or through TURN when direct routing is unavailable.

### Referrals

A responder can choose where a case should go. The destination can be:

- Another responder.
- A police station.
- A hospital.
- A government office.
- A company or other configured organization.

The referral keeps the case information, coordinates, message history, and reference number together.

### Reports

The report button lets an authorized user choose what to print. The report can contain the full page, selected sections, graphs, district information, and a date filter. The browser print window can save the report as a PDF.

## 7. Why the system is safe and reliable

These are strong presentation points:

1. **District-based routing:** A case is sent to the responder responsible for its area.
2. **Access control:** A responder cannot freely open every district's cases.
3. **Encrypted sensitive fields:** Important contacts, locations, and messages are protected in the database.
4. **MFA support:** Approved officials can use a second authentication step.
5. **Idempotency:** Repeated requests do not create duplicate case records.
6. **Protected media:** Videos, audio notes, and files are served through permission-checked endpoints.
7. **Rate limits:** Repeated abusive requests are slowed down.
8. **Audit events:** Important sign-ins, blocked access, and security actions can be recorded.
9. **Session protection:** Inactive responder sessions can lock automatically.
10. **Clear status history:** Teams can understand what happened to a case.

Do not say that the system is perfect or that GPS is guaranteed. A strong presentation is honest: permission, browser support, network quality, and deployment configuration affect some features.

## 8. A five-minute presentation plan

### Minute 1: Explain the problem

Say:

> “When an emergency report is sent, speed and correct routing matter. Our system connects the person asking for help to the official responsible for that district.”

### Minute 2: Demonstrate the public page

1. Open `/`.
2. Allow location in the browser.
3. Select a district and emergency type.
4. Send a short sample message.
5. Show the generated emergency reference.

### Minute 3: Demonstrate the responder dashboard

1. Open `/dashboard/login/`.
2. Sign in as an approved responder.
3. Show that the responder sees assigned districts, not unrelated cases.
4. Open one case.
5. Show the map, case details, status, favorite button, and notes.

### Minute 4: Demonstrate communication and referral

1. Open the secure chat.
2. Send a file or audio note.
3. Show the voice call controls and microphone status.
4. Refer the case to a police station or hospital.
5. Open the institution portal and show the forwarded case.

### Minute 5: Demonstrate accountability

1. Update the case status.
2. Show that it leaves the new-case queue.
3. Open the report builder.
4. Print or save a selected report as PDF.
5. End with the impact statement below.

## 9. Strong points to say to the judges

### Human impact

> “This is not just a form. It is a response chain that keeps the emergency, location, people, communication, and actions connected.”

### Local design

> “The system is designed around Uganda's districts, local response teams, police stations, hospitals, and real network conditions.”

### Speed

> “The quick video option helps a person communicate when typing is too slow or unsafe.”

### Accountability

> “Every case has a reference, a status, an assigned responder, notes, referrals, and a reportable history.”

### Privacy

> “The system uses permission-based location, controlled access, encrypted sensitive data, protected media, and multi-factor authentication.”

### Growth

> “The design can grow from a district pilot into a wider emergency coordination network because routing, referrals, institutions, and communication are separated into clear parts.”

## 10. A short closing statement

> “Rapid Response turns a cry for help into an organized action. It helps the right official see the right case, understand where it started, communicate with the sender, involve the correct institution, and keep a record of the response. Saving lives is better than simply collecting information.”

## 11. Running the system locally

### First setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Keep the virtual environment active while running Django. Public browser alerts
require the `pywebpush` and `py-vapid` packages installed by `requirements.txt`.

Open these pages:

| Purpose | Address |
| --- | --- |
| Public emergency page | `http://127.0.0.1:8000/` |
| Safety alerts and travel watch | `http://127.0.0.1:8000/alerts/` |
| Quick video help | `http://127.0.0.1:8000/quick-help/` |
| Responder login | `http://127.0.0.1:8000/dashboard/login/` |
| Main administration | `http://127.0.0.1:8000/admin/` |
| Institution login | `http://127.0.0.1:8000/institution/login/` |

After creating a superuser, open Django Admin and create the areas, responder profiles, assigned districts, hospitals, police stations, and other accounts needed for the demonstration.

### SQLite and PostgreSQL

SQLite is convenient for a small local demonstration. PostgreSQL is the better choice for a real deployment with many users. Configure PostgreSQL with `DATABASE_URL`. To explicitly use SQLite, set `DJANGO_USE_SQLITE=1`.

### Production checklist

Before publishing the system:

- Set `DJANGO_DEBUG=0`.
- Set a long, private `DJANGO_SECRET_KEY`.
- Set a separate field-encryption key and back it up safely.
- Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`.
- Use HTTPS.
- Use an ASGI server such as Daphne for WebSockets.
- Set `REDIS_URL` when using multiple workers.
- Use PostgreSQL for important data.
- Configure a TURN server for reliable voice calls.
- Change every temporary password before the demonstration or launch.
- Back up the database and encryption key separately.

Never place real passwords, database passwords, encryption keys, or private `.env` files in GitHub.

## 12. Troubleshooting during a demonstration

### The microphone does not work

Check that the page uses HTTPS, the browser was allowed to use the microphone, and no other application is blocking it. On a phone, open the page in a normal browser rather than an in-app preview.

### Chat does not update immediately

The application must run through ASGI for WebSockets. Check the WebSocket service and `REDIS_URL` in a multi-worker deployment. The application keeps polling as a fallback, but live calls need the WebSocket channel.

### GPS is missing

Use HTTPS, allow location, and test outdoors or near a window. If the browser cannot provide coordinates, the system should show “Location not tagged” rather than pretend that the user is somewhere else.

### Styles or images are missing after deployment

Run:

```bash
python3 manage.py collectstatic --noinput
```

Then confirm that the web service is serving `STATIC_ROOT` correctly.

## 13. Honest next improvements

The strongest next steps are:

- Add a production TURN service for voice calls.
- Connect approved SMS, email, or WhatsApp provider APIs.
- Add automated backups and restore testing.
- Add monitoring and alerts for failed messages.
- Conduct a privacy review and define exact data-retention periods.
- Load-test the system with realistic emergency traffic.
- Add more accessibility and language options.
- Pilot the system with real response officers before a large launch.

These improvements do not weaken the project. They show that the team understands the difference between a working prototype and a safe public service.

## 14. Simple glossary

- **Case:** One emergency report in the system.
- **District responder:** The official responsible for selected districts.
- **Referral:** Sending a case to another official or institution.
- **GPS:** A browser feature that can provide a device's location after permission.
- **WebSocket:** A live connection used for fast chat updates.
- **WebRTC:** Browser technology used for live voice communication.
- **MFA:** Multi-factor authentication; it asks for more than one proof of identity.
- **Idempotency:** A safety rule that prevents one action from being saved twice.
- **ASGI:** The server interface needed for Django Channels and live WebSockets.
- **TURN:** A relay service that helps voice calls connect when direct connection fails.

## 15. Community area alerts

The global case map includes a protected **Send an area alert** panel. A responder chooses an assigned district, selects an issue group, and writes a public-safe message. Authorized responders can send a verified warning immediately, even before several similar cases are recorded, so an early security issue can reach opted-in residents quickly.

Residents must opt in from the public emergency page and choose the district where they want alerts. The system stores the browser push subscription for that district, not an exact home location. Alerts never include names, phone numbers, case references, or exact incident coordinates.

The **Safety alerts and travel watch** page lets a subscriber save several districts, such as home and work. A traveller can use GPS for the starting point and choose a destination district; the system builds an alert corridor from the Uganda boundary data. When configured, Google traffic-aware routing supplies the road line, distance, drive time, and congestion delay. This remains a safety-watch route rather than guaranteed turn-by-turn navigation, so travellers must still confirm their actual road route.

The project uses the browser Web Push standard with VAPID keys. It is the lowest-cost option because it does not require SMS or WhatsApp fees. It requires HTTPS, browser permission, a service worker, and `WEBPUSH_VAPID_PUBLIC_KEY`, `WEBPUSH_VAPID_PRIVATE_KEY`, and `WEBPUSH_VAPID_SUBJECT` environment variables. If push is not configured, the alert is still recorded in the audit log and the dashboard explains that delivery is unavailable.
