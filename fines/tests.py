from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission, SavingsAccount
from deposits.services import approve_deposit, reject_deposit
from groupcore.models import GroupSettings, MemberProfile
from .models import Fine
from .services import decide_automatic_fine, ordered_for_management, reconcile_automatic_fines


class AutomaticFineTests(TestCase):
    def setUp(self):
        self.period = timezone.localdate() - timedelta(days=timezone.localdate().weekday(), weeks=1)
        self.settings = GroupSettings.objects.create(
            week_one_start=self.period - timedelta(weeks=3),
            weekly_contribution=Decimal('20000'),
            weekly_deadline_weekday=6,
            weekly_deadline_time=time(23, 59),
            automatic_fine_amount=Decimal('5000'),
            automatic_fines_start_period=self.period,
        )
        self.member = MemberProfile.objects.create_user(
            username='member', password='pw', role='MEMBER', email='member@example.com'
        )
        self.treasurer = MemberProfile.objects.create_user(
            username='treasurer', password='pw', role='TREASURER'
        )
        MemberProfile.objects.filter(pk__in=[self.member.pk, self.treasurer.pk]).update(
            date_joined=timezone.make_aware(datetime.combine(self.period - timedelta(days=1), time(12)))
        )
        self.member.refresh_from_db()
        self.treasurer.refresh_from_db()
        self.account = SavingsAccount.objects.create(member=self.member, account_number='LIG-FINE-1')
        self.deadline = timezone.make_aware(
            datetime.combine(self.period + timedelta(days=6), time(23, 59))
        )
        self.after_deadline = self.deadline + timedelta(minutes=2)

    def deposit(self, status='PENDING', amount=20000, submitted_at=None, reference='D-1'):
        deposit = DepositSubmission.objects.create(
            member=self.member, submitted_by=self.member, savings_account=self.account,
            starting_week=self.settings.week_one_start, weeks_covered=0,
            amount=Decimal(str(amount)), land_savings_amount=Decimal(str(amount)),
            payment_date=self.period, payment_time=time(12), status=status,
            transaction_reference=reference,
        )
        if submitted_at:
            DepositSubmission.objects.filter(pk=deposit.pk).update(date_submitted=submitted_at)
            deposit.refresh_from_db()
        return deposit

    def member_candidates(self):
        return Fine.objects.filter(member=self.member, origin='AUTOMATIC')

    def test_first_reconciliation_initializes_current_period_without_backfill(self):
        self.settings.automatic_fines_start_period = None
        self.settings.weekly_deadline_weekday = self.after_deadline.weekday()
        self.settings.weekly_deadline_time = time(0)
        self.settings.save()

        reconcile_automatic_fines(now=self.after_deadline)

        self.settings.refresh_from_db()
        expected = self.settings.week_one_start + timedelta(
            weeks=max((self.after_deadline.date() - self.settings.week_one_start).days // 7, 0)
        )
        self.assertEqual(self.settings.automatic_fines_start_period, expected)
        self.assertFalse(Fine.objects.filter(affected_week__lt=expected).exists())

    def test_missing_submission_creates_one_idempotent_candidate(self):
        self.assertGreaterEqual(reconcile_automatic_fines(now=self.after_deadline), 1)
        reconcile_automatic_fines(now=self.after_deadline)

        candidate = self.member_candidates().get()
        self.assertEqual(candidate.amount, Decimal('5000'))
        self.assertEqual(candidate.approval_status, 'PENDING')
        self.assertIn('Missed', candidate.reason)

    def test_database_prevents_duplicate_automatic_member_week(self):
        Fine.objects.create(
            member=self.member, amount=5000, reason='One', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            Fine.objects.create(
                member=self.member, amount=5000, reason='Two', origin='AUTOMATIC',
                approval_status='PENDING', affected_week=self.period,
            )

    def test_on_time_approved_partial_contribution_prevents_candidate(self):
        deposit = self.deposit(amount=5000, submitted_at=self.deadline - timedelta(hours=1))
        approve_deposit(deposit.pk, self.treasurer)

        reconcile_automatic_fines(now=self.after_deadline)

        self.assertFalse(self.member_candidates().exists())

    def test_prepaid_week_prevents_candidate(self):
        deposit = self.deposit(amount=100000, submitted_at=self.deadline - timedelta(days=10))
        approve_deposit(deposit.pk, self.treasurer)

        reconcile_automatic_fines(now=self.after_deadline)

        self.assertFalse(self.member_candidates().exists())

    def test_on_time_pending_defers_then_rejection_creates_missed_candidate(self):
        deposit = self.deposit(submitted_at=self.deadline - timedelta(hours=1))
        reconcile_automatic_fines(now=self.after_deadline)
        self.assertFalse(self.member_candidates().exists())

        reject_deposit(deposit.pk, self.treasurer, 'Invalid proof')
        reconcile_automatic_fines(now=self.after_deadline)

        self.assertIn('Missed', self.member_candidates().get().reason)

    def test_on_time_pending_then_approved_never_creates_candidate(self):
        deposit = self.deposit(submitted_at=self.deadline - timedelta(hours=1))
        reconcile_automatic_fines(now=self.after_deadline)
        approve_deposit(deposit.pk, self.treasurer)
        reconcile_automatic_fines(now=self.after_deadline)

        self.assertFalse(self.member_candidates().exists())

    def test_late_approved_submission_creates_late_candidate(self):
        deposit = self.deposit(submitted_at=self.deadline + timedelta(minutes=1))
        approve_deposit(deposit.pk, self.treasurer)

        reconcile_automatic_fines(now=self.after_deadline)

        self.assertIn('Late', self.member_candidates().get().reason)

    def test_pending_missed_candidate_is_relabelled_after_late_submission(self):
        reconcile_automatic_fines(now=self.after_deadline)
        candidate = self.member_candidates().get()
        self.assertIn('Missed', candidate.reason)
        deposit = self.deposit(
            submitted_at=self.deadline + timedelta(minutes=1), reference='LATE-AFTER-SCAN'
        )
        approve_deposit(deposit.pk, self.treasurer)

        reconcile_automatic_fines(now=self.after_deadline)

        candidate.refresh_from_db()
        self.assertIn('Late', candidate.reason)
        self.assertEqual(self.member_candidates().count(), 1)

    def test_inactive_and_superuser_accounts_are_excluded(self):
        inactive = MemberProfile.objects.create_user(username='inactive', is_active=False)
        superuser = MemberProfile.objects.create_superuser(username='admin', password='pw')

        reconcile_automatic_fines(now=self.after_deadline)

        self.assertFalse(Fine.objects.filter(member__in=[inactive, superuser], origin='AUTOMATIC').exists())

    def test_member_is_not_fined_for_a_deadline_before_joining(self):
        newcomer = MemberProfile.objects.create_user(username='newcomer', password='pw')

        reconcile_automatic_fines(now=self.after_deadline)

        self.assertFalse(Fine.objects.filter(member=newcomer, origin='AUTOMATIC').exists())

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_activation_exposes_fine_and_sends_one_email(self):
        candidate = Fine.objects.create(
            member=self.member, amount=5000, reason='Late submission', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )

        with self.captureOnCommitCallbacks(execute=True):
            decide_automatic_fine(candidate.pk, self.treasurer, 'ACTIVE', 'Confirmed')

        candidate.refresh_from_db()
        self.assertEqual(candidate.approval_status, 'ACTIVE')
        self.assertTrue(Fine.objects.active().filter(pk=candidate.pk).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('UGX 5,000', mail.outbox[0].body)
        with self.assertRaises(ValidationError):
            decide_automatic_fine(candidate.pk, self.treasurer, 'ACTIVE')

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_dismissal_stays_hidden_and_sends_no_email(self):
        candidate = Fine.objects.create(
            member=self.member, amount=5000, reason='Missed', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )
        decide_automatic_fine(candidate.pk, self.treasurer, 'DISMISSED', 'Excused')

        self.assertFalse(Fine.objects.active().filter(pk=candidate.pk).exists())
        self.assertEqual(len(mail.outbox), 0)

    def test_member_views_and_payment_form_hide_inactive_candidates(self):
        pending = Fine.objects.create(
            member=self.member, amount=5000, reason='Pending hidden', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )
        self.client.force_login(self.member)

        response = self.client.get(reverse('my_fines'))
        csv_response = self.client.get(reverse('download_my_fines', args=['csv']))
        deposit_response = self.client.get(reverse('submit_deposit'))

        self.assertNotContains(response, pending.reason)
        self.assertNotIn(pending.reason, csv_response.content.decode())
        self.assertNotContains(deposit_response, 'Fine Payment')

    def test_treasurer_only_post_decision_endpoints(self):
        candidate = Fine.objects.create(
            member=self.member, amount=5000, reason='Candidate', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('activate_fine', args=[candidate.pk])).status_code, 405)
        self.client.post(reverse('activate_fine', args=[candidate.pk]))
        candidate.refresh_from_db()
        self.assertEqual(candidate.approval_status, 'PENDING')

    def test_management_order_prioritizes_pending_and_unpaid(self):
        paid = Fine.objects.create(member=self.member, amount=1000, amount_paid=1000, reason='Paid', status='PAID', is_paid=True)
        unpaid = Fine.objects.create(member=self.member, amount=1000, reason='Unpaid')
        pending = Fine.objects.create(
            member=self.member, amount=1000, reason='Pending', origin='AUTOMATIC',
            approval_status='PENDING', affected_week=self.period,
        )

        ordered = list(ordered_for_management().filter(pk__in=[paid.pk, unpaid.pk, pending.pk]))

        self.assertEqual(ordered, [pending, unpaid, paid])
