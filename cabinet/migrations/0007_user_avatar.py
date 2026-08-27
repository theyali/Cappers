from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0006_analystprofile_facebook_analystprofile_tiktok"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="avatar",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to="users/avatars/%Y/%m/",
                verbose_name="Аватар",
            ),
        ),
    ]
