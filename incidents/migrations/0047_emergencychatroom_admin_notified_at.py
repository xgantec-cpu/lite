from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("incidents", "0046_admin_browser_pairing"),
    ]

    operations = [
        migrations.AddField(
            model_name="emergencychatroom",
            name="admin_notified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
