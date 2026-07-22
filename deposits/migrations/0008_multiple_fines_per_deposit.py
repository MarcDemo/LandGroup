import django.db.models.deletion
from django.db import migrations, models


def preserve_selected_fines(apps, schema_editor):
    Deposit = apps.get_model('deposits', 'DepositSubmission')
    Allocation = apps.get_model('deposits', 'FinePaymentAllocation')
    deposits = Deposit.objects.filter(
        selected_fine_id__isnull=False,
        fine_payment_amount__gt=0,
    ).iterator()
    for deposit in deposits:
        Allocation.objects.get_or_create(
            deposit_id=deposit.id,
            defaults={
                'fine_id': deposit.selected_fine_id,
                'amount': deposit.fine_payment_amount,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0007_preserve_legacy_financial_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='finepaymentallocation',
            name='deposit',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='fine_allocations',
                to='deposits.depositsubmission',
            ),
        ),
        migrations.RunPython(preserve_selected_fines, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='depositsubmission',
            name='selected_fine',
        ),
        migrations.AddConstraint(
            model_name='finepaymentallocation',
            constraint=models.UniqueConstraint(
                fields=('deposit', 'fine'),
                name='unique_deposit_fine_allocation',
            ),
        ),
    ]
