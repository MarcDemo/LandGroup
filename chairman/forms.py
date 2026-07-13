from django import forms
from groupcore.models import MemberProfile

class AddUserForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput, label="Password")

    class Meta:
        model = MemberProfile
        fields = ['username', 'email', 'role', 'password']

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])  # Encrypt password
        if commit:
            user.save()
        return user
