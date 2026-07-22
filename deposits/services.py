from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from fines.models import Fine
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


def save_fine_allocations(deposit, allocations):
    FinePaymentAllocation.objects.bulk_create([
        FinePaymentAllocation(deposit=deposit, fine=fine, amount=amount)
        for fine, amount in allocations
    ])


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
    deposit = DepositSubmission.objects.select_for_update().get(pk=deposit_id)
    if deposit.status != 'PENDING':
        raise ValidationError('This deposit has already been reviewed.')
    settings_obj = GroupSettings.objects.select_for_update().first()
    if not settings_obj:
        raise ValidationError('Group Settings must be configured before approval.')
    if deposit.amount != deposit.land_savings_amount + deposit.fine_payment_amount:
        raise ValidationError('The category amounts do not match the deposit total.')

    allocate_land_savings(deposit, settings_obj)
    allocations = list(deposit.fine_allocations.all().order_by('fine_id'))
    allocated_total = sum((allocation.amount for allocation in allocations), Decimal('0'))
    if allocated_total != deposit.fine_payment_amount:
        raise ValidationError('Fine allocations do not match the deposit fine amount.')
    if deposit.fine_payment_amount and not allocations:
        raise ValidationError('Select at least one fine for this payment.')

    if allocations:
        fines = {
            fine.pk: fine for fine in Fine.objects.select_for_update().filter(
                pk__in=[allocation.fine_id for allocation in allocations],
            ).order_by('pk')
        }
        if len(fines) != len(allocations):
            raise ValidationError('One or more selected fines are invalid.')
        for allocation in allocations:
            fine = fines[allocation.fine_id]
            outstanding = fine.amount - fine.amount_paid
            if (fine.member_id != deposit.member_id or fine.approval_status != 'ACTIVE' or
                    fine.status == 'PAID' or outstanding <= 0):
                raise ValidationError('Every selected fine must be active, outstanding, and belong to this member.')
            if allocation.amount <= 0 or allocation.amount > outstanding:
                raise ValidationError(
                    f'Allocation for fine #{fine.pk} exceeds its outstanding balance of UGX {outstanding:,.0f}.'
                )

        for allocation in allocations:
            fine = fines[allocation.fine_id]
            fine.amount_paid += allocation.amount
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
