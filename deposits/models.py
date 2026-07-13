from django.db import models
from groupcore.models import MemberProfile
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal

# Create your models here.


class SavingsAccount(models.Model):
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='savings_accounts')
    account_number = models.CharField(max_length=30, unique=True)
    is_active = models.BooleanField(default=True)
    date_opened = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.account_number} - {self.member.get_full_name() or self.member.username}"


class DepositSubmission(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]

    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='deposits')
    savings_account = models.ForeignKey(SavingsAccount, on_delete=models.PROTECT, null=True, blank=True, related_name='deposits')
    starting_week = models.DateField(help_text="Week this deposit starts from")
    weeks_covered = models.PositiveIntegerField(help_text="How many weeks this deposit covers")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    land_savings_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])
    fine_payment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(Decimal('0'))])
    selected_fine = models.ForeignKey('fines.Fine', on_delete=models.PROTECT, null=True, blank=True, related_name='selected_deposits')
    transaction_reference = models.CharField(max_length=80, blank=True, db_index=True)
    proof = models.ImageField(upload_to='proofs/', blank=True, null=True)
    remarks = models.TextField(blank=True, null=True)
    review_comment = models.TextField(blank=True)

    payment_date = models.DateField(help_text="Date the payment was made")
    payment_time = models.TimeField(help_text="Time the payment was made")
    
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='PENDING')
    submitted_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='submitted_group_deposits')
    reviewed_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_group_deposits')
    date_submitted = models.DateTimeField(auto_now_add=True)
    date_reviewed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.member.username} - UGX {self.amount} ({self.status})"

    def get_covered_weeks(self):
        from datetime import timedelta
        return [self.starting_week + timedelta(weeks=i) for i in range(self.weeks_covered)]

    @property
    def categories_display(self):
        categories = []
        if self.land_savings_amount:
            categories.append('Land Savings')
        if self.fine_payment_amount:
            categories.append('Fine Payment')
        return ', '.join(categories) or 'Legacy deposit'


class WeeklySavingsAllocation(models.Model):
    deposit = models.ForeignKey(DepositSubmission, on_delete=models.PROTECT, related_name='weekly_allocations')
    savings_account = models.ForeignKey(SavingsAccount, on_delete=models.PROTECT, related_name='weekly_allocations')
    week_start = models.DateField(db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['week_start', 'id']
        constraints = [models.UniqueConstraint(fields=['deposit', 'week_start'], name='unique_deposit_week_allocation')]


class FinePaymentAllocation(models.Model):
    deposit = models.OneToOneField(DepositSubmission, on_delete=models.PROTECT, related_name='fine_allocation')
    fine = models.ForeignKey('fines.Fine', on_delete=models.PROTECT, related_name='payment_allocations')
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    created_at = models.DateTimeField(auto_now_add=True)


class DepositAuditLog(models.Model):
    deposit = models.ForeignKey(DepositSubmission, on_delete=models.PROTECT, related_name='audit_logs')
    action = models.CharField(max_length=30)
    actor = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='deposit_audit_actions')
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
