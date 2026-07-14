from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from groupcore.models import MemberProfile
from fines.models import Fine
from .models import DepositSubmission, SavingsAccount


class DepositSubmissionForm(forms.ModelForm):
    include_land_savings = forms.BooleanField(required=False, label='Land Savings')
    include_fine_payment = forms.BooleanField(required=False, label='Fine Payment')
    land_savings_amount = forms.DecimalField(required=False, min_value=Decimal('0.01'), decimal_places=2)
    fine_payment_amount = forms.DecimalField(required=False, min_value=Decimal('0.01'), decimal_places=2)
    selected_fine = forms.ModelChoiceField(queryset=Fine.objects.none(), required=False, label='Fine to pay')
    payment_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    payment_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    proof = forms.FileField(required=True)

    class Meta:
        model = DepositSubmission
        fields = ['savings_account', 'payment_date', 'payment_time',
                  'proof', 'remarks', 'include_land_savings', 'land_savings_amount',
                  'include_fine_payment', 'fine_payment_amount', 'selected_fine']

    def __init__(self, *args, member=None, **kwargs):
        super().__init__(*args, **kwargs)
        if member is None and self.data.get('member'):
            member = MemberProfile.objects.filter(pk=self.data.get('member')).first()
        self.member = member
        if member:
            self.fields['savings_account'].queryset = SavingsAccount.objects.filter(member=member, is_active=True)
            self.fields['selected_fine'].queryset = Fine.objects.filter(member=member).exclude(status='PAID')
        elif 'member' in self.fields:
            self.fields['savings_account'].queryset = SavingsAccount.objects.filter(is_active=True).select_related('member')
            self.fields['selected_fine'].queryset = Fine.objects.exclude(status='PAID').select_related('member')

    def clean(self):
        data = super().clean()
        land = data.get('land_savings_amount') or Decimal('0')
        fine = data.get('fine_payment_amount') or Decimal('0')
        if data.get('include_land_savings') != bool(land):
            self.add_error('land_savings_amount', 'Enter an amount when Land Savings is selected.')
        if data.get('include_fine_payment') != bool(fine):
            self.add_error('fine_payment_amount', 'Enter an amount when Fine Payment is selected.')
        selected = data.get('selected_fine')
        if fine and not selected:
            self.add_error('selected_fine', 'Select the fine this payment should reduce.')
        if selected and fine > selected.outstanding_balance:
            self.add_error('fine_payment_amount', 'Amount cannot exceed the fine balance.')
        if land + fine <= 0:
            raise ValidationError('Select at least one category and enter an amount.')
        data['calculated_total'] = land + fine
        return data


class DirectDepositForm(DepositSubmissionForm):
    member = forms.ModelChoiceField(queryset=MemberProfile.objects.exclude(is_superuser=True))
    proof = forms.FileField(required=False)

    class Meta(DepositSubmissionForm.Meta):
        fields = ['member'] + DepositSubmissionForm.Meta.fields

    def clean(self):
        data = super().clean()
        member = data.get('member')
        account, fine = data.get('savings_account'), data.get('selected_fine')
        if account and member and account.member_id != member.id:
            self.add_error('savings_account', 'Select an account belonging to this member.')
        if fine and member and fine.member_id != member.id:
            self.add_error('selected_fine', 'Select a fine belonging to this member.')
        return data
