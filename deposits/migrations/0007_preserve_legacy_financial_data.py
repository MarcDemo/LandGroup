from datetime import timedelta
from decimal import Decimal
from django.db import migrations


def forwards(apps, schema_editor):
    Deposit = apps.get_model('deposits', 'DepositSubmission')
    Account = apps.get_model('deposits', 'SavingsAccount')
    Weekly = apps.get_model('deposits', 'WeeklySavingsAllocation')
    Fine = apps.get_model('fines', 'Fine')
    GroupSettings = apps.get_model('groupcore', 'GroupSettings')
    rate = Decimal('20000')
    settings_obj = GroupSettings.objects.first()
    if settings_obj:
        rate = settings_obj.weekly_contribution

    member_ids = Deposit.objects.values_list('member_id', flat=True).distinct()
    for member_id in member_ids:
        account, _ = Account.objects.get_or_create(
            member_id=member_id, defaults={'account_number': f'LIG-{member_id:05d}'}
        )
        deposits = Deposit.objects.filter(member_id=member_id).order_by('date_submitted', 'id')
        for deposit in deposits:
            deposit.savings_account_id = account.id
            deposit.land_savings_amount = deposit.amount
            deposit.fine_payment_amount = Decimal('0')
            deposit.save(update_fields=['savings_account', 'land_savings_amount', 'fine_payment_amount'])
            if deposit.status != 'APPROVED' or deposit.amount <= 0:
                continue
            remaining = deposit.amount
            week = deposit.starting_week
            while remaining > 0:
                allocated = min(remaining, rate)
                Weekly.objects.get_or_create(
                    deposit_id=deposit.id, week_start=week,
                    defaults={'savings_account_id': account.id, 'amount': allocated},
                )
                remaining -= allocated
                week += timedelta(weeks=1)

    for fine in Fine.objects.all():
        if fine.is_paid:
            fine.amount_paid = fine.amount
            fine.status = 'PAID'
        else:
            fine.amount_paid = Decimal('0')
            fine.status = 'UNPAID'
        fine.save(update_fields=['amount_paid', 'status'])


class Migration(migrations.Migration):
    dependencies = [
        ('deposits', '0006_depositsubmission_fine_payment_amount_and_more'),
        ('groupcore', '0008_groupsettings_weekly_contribution'),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
