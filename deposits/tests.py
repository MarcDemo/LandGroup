from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from fines.models import Fine
from groupcore.models import GroupSettings, MemberProfile
from .forms import DepositSubmissionForm, DirectDepositForm
from .models import DepositSubmission, FinePaymentAllocation, SavingsAccount, WeeklySavingsAllocation
from .notifications import notify_deposit_submitted
from .services import approve_deposit, reject_deposit
from .utils import group_week_info, savings_position, week_label


class GroupFinancialWeekTests(TestCase):
    def setUp(self):
        self.start = date(2025, 7, 7)
        self.settings = GroupSettings.objects.create(
            week_one_start=self.start, weekly_contribution=20000
        )

    def test_original_start_is_financial_and_overall_week_one(self):
        info = group_week_info(self.start, self.start)
        self.assertEqual((info['financial_week'], info['financial_year'], info['overall_week']), (1, 2025, 1))

    def test_2026_financial_year_resets_on_first_monday_in_july(self):
        info = group_week_info(date(2026, 7, 6), self.start)
        self.assertEqual((info['financial_week'], info['financial_year'], info['overall_week']), (1, 2026, 53))

    def test_14_july_2026_is_financial_week_two_and_overall_54(self):
        value = date(2026, 7, 14)
        info = group_week_info(value, self.start)
        self.assertEqual((info['financial_week'], info['financial_year'], info['overall_week']), (2, 2026, 54))
        self.assertEqual(
            week_label(value, self.settings),
            'Week 2, Financial Year 2026 (Overall Week 54)',
        )

    def test_financial_year_can_contain_week_53(self):
        info = group_week_info(date(2031, 6, 30), self.start)
        self.assertEqual((info['financial_week'], info['financial_year']), (53, 2030))


