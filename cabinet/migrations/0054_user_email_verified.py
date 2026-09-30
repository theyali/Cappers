from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0053_analystpaidsubscriptionpayment"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="email_verified",
            field=models.BooleanField(db_index=True, default=False, verbose_name="Почта подтверждена"),
        ),
    ]
