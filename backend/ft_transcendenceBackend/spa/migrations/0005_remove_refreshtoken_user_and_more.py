# Generated by Django 4.2.11 on 2024-03-18 14:51

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('spa', '0004_app_user_delete_user'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='refreshtoken',
            name='user',
        ),
        migrations.RemoveField(
            model_name='whitelistedtoken',
            name='user',
        ),
        migrations.DeleteModel(
            name='BlacklistedToken',
        ),
        migrations.DeleteModel(
            name='RefreshToken',
        ),
        migrations.DeleteModel(
            name='WhitelistedToken',
        ),
    ]