class DepositAccountingTests(TestCase):
    def setUp(self):
        self.start = timezone.localdate() - timedelta(weeks=3)
        self.settings = GroupSettings.objects.create(week_one_start=self.start, weekly_contribution=20000)
        self.member = MemberProfile.objects.create_user(username='member', password='pw', role='MEMBER')
        self.treasurer = MemberProfile.objects.create_user(username='treasurer', password='pw', role='TREASURER')
        self.account = SavingsAccount.objects.create(member=self.member, account_number='LIG-00001')

    def deposit(self, land=0, fine=0, selected_fine=None, status='PENDING', reference='TX-1', account=None):
        deposit = DepositSubmission.objects.create(
            member=self.member, submitted_by=self.member, savings_account=account or self.account,
            starting_week=self.start, weeks_covered=0, amount=Decimal(str(land + fine)),
            land_savings_amount=Decimal(str(land)), fine_payment_amount=Decimal(str(fine)),
            transaction_reference=reference,
            payment_date=timezone.localdate(), payment_time=timezone.localtime().time(), status=status,
        )
        if selected_fine:
            FinePaymentAllocation.objects.create(
                deposit=deposit, fine=selected_fine, amount=Decimal(str(fine)),
            )
        return deposit

    def test_land_savings_only_and_partial_week(self):
        deposit = self.deposit(land=10000)
        approve_deposit(deposit.id, self.treasurer)
        allocation = WeeklySavingsAllocation.objects.get(deposit=deposit)
        self.assertEqual(allocation.amount, Decimal('10000'))
        self.assertEqual(savings_position(self.member)['partial_balance'], Decimal('10000'))

    def test_transaction_reference_is_generated_automatically(self):
        deposit = self.deposit(land=20000, reference='')
        self.assertRegex(deposit.transaction_reference, r'^LIG-\d{8}-[A-F0-9]{8}$')
        second = self.deposit(land=20000, reference='')
        self.assertNotEqual(deposit.transaction_reference, second.transaction_reference)

    def test_transaction_reference_is_not_user_editable(self):
        form = DepositSubmissionForm(member=self.member)
        self.assertNotIn('transaction_reference', form.fields)

    def test_member_without_outstanding_fine_has_no_fine_payment_option(self):
        form = DepositSubmissionForm(member=self.member)
        self.assertNotIn('include_fine_payment', form.fields)
        self.assertNotIn('fine_payment_amount', form.fields)
        self.assertNotIn('selected_fines', form.fields)

        self.client.force_login(self.member)
        response = self.client.get(reverse('submit_deposit'))
        self.assertNotContains(response, 'Fine Payment')

    def test_member_without_outstanding_fine_can_submit_land_savings(self):
        self.client.force_login(self.member)

        response = self.client.post(reverse('submit_deposit'), {
            'savings_account': self.account.pk,
            'include_land_savings': 'on',
            'land_savings_amount': '20000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:41',
            'proof': SimpleUploadedFile('proof.jpg', b'payment proof', content_type='image/jpeg'),
            'remarks': '',
        })

        self.assertRedirects(response, reverse('my_contributions'))
        deposit = DepositSubmission.objects.latest('id')
        self.assertEqual(deposit.member, self.member)
        self.assertEqual(deposit.land_savings_amount, Decimal('20000'))
        self.assertEqual(deposit.fine_payment_amount, Decimal('0'))

    def test_member_with_outstanding_fine_has_fine_payment_option(self):
        fine = Fine.objects.create(
            member=self.member, reason='Late', amount=30000, issued_by=self.treasurer
        )
        form = DepositSubmissionForm(member=self.member)
        self.assertIn('include_fine_payment', form.fields)
        self.assertFalse(form.requires_fine_allocation)

        self.client.force_login(self.member)
        response = self.client.get(reverse('submit_deposit'))
        self.assertContains(response, 'Fine Payment')
        self.assertContains(response, 'automatically be applied to your outstanding fine')
        self.assertNotContains(response, f'name="selected_fines" value="{fine.pk}"')

    def test_single_fine_is_allocated_automatically(self):
        fine = Fine.objects.create(
            member=self.member, reason='Late', amount=10000, issued_by=self.treasurer,
        )
        self.client.force_login(self.member)

        response = self.client.post(reverse('submit_deposit'), {
            'savings_account': self.account.pk,
            'include_fine_payment': 'on',
            'fine_payment_amount': '6000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:41',
            'proof': SimpleUploadedFile('proof.jpg', b'payment proof', content_type='image/jpeg'),
            'remarks': '',
        })

        self.assertRedirects(response, reverse('my_contributions'))
        deposit = DepositSubmission.objects.latest('id')
        allocation = deposit.fine_allocations.get()
        self.assertEqual((allocation.fine, allocation.amount), (fine, Decimal('6000')))

    def test_treasurer_direct_form_has_no_category_toggle_boxes(self):
        form = DirectDepositForm()
        self.assertNotIn('include_land_savings', form.fields)
        self.assertNotIn('include_fine_payment', form.fields)

    def test_treasurer_direct_form_keeps_amount_fields_for_member_without_fine(self):
        form = DirectDepositForm(data={'member': self.member.pk})
        self.assertIn('land_savings_amount', form.fields)
        self.assertIn('fine_payment_amount', form.fields)
        self.assertIn('selected_fines', form.fields)

    def test_payment_completes_partial_and_covers_several_weeks(self):
        approve_deposit(self.deposit(land=10000, reference='A').id, self.treasurer)
        second = self.deposit(land=50000, reference='B')
        approve_deposit(second.id, self.treasurer)
        amounts = list(second.weekly_allocations.values_list('amount', flat=True))
        self.assertEqual(amounts, [Decimal('10000'), Decimal('20000'), Decimal('20000')])

    def test_payment_can_place_member_ahead(self):
        deposit = self.deposit(land=120000)
        approve_deposit(deposit.id, self.treasurer)
        position = savings_position(self.member)
        self.assertGreaterEqual(position['weeks_ahead'], 1)

    def test_partial_then_full_fine_payment(self):
        fine = Fine.objects.create(member=self.member, reason='Late', amount=30000, issued_by=self.treasurer)
        first = self.deposit(fine=10000, selected_fine=fine, reference='F1')
        approve_deposit(first.id, self.treasurer)
        fine.refresh_from_db()
        self.assertEqual((fine.amount_paid, fine.status, fine.outstanding_balance), (Decimal('10000'), 'PARTIAL', Decimal('20000')))
        second = self.deposit(fine=20000, selected_fine=fine, reference='F2')
        approve_deposit(second.id, self.treasurer)
        fine.refresh_from_db()
        self.assertTrue(fine.is_paid)
        self.assertEqual(fine.status, 'PAID')
        self.assertEqual(FinePaymentAllocation.objects.filter(fine=fine).count(), 2)

    def test_one_deposit_can_pay_two_fines(self):
        first = Fine.objects.create(member=self.member, reason='Late week 1', amount=5000, issued_by=self.treasurer)
        second = Fine.objects.create(member=self.member, reason='Late week 2', amount=5000, issued_by=self.treasurer)
        self.client.force_login(self.member)

        response = self.client.post(reverse('submit_deposit'), {
            'savings_account': self.account.pk,
            'include_fine_payment': 'on',
            'fine_payment_amount': '10000',
            'selected_fines': [str(first.pk), str(second.pk)],
            f'fine_allocation_{first.pk}': '5000',
            f'fine_allocation_{second.pk}': '5000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:41',
            'proof': SimpleUploadedFile('proof.jpg', b'payment proof', content_type='image/jpeg'),
            'remarks': '',
        })

        self.assertRedirects(response, reverse('my_contributions'))
        deposit = DepositSubmission.objects.latest('id')
        self.assertEqual(deposit.fine_allocations.count(), 2)
        self.assertEqual(sum(a.amount for a in deposit.fine_allocations.all()), Decimal('10000'))

        approve_deposit(deposit.pk, self.treasurer)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual((first.status, second.status), ('PAID', 'PAID'))

    def test_fine_allocation_sum_must_match_main_amount(self):
        first = Fine.objects.create(member=self.member, reason='Late week 1', amount=5000, issued_by=self.treasurer)
        second = Fine.objects.create(member=self.member, reason='Late week 2', amount=5000, issued_by=self.treasurer)
        form = DepositSubmissionForm(data={
            'savings_account': self.account.pk,
            'include_fine_payment': 'on',
            'fine_payment_amount': '10000',
            'selected_fines': [str(first.pk), str(second.pk)],
            f'fine_allocation_{first.pk}': '5000',
            f'fine_allocation_{second.pk}': '4000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:41',
        }, files={'proof': SimpleUploadedFile('proof.jpg', b'payment proof', content_type='image/jpeg')}, member=self.member)

        self.assertFalse(form.is_valid())
        self.assertIn('must equal the allocated total', form.errors['fine_payment_amount'][0])

    def test_duplicate_fine_selection_is_rejected(self):
        fine = Fine.objects.create(member=self.member, reason='Late', amount=5000, issued_by=self.treasurer)
        form = DepositSubmissionForm(data={
            'savings_account': self.account.pk,
            'include_fine_payment': 'on',
            'fine_payment_amount': '5000',
            'selected_fines': [str(fine.pk), str(fine.pk)],
            f'fine_allocation_{fine.pk}': '5000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '10:41',
        }, files={'proof': SimpleUploadedFile('proof.jpg', b'payment proof', content_type='image/jpeg')}, member=self.member)

        self.assertFalse(form.is_valid())
        self.assertIn('cannot be selected more than once', form.errors['selected_fines'][0])

    def test_stale_fine_balance_rolls_back_all_allocations(self):
        first = Fine.objects.create(member=self.member, reason='Late week 1', amount=5000, issued_by=self.treasurer)
        second = Fine.objects.create(member=self.member, reason='Late week 2', amount=5000, issued_by=self.treasurer)
        deposit = self.deposit(fine=10000)
        FinePaymentAllocation.objects.create(deposit=deposit, fine=first, amount=5000)
        FinePaymentAllocation.objects.create(deposit=deposit, fine=second, amount=5000)
        second.amount_paid = second.amount
        second.is_paid = True
        second.status = 'PAID'
        second.save(update_fields=['amount_paid', 'is_paid', 'status'])

        with self.assertRaises(ValidationError):
            approve_deposit(deposit.pk, self.treasurer)

        deposit.refresh_from_db(); first.refresh_from_db()
        self.assertEqual(deposit.status, 'PENDING')
        self.assertEqual(first.amount_paid, Decimal('0'))

    def test_combined_payment_allocates_both_ledgers(self):
        fine = Fine.objects.create(member=self.member, reason='Missed meeting', amount=15000, issued_by=self.treasurer)
        deposit = self.deposit(land=20000, fine=15000, selected_fine=fine)
        approve_deposit(deposit.id, self.treasurer)
        self.assertEqual(deposit.weekly_allocations.count(), 1)
        fine.refresh_from_db(); self.assertEqual(fine.status, 'PAID')

    def test_rejected_and_pending_do_not_allocate(self):
        deposit = self.deposit(land=20000)
        reject_deposit(deposit.id, self.treasurer, 'Invalid proof')
        self.assertFalse(WeeklySavingsAllocation.objects.filter(deposit=deposit).exists())
        self.assertEqual(savings_position(self.member)['weeks_behind'], 3)

    def test_duplicate_approval_is_blocked(self):
        deposit = self.deposit(land=20000)
        approve_deposit(deposit.id, self.treasurer)
        with self.assertRaises(ValidationError): approve_deposit(deposit.id, self.treasurer)
        self.assertEqual(WeeklySavingsAllocation.objects.filter(deposit=deposit).count(), 1)

    def test_fine_overpayment_is_blocked_atomically(self):
        fine = Fine.objects.create(member=self.member, reason='Late', amount=5000, issued_by=self.treasurer)
        deposit = self.deposit(fine=6000, selected_fine=fine)
        with self.assertRaises(ValidationError): approve_deposit(deposit.id, self.treasurer)
        deposit.refresh_from_db(); fine.refresh_from_db()
        self.assertEqual(deposit.status, 'PENDING'); self.assertEqual(fine.amount_paid, 0)

    def test_multiple_savings_accounts_are_isolated(self):
        second_account = SavingsAccount.objects.create(member=self.member, account_number='LIG-00001-B')
        approve_deposit(self.deposit(land=20000, account=second_account).id, self.treasurer)
        self.assertFalse(WeeklySavingsAllocation.objects.filter(savings_account=self.account).exists())
        self.assertEqual(WeeklySavingsAllocation.objects.filter(savings_account=second_account).count(), 1)


