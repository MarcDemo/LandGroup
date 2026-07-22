from datetime import datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from deposits.models import DepositSubmission, WeeklySavingsAllocation
from groupcore.models import GroupSettings, MemberProfile
from .models import Fine
from .notifications import notify_fine_activated


def period_start_for(value, settings_obj):
    elapsed = max((value - settings_obj.week_one_start).days // 7, 0)
    return settings_obj.week_one_start + timedelta(weeks=elapsed)


def deadline_for(period_start, settings_obj):
    offset = (settings_obj.weekly_deadline_weekday - period_start.weekday()) % 7
    deadline_date = period_start + timedelta(days=offset)
    naive = datetime.combine(deadline_date, settings_obj.weekly_deadline_time)
    return timezone.make_aware(naive, timezone.get_current_timezone())


def _has_qualifying_allocation(member, period_start, deadline):
    allocation_exists = WeeklySavingsAllocation.objects.filter(
        savings_account__member=member,
        week_start=period_start,
        amount__gt=0,
        deposit__status='APPROVED',
        deposit__date_submitted__lte=deadline,
    ).exists()
    if allocation_exists:
        return True
    period_open = timezone.make_aware(
        datetime.combine(period_start, time.min), timezone.get_current_timezone()
    )
    return DepositSubmission.objects.filter(
        member=member,
        status='APPROVED',
        land_savings_amount__gt=0,
        date_submitted__gte=period_open,
        date_submitted__lte=deadline,
    ).exists()


def _has_pending_submission(member, period_start, deadline):
    """Conservatively defer while a timely pending land deposit is unresolved."""
    period_open = timezone.make_aware(
        datetime.combine(period_start, time.min), timezone.get_current_timezone()
    )
    return DepositSubmission.objects.filter(
        member=member,
        status='PENDING',
        land_savings_amount__gt=0,
        date_submitted__gte=period_open,
        date_submitted__lte=deadline,
    ).exists()


def _late_allocation_exists(member, period_start, deadline):
    allocation_exists = WeeklySavingsAllocation.objects.filter(
        savings_account__member=member,
        week_start=period_start,
        amount__gt=0,
        deposit__status='APPROVED',
        deposit__date_submitted__gt=deadline,
    ).exists()
    if allocation_exists:
        return True
    return DepositSubmission.objects.filter(
        member=member,
        status='APPROVED',
        land_savings_amount__gt=0,
        date_submitted__gt=deadline,
        date_submitted__lte=deadline + timedelta(weeks=1),
    ).exists()


@transaction.atomic
def reconcile_automatic_fines(now=None):
    now = now or timezone.now()
    local_date = timezone.localtime(now).date()
    settings_obj = GroupSettings.objects.select_for_update().first()
    if not settings_obj or local_date < settings_obj.week_one_start:
        return 0

    if settings_obj.automatic_fines_start_period is None:
        settings_obj.automatic_fines_start_period = period_start_for(local_date, settings_obj)
        settings_obj.save(update_fields=['automatic_fines_start_period'])

    members = list(MemberProfile.objects.filter(is_active=True, is_superuser=False))
    period = settings_obj.automatic_fines_start_period
    created = 0
    while period <= local_date:
        deadline = deadline_for(period, settings_obj)
        if deadline >= now:
            break
        for member in members:
            if member.date_joined > deadline:
                continue
            existing = Fine.objects.filter(
                member=member, origin='AUTOMATIC', affected_week=period
            ).first()
            if existing:
                if (
                    existing.approval_status == 'PENDING'
                    and existing.reason.startswith('Missed ')
                    and _late_allocation_exists(member, period, deadline)
                ):
                    existing.reason = f'Late Land Savings submission for week starting {period:%d %B %Y}'
                    existing.save(update_fields=['reason'])
                continue
            if _has_qualifying_allocation(member, period, deadline):
                continue
            if _has_pending_submission(member, period, deadline):
                continue
            late = _late_allocation_exists(member, period, deadline)
            reason = (
                f'Late Land Savings submission for week starting {period:%d %B %Y}'
                if late else
                f'Missed Land Savings deadline for week starting {period:%d %B %Y}'
            )
            _, was_created = Fine.objects.get_or_create(
                member=member,
                origin='AUTOMATIC',
                affected_week=period,
                defaults={
                    'reason': reason,
                    'amount': settings_obj.automatic_fine_amount,
                    'approval_status': 'PENDING',
                    'remarks': f'Weekly deadline: {timezone.localtime(deadline):%d %B %Y %H:%M %Z}',
                },
            )
            created += int(was_created)
        period += timedelta(weeks=1)
    return created


def ordered_for_management():
    return Fine.objects.select_related('member', 'issued_by', 'decided_by').annotate(
        management_priority=Case(
            When(approval_status='PENDING', then=Value(0)),
            When(approval_status='ACTIVE', status='UNPAID', then=Value(1)),
            When(approval_status='ACTIVE', status='PARTIAL', then=Value(2)),
            When(approval_status='ACTIVE', status='PAID', then=Value(3)),
            default=Value(4),
            output_field=IntegerField(),
        )
    ).order_by('management_priority', '-date_issued', '-id')


@transaction.atomic
def decide_automatic_fine(fine_id, treasurer, decision, comment=''):
    if decision not in ('ACTIVE', 'DISMISSED'):
        raise ValidationError('Invalid fine decision.')
    fine = Fine.objects.select_for_update().select_related('member').get(pk=fine_id)
    if fine.origin != 'AUTOMATIC' or fine.approval_status != 'PENDING':
        raise ValidationError('This automatic fine has already been decided.')
    fine.approval_status = decision
    fine.decided_by = treasurer
    fine.decision_at = timezone.now()
    fine.decision_comment = comment
    fine.save(update_fields=['approval_status', 'decided_by', 'decision_at', 'decision_comment'])
    if decision == 'ACTIVE':
        transaction.on_commit(lambda: notify_fine_activated(fine.pk), robust=True)
    return fine
