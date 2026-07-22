import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import Fine
from groupcore.models import GroupSettings


logger = logging.getLogger(__name__)


def _deadline_for(period_start, settings_obj):
    offset = (settings_obj.weekly_deadline_weekday - period_start.weekday()) % 7
    value = datetime.combine(
        period_start + timedelta(days=offset), settings_obj.weekly_deadline_time
    )
    return timezone.make_aware(value, timezone.get_current_timezone())


def notify_fine_activated(fine_id):
    fine = Fine.objects.select_related('member').get(pk=fine_id)
    if not fine.member.email:
        return 0
    settings_obj = GroupSettings.objects.first()
    deadline = _deadline_for(fine.affected_week, settings_obj) if settings_obj and fine.affected_week else None
    member_name = fine.member.get_full_name() or fine.member.username
    message = (
        f'Hello {member_name},\n\n'
        f'A fine of UGX {fine.amount:,.0f} has been activated on your account.\n'
        f'Reason: {fine.reason}\n'
    )
    if fine.affected_week:
        message += f'Affected week: {fine.affected_week:%d %B %Y}\n'
    if deadline:
        message += f'Submission deadline: {timezone.localtime(deadline):%d %B %Y %H:%M %Z}\n'
    message += '\nLand Investment Group'
    try:
        return send_mail(
            'Weekly contribution fine activated', message,
            settings.DEFAULT_FROM_EMAIL, [fine.member.email], fail_silently=False,
        )
    except Exception:
        logger.exception('Could not send activation email for fine %s', fine.pk)
        return 0
