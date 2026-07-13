from datetime import timedelta
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from groupcore.models import GroupSettings
from .models import WeeklySavingsAllocation


def week_label(value):
    iso = value.isocalendar()
    return f"Week {iso.week}, {iso.year}"


def savings_position(member, account=None):
    today = timezone.localdate()
    settings_obj = GroupSettings.objects.first()
    base = {
        'current_week_label': week_label(today), 'latest_fully_paid': None,
        'weeks_behind': 0, 'weeks_ahead': 0, 'current_week_due': True,
        'partial_week': None, 'partial_balance': Decimal('0'), 'status': 'Current Week Due',
    }
    if not settings_obj:
        return base
    if account is None:
        account = member.savings_accounts.filter(is_active=True).order_by('id').first()
    if not account:
        elapsed = max(((today - settings_obj.week_one_start).days // 7) + 1, 0)
        base['weeks_behind'] = elapsed
        return base
    totals = dict(WeeklySavingsAllocation.objects.filter(savings_account=account)
                  .values_list('week_start').annotate(total=Sum('amount')))
    rate = settings_obj.weekly_contribution
    current_start = settings_obj.week_one_start + timedelta(weeks=max((today - settings_obj.week_one_start).days // 7, 0))
    base['current_week_label'] = week_label(current_start)
    week = settings_obj.week_one_start
    latest = None
    while totals.get(week, Decimal('0')) >= rate:
        latest = week
        week += timedelta(weeks=1)
    current_paid = totals.get(current_start, Decimal('0'))
    base['latest_fully_paid'] = week_label(latest) if latest else 'None'
    partial_paid = totals.get(week, Decimal('0'))
    has_partial = Decimal('0') < partial_paid < rate
    if has_partial:
        base.update(partial_week=week_label(week), partial_balance=rate-partial_paid)
    if current_paid >= rate:
        base['current_week_due'] = False
    if week < current_start:
        base.update(status='Behind', weeks_behind=((current_start-week).days // 7))
    elif week > current_start + timedelta(weeks=1):
        base.update(status='Ahead', weeks_ahead=((week-current_start).days // 7)-1, current_week_due=False)
    elif not base['current_week_due']:
        base['status'] = 'Up to Date'
    if has_partial:
        base['status'] = 'Partially Paid'
    return base
