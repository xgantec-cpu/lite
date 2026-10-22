import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import incidents.fields


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("incidents", "0041_chat_attachments"),
    ]

    operations = [
        migrations.CreateModel(
            name="AreaAlert",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("body", incidents.fields.EncryptedTextField(max_length=600)),
                ("issue_type", models.CharField(blank=True, max_length=20)),
                ("case_count_snapshot", models.PositiveIntegerField(default=0)),
                (
                    "delivery_status",
                    models.CharField(
                        choices=[
                            ("pending", "Pending delivery"),
                            ("sent", "Delivered"),
                            ("partial", "Partially delivered"),
                            ("failed", "Delivery failed"),
                            ("no_subscribers", "No opted-in subscribers"),
                            ("not_configured", "Push service not configured"),
                        ],
                        default="pending",
                        max_length=20,
                    ),
                ),
                ("recipient_count", models.PositiveIntegerField(default=0)),
                ("failed_count", models.PositiveIntegerField(default=0)),
                ("idempotency_key", models.CharField(editable=False, max_length=64, unique=True)),
                ("sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="public_alerts",
                        to="incidents.locationarea",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="public_area_alerts",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-pk"],
                "indexes": [
                    models.Index(fields=["area", "created_at"], name="incidents_a_area_id_9b79bc_idx"),
                    models.Index(fields=["delivery_status", "created_at"], name="incidents_a_deliver_1809a4_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="PublicAlertSubscription",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("endpoint_hash", models.CharField(editable=False, max_length=64, unique=True)),
                ("endpoint", incidents.fields.EncryptedTextField(max_length=2048)),
                ("p256dh", incidents.fields.EncryptedTextField(max_length=255)),
                ("auth", incidents.fields.EncryptedTextField(max_length=255)),
                ("client_uuid", models.UUIDField(blank=True, db_index=True, null=True)),
                ("user_agent", models.CharField(blank=True, max_length=300)),
                ("active", models.BooleanField(default=True)),
                ("last_seen_at", models.DateTimeField(auto_now=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "area",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="public_alert_subscriptions",
                        to="incidents.locationarea",
                    ),
                ),
            ],
            options={
                "ordering": ["-last_seen_at", "-pk"],
                "indexes": [
                    models.Index(fields=["area", "active"], name="incidents_p_area_id_f46542_idx"),
                ],
            },
        ),
    ]
