import logging

from django.conf import settings
from django.core.mail import send_mail

from groupcore.models import MemberProfile


logger = logging.getLogger(__name__)


def _name(member):
    return member.get_full_name() or member.username


def _send(subject, message, recipients):
    recipients = sorted({email.strip() for email in recipients if email and email.strip()})
    if not recipients:
        return 0
    try:
        return send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            recipients,
            fail_silently=False,
        )
    except Exception:
        logger.exception('Could not send LandGroup email %r', subject)
        return 0


def notify_deposit_submitted(deposit):
    reference = deposit.transaction_reference or f'Deposit #{deposit.pk}'
    amount = f'UGX {deposit.amount:,.0f}'

    if deposit.member.email:
        _send(
            f'Deposit received - {reference}',
            (
                f'Hello {_name(deposit.member)},\n\n'
                f'Your deposit of {amount} has been received and is awaiting Treasurer review.\n'
                f'Reference: {reference}\n'
                f'Payment date: {deposit.payment_date:%d %B %Y}\n\n'
                'You will receive another email after it has been reviewed.\n\n'
                'Land Investment Group'
            ),
            [deposit.member.email],
        )

    treasurer_emails = MemberProfile.objects.filter(
        role='TREASURER', is_active=True
    ).exclude(email='').values_list('email', flat=True)
    _send(
        f'New deposit awaiting review - {reference}',
        (
            'A member has submitted a new deposit for review.\n\n'
            f'Member: {_name(deposit.member)}\n'
            f'Amount: {amount}\n'
            f'Categories: {deposit.categories_display}\n'
            f'Reference: {reference}\n'
            f'Payment date: {deposit.payment_date:%d %B %Y}\n\n'
            'Sign in to LandGroup to review the proof of payment.'
        ),
        treasurer_emails,
    )


def notify_deposit_reviewed(deposit):
    if not deposit.member.email:
        return 0
    reference = deposit.transaction_reference or f'Deposit #{deposit.pk}'
    approved = deposit.status == 'APPROVED'
    decision = 'approved' if approved else 'rejected'
    subject = f'Deposit {decision} - {reference}'
    comment = deposit.review_comment.strip() if deposit.review_comment else ''
    message = (
        f'Hello {_name(deposit.member)},\n\n'
        f'Your deposit of UGX {deposit.amount:,.0f} has been {decision}.\n'
        f'Reference: {reference}\n'
        f'Status: {deposit.get_status_display()}\n'
    )
    if comment:
        message += f'Review comment: {comment}\n'
    message += '\nLand Investment Group'
    return _send(subject, message, [deposit.member.email])
