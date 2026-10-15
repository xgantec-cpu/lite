from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("incidents", "0039_case_deletion_audit_events"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emergencyrequest",
            name="location_source",
            field=models.CharField(
                choices=[
                    ("gps", "Device GPS"),
                    ("cached", "Last known browser GPS"),
                    ("user", "User provided"),
                    ("network", "Network estimate"),
                ],
                default="user",
                max_length=20,
            ),
        ),
    ]
