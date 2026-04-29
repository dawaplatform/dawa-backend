from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('DawaApp', '0020_item_subscription_package_subcategory_metadata'),
    ]

    operations = [
        migrations.AlterField(
            model_name='item',
            name='item_status',
            field=models.CharField(
                choices=[
                    ('Available', 'Available'),
                    ('Sold', 'Sold'),
                    ('Out of Stock', 'Out of Stock'),
                    ('Cancelled', 'Cancelled'),
                ],
                default='Available',
                max_length=50,
            ),
        ),
    ]
