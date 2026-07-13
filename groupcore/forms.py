from django import forms
from .models import MemberProfile

class MemberRegistrationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput)

    class Meta:
        model = MemberProfile
        fields = ['username', 'email', 'role', 'password', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact']


class ProfileForm(forms.ModelForm):
    class Meta:
        model = MemberProfile
        fields = ['first_name', 'last_name', 'email', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact', 'profile_picture']