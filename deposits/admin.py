from django.contrib import admin
from .models import DepositAuditLog, DepositSubmission, FinePaymentAllocation, SavingsAccount, WeeklySavingsAllocation

# Register your models here.
admin.site.register(DepositSubmission)
admin.site.register(SavingsAccount)
admin.site.register(WeeklySavingsAllocation)
admin.site.register(FinePaymentAllocation)
admin.site.register(DepositAuditLog)
