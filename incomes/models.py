
from django.db import models
from deposits.models import MemberProfile
from fines.models import Fine

# Create your models here.

class OtherIncome(models.Model):
    SOURCE_CHOICES = [
        ('FINE', 'Fine Payment'),
        ('INTEREST', 'Interest Earned'),
        ('OTHER', 'Other Income'),
    ]

    source = models.CharField(max_length=20, choices=SOURCE_CHOICES)
    fine = models.ForeignKey(Fine, on_delete=models.SET_NULL, null=True, blank=True, related_name='income_record')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField(blank=True, null=True)
    date_received = models.DateField(auto_now_add=True)
    recorded_by = models.ForeignKey(MemberProfile, on_delete=models.SET_NULL, null=True, related_name='recorded_incomes')

    def __str__(self):
        return f"{self.source} - UGX {self.amount}"