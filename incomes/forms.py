from django import forms
from .models import OtherIncome

class OtherIncomeForm(forms.ModelForm):
    class Meta:
        model = OtherIncome
        fields = ['source', 'fine', 'amount', 'description']
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fine'].queryset = self.fields['fine'].queryset.filter(is_paid=True)
