from django.db import models
from groupcore.models import MemberProfile

# Create your models here.
class Fine(models.Model):
    STATUS_CHOICES = [('UNPAID', 'Unpaid'), ('PARTIAL', 'Partially Paid'), ('PAID', 'Paid')]
    member = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='fines')
    reason = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    issued_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='issued_fines')
    date_issued = models.DateField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='UNPAID')
    remarks = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.member.username} - UGX {self.amount} - {self.reason[:30]}"

    @property
    def outstanding_balance(self):
        return max(self.amount - self.amount_paid, 0)