class DepositViewTests(DepositAccountingTests):
    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='LandGroup <landgroup@example.com>',
    )
    def test_submission_emails_member_and_treasurer(self):
        self.member.email = 'member@example.com'
        self.member.save(update_fields=['email'])
        self.treasurer.email = 'treasurer@example.com'
        self.treasurer.save(update_fields=['email'])
        deposit = self.deposit(land=20000)

        notify_deposit_submitted(deposit)

        self.assertEqual(len(mail.outbox), 2)
        self.assertEqual(
            {recipient for message in mail.outbox for recipient in message.to},
            {'member@example.com', 'treasurer@example.com'},
        )
        self.assertTrue(all(deposit.transaction_reference in message.subject for message in mail.outbox))

    @override_settings(
        EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
        DEFAULT_FROM_EMAIL='LandGroup <landgroup@example.com>',
    )
    def test_approval_emails_member_after_successful_review(self):
        self.member.email = 'member@example.com'
        self.member.save(update_fields=['email'])
        deposit = self.deposit(land=20000)
        self.client.force_login(self.treasurer)

        response = self.client.post(reverse('approve_deposit', args=[deposit.pk]))

        self.assertRedirects(response, reverse('manage_deposits'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('Deposit approved', mail.outbox[0].subject)
        self.assertEqual(mail.outbox[0].to, ['member@example.com'])

    def test_treasurer_can_post_direct_deposit_for_member_without_fine(self):
        self.client.force_login(self.treasurer)

        response = self.client.post(reverse('manage_deposits'), {
            'direct_deposit': '1',
            'member': self.member.pk,
            'savings_account': self.account.pk,
            'land_savings_amount': '20000',
            'fine_payment_amount': '',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '12:30',
            'remarks': '',
        })

        self.assertRedirects(response, reverse('manage_deposits'))
        deposit = DepositSubmission.objects.latest('id')
        self.assertEqual(deposit.status, 'APPROVED')
        self.assertEqual(deposit.land_savings_amount, Decimal('20000'))

    def test_treasurer_direct_deposit_can_pay_multiple_fines(self):
        first = Fine.objects.create(member=self.member, reason='Late week 1', amount=5000, issued_by=self.treasurer)
        second = Fine.objects.create(member=self.member, reason='Late week 2', amount=5000, issued_by=self.treasurer)
        self.client.force_login(self.treasurer)

        response = self.client.post(reverse('manage_deposits'), {
            'direct_deposit': '1',
            'member': self.member.pk,
            'savings_account': self.account.pk,
            'land_savings_amount': '',
            'fine_payment_amount': '10000',
            'selected_fines': [str(first.pk), str(second.pk)],
            f'fine_allocation_{first.pk}': '5000',
            f'fine_allocation_{second.pk}': '5000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '12:30',
            'remarks': '',
        })

        self.assertRedirects(response, reverse('manage_deposits'))
        deposit = DepositSubmission.objects.latest('id')
        self.assertEqual(deposit.status, 'APPROVED')
        self.assertEqual(deposit.fine_allocations.count(), 2)

    def test_treasurer_direct_deposit_auto_allocates_one_fine(self):
        fine = Fine.objects.create(member=self.member, reason='Late', amount=5000, issued_by=self.treasurer)
        self.client.force_login(self.treasurer)

        response = self.client.post(reverse('manage_deposits'), {
            'direct_deposit': '1',
            'member': self.member.pk,
            'savings_account': self.account.pk,
            'land_savings_amount': '',
            'fine_payment_amount': '5000',
            'payment_date': timezone.localdate().isoformat(),
            'payment_time': '12:30',
            'remarks': '',
        })

        self.assertRedirects(response, reverse('manage_deposits'))
        deposit = DepositSubmission.objects.latest('id')
        self.assertEqual(deposit.status, 'APPROVED')
        self.assertEqual(deposit.fine_allocations.get().fine, fine)

    def test_manage_deposits_renders_thumbnail_and_expanded_proof_modal(self):
        deposit = self.deposit(land=20000)
        deposit.proof = 'proofs/payment-proof.jpg'
        deposit.save(update_fields=['proof'])
        self.client.force_login(self.treasurer)

        response = self.client.get(reverse('manage_deposits'))

        self.assertContains(response, 'class="proof-thumbnail"')
        self.assertContains(response, f'id="proofModal{deposit.id}"')
        self.assertContains(response, 'class="proof-preview-image"')

    def test_manage_deposits_displays_member_remarks_and_blank_fallback(self):
        commented = self.deposit(land=20000, reference='COMMENTED')
        commented.remarks = 'Paid from mobile money\nPlease confirm.'
        commented.save(update_fields=['remarks'])
        self.deposit(land=20000, reference='BLANK').remarks
        self.client.force_login(self.treasurer)

        response = self.client.get(reverse('manage_deposits'))

        self.assertContains(response, 'Remarks / Comment')
        self.assertContains(response, 'Paid from mobile money')
        self.assertContains(response, 'Please confirm.')

    def test_current_week_status_separates_paid_and_unpaid_members(self):
        unpaid = MemberProfile.objects.create_user(username='unpaid', password='pw')
        approve_deposit(self.deposit(land=80000).id, self.treasurer)
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse('current_week_status'))
        paid_ids = [row['member'].id for row in response.context['paid_members']]
        unpaid_ids = [row['member'].id for row in response.context['unpaid_members']]
        self.assertIn(self.member.id, paid_ids)
        self.assertIn(unpaid.id, unpaid_ids)
        self.assertContains(response, 'weekly-paid-card')
        self.assertContains(response, 'weekly-unpaid-card')

    def test_only_treasurer_can_approve_and_endpoint_requires_post(self):
        deposit = self.deposit(land=20000)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse('approve_deposit', args=[deposit.id])).status_code, 405)
        self.client.post(reverse('approve_deposit', args=[deposit.id]))
        deposit.refresh_from_db(); self.assertEqual(deposit.status, 'PENDING')

    def test_filtered_contribution_csv_and_member_scope(self):
        approve_deposit(self.deposit(land=20000, reference='VISIBLE').id, self.treasurer)
        other = MemberProfile.objects.create_user(username='other', password='pw')
        other_account = SavingsAccount.objects.create(member=other, account_number='OTHER')
        DepositSubmission.objects.create(member=other, submitted_by=other, savings_account=other_account,
            starting_week=self.start, weeks_covered=0, amount=99999, land_savings_amount=99999,
            payment_date=timezone.localdate(), payment_time=timezone.localtime().time(), transaction_reference='HIDDEN')
        self.client.force_login(self.member)
        response = self.client.get(reverse('download_my_contributions', args=['csv']), {'status': 'APPROVED'})
        body = response.content.decode()
        self.assertIn('VISIBLE', body); self.assertNotIn('HIDDEN', body)

    def test_contribution_pagination_preserves_filter(self):
        for index in range(25): self.deposit(land=100, reference=f'P-{index}')
        self.client.force_login(self.member)
        response = self.client.get(reverse('my_contributions'), {'status': 'PENDING'})
        self.assertEqual(len(response.context['deposits']), 20)
        self.assertContains(response, 'status=PENDING&amp;page=2')
