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

    def test_treasurer_gets_role_specific_mobile_actions(self):
        treasurer = MemberProfile.objects.create_user(
            username='mobile-treasurer', password='pw', role='TREASURER'
        )
        self.client.force_login(treasurer)
        response = self.client.get(reverse('treasurer_dashboard'))
        self.assertContains(response, 'mobile-tabbar')
        self.assertContains(response, reverse('manage_deposits'))
        self.assertContains(response, reverse('treasurer_reports'))

    def test_login_has_group_title_and_rotating_images(self):
        response = self.client.get(reverse('login'))
        self.assertContains(response, 'Land Investment Group')
        self.assertContains(response, 'auth-slideshow')
        self.assertContains(response, 'images/land_savings.webp')
        self.assertContains(response, 'images/jar_savings.webp')
        self.assertContains(response, 'images/jar_and_coins.webp')
