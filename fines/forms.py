from django import forms
from .models import Fine
from groupcore.models import MemberProfile

class FineForm(forms.ModelForm):
    class Meta:
        model = Fine
        fields = ['member', 'amount', 'reason', 'remarks']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Optional: only show members (not chairman/treasurer)
        # self.fields['member'].queryset = MemberProfile.objects.filter(role='MEMBER')
