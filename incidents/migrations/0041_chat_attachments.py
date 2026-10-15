from django.db import migrations, models

import incidents.fields


class Migration(migrations.Migration):
    dependencies = [
        ("incidents", "0040_emergencyrequest_cached_location_source"),
    ]

    operations = [
        migrations.AlterField(
            model_name="emergencychatmessage",
            name="channel",
            field=models.CharField(
                choices=[
                    ("text", "Text message"),
                    ("audio", "Audio note"),
                    ("file", "File attachment"),
                    ("system", "System event"),
                ],
                default="text",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="casemessage",
            name="body",
            field=incidents.fields.EncryptedTextField(blank=True, max_length=4000),
        ),
        migrations.AlterField(
            model_name="inhousemessage",
            name="body",
            field=incidents.fields.EncryptedTextField(blank=True, max_length=4000),
        ),
        migrations.AddField(
            model_name="casemessage",
            name="attachment",
            field=models.FileField(blank=True, upload_to="case_chat_files/"),
        ),
        migrations.AddField(
            model_name="casemessage",
            name="attachment_content_type",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="casemessage",
            name="attachment_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="casemessage",
            name="attachment_size",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="emergencychatmessage",
            name="attachment",
            field=models.FileField(blank=True, upload_to="emergency_chat_files/"),
        ),
        migrations.AddField(
            model_name="emergencychatmessage",
            name="attachment_content_type",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="emergencychatmessage",
            name="attachment_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="emergencychatmessage",
            name="attachment_size",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="inhousemessage",
            name="attachment",
            field=models.FileField(blank=True, upload_to="inhouse_chat_files/"),
        ),
        migrations.AddField(
            model_name="inhousemessage",
            name="attachment_content_type",
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name="inhousemessage",
            name="attachment_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="inhousemessage",
            name="attachment_size",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
