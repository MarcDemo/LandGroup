from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from datetime import time
from decimal import Decimal



# Create your models here.

class MemberProfile(AbstractUser):
    ROLE_CHOICES = [
        ('MEMBER', 'Member'),
        ('TREASURER', 'Treasurer'),
        ('CHAIRMAN', 'Chairman'),
        ('SECRETARY', 'Secretary'),
        ('MOBILIZER', 'Mobilizer'),
        
    ]

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='MEMBER')

    
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    next_of_kin_name = models.CharField(max_length=100, blank=True, null=True)
    next_of_kin_contact = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    

    def is_member(self):
        return self.role == 'MEMBER'

    def is_treasurer(self):
        return self.role == 'TREASURER'

    def is_chairman(self):
        return self.role == 'CHAIRMAN'
    
    def is_secretary(self):
        return self.role == 'SECRETARY'
    
    def is_mobilizer(self):
        return self.role == 'MOBILIZER'

    def __str__(self):
        return self.username
    
class GroupSettings(models.Model):
    week_one_start = models.DateField(help_text="The date of the first week (Week 1)")
    weekly_contribution = models.DecimalField(
        max_digits=10, decimal_places=2, default=20000,
        help_text="Required Land Savings contribution per week",
    )
    weekly_deadline_weekday = models.PositiveSmallIntegerField(
        choices=[
            (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
            (3, 'Thursday'), (4, 'Friday'), (5, 'Saturday'), (6, 'Sunday'),
        ],
        default=6,
        help_text='Weekday on which weekly Land Savings submissions close',
    )
    weekly_deadline_time = models.TimeField(
        default=time(23, 59),
        help_text='Submission cutoff time in the configured Django time zone',
    )
    automatic_fine_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('5000'),
        validators=[MinValueValidator(Decimal('0.01'))],
        help_text='Fine proposed for a late or missed weekly contribution',
    )
    automatic_fines_start_period = models.DateField(
        null=True, blank=True,
        help_text='First weekly period eligible for automatic fines; initialized on first reconciliation',
    )

    def __str__(self):
        return f"Group Settings (Week 1 Start: {self.week_one_start})"

    class Meta:
        verbose_name = "Group Setting"
        verbose_name_plural = "Group Settings"
