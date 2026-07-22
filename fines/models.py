from django.db import models
from groupcore.models import MemberProfile

# Create your models here.
class FineQuerySet(models.QuerySet):
    def active(self):
        return self.filter(approval_status='ACTIVE')


class Fine(models.Model):
    STATUS_CHOICES = [('UNPAID', 'Unpaid'), ('PARTIAL', 'Partially Paid'), ('PAID', 'Paid')]
    ORIGIN_CHOICES = [('MANUAL', 'Manual'), ('AUTOMATIC', 'Automatic')]
    APPROVAL_CHOICES = [
        ('PENDING', 'Pending approval'),
        ('ACTIVE', 'Active'),
        ('DISMISSED', 'Dismissed'),
    ]
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='fines')
    reason = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    issued_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='issued_fines')
    date_issued = models.DateField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='UNPAID')
    remarks = models.TextField(blank=True, null=True)
    origin = models.CharField(max_length=10, choices=ORIGIN_CHOICES, default='MANUAL')
    approval_status = models.CharField(max_length=10, choices=APPROVAL_CHOICES, default='ACTIVE')
    affected_week = models.DateField(null=True, blank=True, db_index=True)
    decided_by = models.ForeignKey(
        MemberProfile, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='decided_fines',
    )
    decision_at = models.DateTimeField(null=True, blank=True)
    decision_comment = models.TextField(blank=True)
    objects = FineQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['member', 'affected_week'],
                condition=models.Q(origin='AUTOMATIC'),
                name='unique_automatic_fine_member_week',
            ),
        ]

    def __str__(self):
        return f"{self.member.username} - UGX {self.amount} - {self.reason[:30]}"

    @property
    def outstanding_balance(self):
        return max(self.amount - self.amount_paid, 0)
