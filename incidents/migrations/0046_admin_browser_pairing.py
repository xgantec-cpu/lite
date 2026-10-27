import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import incidents.fields


class Migration(migrations.Migration):

    dependencies = [
        ("incidents", "0045_national_area_alerts"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminBrowserPairing",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("pairing_token_hash", models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ("pairing_expires_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("endpoint_hash", models.CharField(blank=True, editable=False, max_length=64, null=True, unique=True)),
                ("endpoint", incidents.fields.EncryptedTextField(blank=True, editable=False, max_length=2048)),
                ("p256dh", incidents.fields.EncryptedTextField(blank=True, editable=False, max_length=255)),
                ("auth", incidents.fields.EncryptedTextField(blank=True, editable=False, max_length=255)),
                ("device_label", models.CharField(blank=True, max_length=120)),
                ("active", models.BooleanField(default=False)),
                ("paired_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("last_seen_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("critical_alert_enabled", models.BooleanField(default=True)),
                ("critical_alert_threshold", models.PositiveSmallIntegerField(default=2)),
                ("last_critical_alert_count", models.PositiveIntegerField(default=0, editable=False)),
                ("last_critical_alert_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="admin_browser_pairing",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
