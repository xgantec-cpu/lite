from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("incidents", "0038_encrypt_sensitive_fields_and_mfa"),
    ]

    operations = [
        migrations.AlterField(
            model_name="securityevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("login_success", "Login succeeded"),
                    ("login_failure", "Login failed"),
                    ("login_throttled", "Login throttled"),
                    ("session_expired", "Session expired"),
                    ("access_denied", "Access denied"),
                    ("mfa_enabled", "MFA enabled"),
                    ("mfa_failure", "MFA failed"),
                    ("case_delete_success", "Case data deleted"),
                    ("case_delete_failure", "Case data deletion failed"),
                ],
                max_length=32,
            ),
        ),
    ]
