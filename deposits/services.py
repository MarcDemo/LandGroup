from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from groupcore.models import GroupSettings
from .models import (
    DepositAuditLog, DepositSubmission, FinePaymentAllocation,
    SavingsAccount, WeeklySavingsAllocation,
)


def get_or_create_account(member):
    account = member.savings_accounts.filter(is_active=True).order_by('id').first()
    if account:
        return account
    base = f"LIG-{member.pk:05d}"
    number, suffix = base, 1
    while SavingsAccount.objects.filter(account_number=number).exists():
        suffix += 1
        number = f"{base}-{suffix}"
    return SavingsAccount.objects.create(member=member, account_number=number)


def allocate_land_savings(deposit, settings_obj):
    remaining = deposit.land_savings_amount
    if remaining <= 0:
        return
    account = deposit.savings_account or get_or_create_account(deposit.member)
    deposit.savings_account = account
    rate = settings_obj.weekly_contribution
    week_start = settings_obj.week_one_start
    while remaining > 0:
        paid = WeeklySavingsAllocation.objects.filter(
            savings_account=account, week_start=week_start
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
        due = max(rate - paid, Decimal('0'))
        if due:
            allocated = min(remaining, due)
            WeeklySavingsAllocation.objects.create(
                deposit=deposit, savings_account=account,
                week_start=week_start, amount=allocated,
            )
            remaining -= allocated
        week_start += timedelta(weeks=1)
    deposit.starting_week = deposit.weekly_allocations.order_by('week_start').first().week_start
    deposit.weeks_covered = deposit.weekly_allocations.filter(amount=rate).count()


@transaction.atomic
def approve_deposit(deposit_id, reviewer):
    deposit = DepositSubmission.objects.select_for_update().select_related('selected_fine').get(pk=deposit_id)
    if deposit.status != 'PENDING':
        raise ValidationError('This deposit has already been reviewed.')
    settings_obj = GroupSettings.objects.select_for_update().first()
    if not settings_obj:
        raise ValidationError('Group Settings must be configured before approval.')
    if deposit.amount != deposit.land_savings_amount + deposit.fine_payment_amount:
        raise ValidationError('The category amounts do not match the deposit total.')

    allocate_land_savings(deposit, settings_obj)
    if deposit.fine_payment_amount:
        if not deposit.selected_fine_id or deposit.selected_fine.member_id != deposit.member_id:
            raise ValidationError('Select a valid fine belonging to this member.')
        fine = type(deposit.selected_fine).objects.select_for_update().get(pk=deposit.selected_fine_id)
        outstanding = fine.amount - fine.amount_paid
        if deposit.fine_payment_amount > outstanding:
            raise ValidationError(f'Fine payment exceeds the outstanding balance of UGX {outstanding:,.0f}.')
        FinePaymentAllocation.objects.create(
            deposit=deposit, fine=fine, amount=deposit.fine_payment_amount,
        )
        fine.amount_paid += deposit.fine_payment_amount
        fine.is_paid = fine.amount_paid >= fine.amount
        fine.status = 'PAID' if fine.is_paid else 'PARTIAL'
        fine.save(update_fields=['amount_paid', 'is_paid', 'status'])

    deposit.status = 'APPROVED'
    deposit.reviewed_by = reviewer
    deposit.date_reviewed = timezone.now()
    deposit.save()
    DepositAuditLog.objects.create(deposit=deposit, actor=reviewer, action='APPROVED', details=deposit.review_comment)
    return deposit


@transaction.atomic
def reject_deposit(deposit_id, reviewer, comment=''):
    deposit = DepositSubmission.objects.select_for_update().get(pk=deposit_id)
    if deposit.status != 'PENDING':
        raise ValidationError('This deposit has already been reviewed.')
    deposit.status = 'REJECTED'
    deposit.reviewed_by = reviewer
    deposit.review_comment = comment
    deposit.date_reviewed = timezone.now()
    deposit.save(update_fields=['status', 'reviewed_by', 'review_comment', 'date_reviewed'])
    DepositAuditLog.objects.create(deposit=deposit, actor=reviewer, action='REJECTED', details=comment)
    return deposit
