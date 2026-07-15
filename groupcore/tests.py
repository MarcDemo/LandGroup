from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deposits.models import DepositSubmission
from .models import GroupSettings, MemberProfile


class MobileAppShellTests(TestCase):
    def setUp(self):
        GroupSettings.objects.create(
            week_one_start=date(2025, 7, 7), weekly_contribution=20000
        )

    def test_member_gets_mobile_deposit_and_contribution_actions(self):
        member = MemberProfile.objects.create_user(
            username='mobile-member', password='pw', role='MEMBER'
        )
        self.client.force_login(member)
        response = self.client.get(reverse('member_dashboard'))
        self.assertContains(response, 'mobile-tabbar')
        self.assertContains(response, reverse('submit_deposit'))
        self.assertContains(response, reverse('my_contributions'))
        self.assertContains(response, '>Deposit</span>', html=False)
        self.assertContains(response, 'sidebar-logout')
        self.assertContains(response, reverse('logout'))

    def test_proof_preview_has_mobile_close_controls(self):
        member = MemberProfile.objects.create_user(
            username='proof-member', password='pw', role='MEMBER'
        )
        deposit = DepositSubmission.objects.create(
            member=member,
            submitted_by=member,
            starting_week=date(2025, 7, 7),
            weeks_covered=1,
            amount=Decimal('20000'),
            land_savings_amount=Decimal('20000'),
            payment_date=timezone.localdate(),
            payment_time=timezone.localtime().time(),
        )
        deposit.proof = 'proofs/mobile-proof.jpg'
        deposit.save(update_fields=['proof'])

        self.client.force_login(member)
        response = self.client.get(reverse('member_dashboard'))

        self.assertContains(response, f'id="proofModal{deposit.id}"')
        self.assertContains(response, 'class="btn-close" data-bs-dismiss="modal"')
        self.assertContains(response, 'data-bs-dismiss="modal">Close</button>')
        self.assertContains(response, 'modal-dialog-scrollable')
        table_end = response.content.index(b'</table>')
        modal_start = response.content.index(f'id="proofModal{deposit.id}"'.encode())
        self.assertGreater(modal_start, table_end)

    def test_treasurer_gets_role_specific_mobile_actions(self):
        treasurer = MemberProfile.objects.create_user(
            username='mobile-treasurer', password='pw', role='TREASURER'
        )
        self.client.force_login(treasurer)
        response = self.client.get(reverse('treasurer_dashboard'))
        self.assertContains(response, 'mobile-tabbar')
        self.assertContains(response, reverse('manage_deposits'))
        self.assertContains(response, reverse('treasurer_reports'))
        self.assertContains(response, 'My Member Account')
        self.assertContains(response, reverse('member_dashboard'))
        self.assertContains(response, reverse('my_contributions'))
        self.assertContains(response, reverse('my_fines'))
        personal_deposit = self.client.get(reverse('submit_deposit'))
        self.assertEqual(personal_deposit.status_code, 200)

    def test_login_has_group_title_and_rotating_images(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'Land Investment Group')
        self.assertContains(response, 'auth-slideshow')
        self.assertContains(response, 'images/land_savings.webp')
        self.assertContains(response, 'images/jar_savings.webp')
        self.assertContains(response, 'images/jar_and_coins.webp')
        self.assertContains(response, 'https://wa.me/message/3XKDABIYDNBEH1')
        self.assertContains(response, 'Contact Deap Technologies on WhatsApp')
