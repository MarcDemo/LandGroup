from django.db import models
from django.contrib.auth.models import AbstractUser



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

    def __str__(self):
        return f"Group Settings (Week 1 Start: {self.week_one_start})"

    class Meta:
        verbose_name = "Group Setting"
        verbose_name_plural = "Group Settings"
