from datetime import date

from django.test import TestCase
from django.urls import reverse

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
