from django.db import migrations, models
import artwork.private_storage


class Migration(migrations.Migration):
    dependencies = [('artwork', '0004_customrequest_cancellation_refunds_and_more')]
    operations = [
        migrations.AlterField(
            model_name='customrequest', name='reference_image',
            field=models.ImageField(blank=True, null=True, storage=artwork.private_storage.PrivateCommissionStorage(), upload_to='commission_refs/'),
        ),
        migrations.AlterField(
            model_name='commissionmessage', name='attachment',
            field=models.FileField(blank=True, null=True, storage=artwork.private_storage.PrivateCommissionStorage(), upload_to='commission_messages/'),
        ),
        migrations.AlterField(
            model_name='commissiondelivery', name='delivery_file',
            field=models.FileField(blank=True, null=True, storage=artwork.private_storage.PrivateCommissionStorage(), upload_to='commission_deliveries/'),
        ),
    ]
