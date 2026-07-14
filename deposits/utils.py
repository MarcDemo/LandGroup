from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from groupcore.models import GroupSettings
from .models import WeeklySavingsAllocation


def _first_matching_weekday_in_july(year, weekday):
    """Return the first requested weekday in July for a financial year."""
    july_first = date(year, 7, 1)
    offset = (weekday - july_first.weekday()) % 7
    return july_first + timedelta(days=offset)


def group_week_info(value, week_one_start):
    """Calculate LandGroup financial and cumulative week numbers.

    Weekly periods remain anchored to ``week_one_start``. Financial week
    numbering resets on the first matching weekday in July, while the overall
    week remains a one-based count from the original group start.
    """
    if value < week_one_start:
        return None

    overall_week = ((value - week_one_start).days // 7) + 1
    period_start = week_one_start + timedelta(weeks=overall_week - 1)
    financial_year = period_start.year
    financial_start = _first_matching_weekday_in_july(
        financial_year, week_one_start.weekday()
    )
    if period_start < financial_start:
        financial_year -= 1
        financial_start = _first_matching_weekday_in_july(
            financial_year, week_one_start.weekday()
        )

    financial_week = ((period_start - financial_start).days // 7) + 1
    return {
        'period_start': period_start,
        'financial_year': financial_year,
        'financial_week': financial_week,
        'overall_week': overall_week,
    }


def week_label(value, settings_obj=None):
    settings_obj = settings_obj or GroupSettings.objects.first()
    if not settings_obj:
        return 'Financial week not configured'
    info = group_week_info(value, settings_obj.week_one_start)
    if not info:
        return 'Before group savings start'
    return (
        f"Week {info['financial_week']}, Financial Year "
        f"{info['financial_year']} (Overall Week {info['overall_week']})"
    )


def savings_position(member, account=None):
    today = timezone.localdate()
    settings_obj = GroupSettings.objects.first()
    base = {
        'current_week_label': 'Financial week not configured', 'latest_fully_paid': None,
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
    base['current_week_label'] = week_label(current_start, settings_obj)
    week = settings_obj.week_one_start
    latest = None
    while totals.get(week, Decimal('0')) >= rate:
        latest = week
        week += timedelta(weeks=1)
    current_paid = totals.get(current_start, Decimal('0'))
    base['latest_fully_paid'] = week_label(latest, settings_obj) if latest else 'None'
    partial_paid = totals.get(week, Decimal('0'))
    has_partial = Decimal('0') < partial_paid < rate
    if has_partial:
        base.update(partial_week=week_label(week, settings_obj), partial_balance=rate-partial_paid)
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
