from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import F

from fines.models import Fine
from groupcore.models import MemberProfile
from .models import DepositSubmission, SavingsAccount


class DepositSubmissionForm(forms.ModelForm):
    include_land_savings = forms.BooleanField(required=False, label='Land Savings')
    include_fine_payment = forms.BooleanField(required=False, label='Fine Payment')
    land_savings_amount = forms.DecimalField(required=False, min_value=Decimal('0.01'), decimal_places=2)
    fine_payment_amount = forms.DecimalField(required=False, min_value=Decimal('0.01'), decimal_places=2)
    selected_fines = forms.ModelMultipleChoiceField(
        queryset=Fine.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple, label='Fines to pay',
    )
    payment_date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))
    payment_time = forms.TimeField(widget=forms.TimeInput(attrs={'type': 'time'}))
    proof = forms.FileField(required=True)

    class Meta:
        model = DepositSubmission
        fields = [
            'savings_account', 'payment_date', 'payment_time', 'proof', 'remarks',
            'include_land_savings', 'land_savings_amount', 'include_fine_payment',
            'fine_payment_amount', 'selected_fines',
        ]

    def _posted_list(self, name):
        if hasattr(self.data, 'getlist'):
            return self.data.getlist(name)
        value = self.data.get(name, [])
        if value in (None, ''):
            return []
        return list(value) if isinstance(value, (list, tuple)) else [str(value)]

    def __init__(self, *args, member=None, hide_fine_fields_without_balance=True, **kwargs):
        super().__init__(*args, **kwargs)
        if member is None and self.data.get('member'):
            member = MemberProfile.objects.filter(pk=self.data.get('member')).first()
        self.member = member
        if member:
            self.fields['savings_account'].queryset = SavingsAccount.objects.filter(member=member, is_active=True)
            outstanding_fines = Fine.objects.active().filter(
                member=member, amount__gt=F('amount_paid'),
            ).exclude(status='PAID').order_by('date_issued', 'id')
        else:
            self.fields['savings_account'].queryset = SavingsAccount.objects.filter(
                is_active=True,
            ).select_related('member')
            outstanding_fines = Fine.objects.active().filter(
                amount__gt=F('amount_paid'),
            ).exclude(status='PAID').select_related('member').order_by('member_id', 'date_issued', 'id')

        self.fields['selected_fines'].queryset = outstanding_fines
        if member and hide_fine_fields_without_balance and not outstanding_fines.exists():
            for name in ('include_fine_payment', 'fine_payment_amount', 'selected_fines'):
                self.fields.pop(name, None)

        self.fine_rows = []
        if 'selected_fines' in self.fields:
            checked_ids = set(self._posted_list('selected_fines')) if self.is_bound else set()
            for fine in outstanding_fines:
                field_name = f'fine_allocation_{fine.pk}'
                self.fields[field_name] = forms.DecimalField(
                    required=False, min_value=Decimal('0.01'), decimal_places=2,
                    label=f'Amount for fine #{fine.pk}',
                )
                self.fine_rows.append({
                    'fine': fine,
                    'amount_field': self[field_name],
                    'checked': str(fine.pk) in checked_ids,
                })

    def _clean_fine_allocations(self, data, member):
        fine_amount = data.get('fine_payment_amount') or Decimal('0')
        selected = list(data.get('selected_fines') or [])
        raw_ids = self._posted_list('selected_fines') if self.is_bound else []
        if len(raw_ids) != len(set(raw_ids)):
            self.add_error('selected_fines', 'A fine cannot be selected more than once.')
        if fine_amount and not selected:
            self.add_error('selected_fines', 'Select at least one fine for this payment.')

        allocations = []
        allocation_total = Decimal('0')
        for fine in selected:
            amount = data.get(f'fine_allocation_{fine.pk}')
            if not amount:
                self.add_error(f'fine_allocation_{fine.pk}', 'Enter an amount for this selected fine.')
                continue
            if member and fine.member_id != member.id:
                self.add_error('selected_fines', 'Every selected fine must belong to this member.')
            if amount > fine.outstanding_balance:
                self.add_error(
                    f'fine_allocation_{fine.pk}',
                    f'Amount cannot exceed the outstanding balance of UGX {fine.outstanding_balance:,.0f}.',
                )
            allocations.append((fine, amount))
            allocation_total += amount

        if fine_amount != allocation_total:
            self.add_error(
                'fine_payment_amount',
                f'Fine amount must equal the allocated total of UGX {allocation_total:,.0f}.',
            )
        data['fine_allocations'] = allocations
        return fine_amount

    def clean(self):
        data = super().clean()
        land = data.get('land_savings_amount') or Decimal('0')
        if data.get('include_land_savings') != bool(land):
            self.add_error('land_savings_amount', 'Enter an amount when Land Savings is selected.')

        fine = Decimal('0')
        if 'fine_payment_amount' in self.fields:
            fine = data.get('fine_payment_amount') or Decimal('0')
            if data.get('include_fine_payment') != bool(fine):
                self.add_error('fine_payment_amount', 'Enter an amount when Fine Payment is selected.')
            fine = self._clean_fine_allocations(data, self.member)
        if land + fine <= 0:
            raise ValidationError('Select at least one category and enter an amount.')
        data['calculated_total'] = land + fine
        return data


class DirectDepositForm(DepositSubmissionForm):
    member = forms.ModelChoiceField(queryset=MemberProfile.objects.exclude(is_superuser=True))
    proof = forms.FileField(required=False)

    class Meta(DepositSubmissionForm.Meta):
        fields = [
            'member', 'savings_account', 'payment_date', 'payment_time', 'proof',
            'remarks', 'land_savings_amount', 'fine_payment_amount', 'selected_fines',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, hide_fine_fields_without_balance=False, **kwargs)
        self.fields.pop('include_land_savings', None)
        self.fields.pop('include_fine_payment', None)
        self.fields['land_savings_amount'].label = 'Land Savings amount'
        self.fields['land_savings_amount'].help_text = 'Enter only if this direct deposit includes Land Savings.'
        self.fields['fine_payment_amount'].label = 'Fine payment amount (optional)'
        self.direct_fields = [
            self[name] for name in (
                'member', 'savings_account', 'payment_date', 'payment_time', 'proof',
                'remarks', 'land_savings_amount', 'fine_payment_amount',
            )
        ]

    def clean(self):
        data = forms.ModelForm.clean(self)
        member = data.get('member')
        account = data.get('savings_account')
        land = data.get('land_savings_amount') or Decimal('0')
        fine_amount = self._clean_fine_allocations(data, member)
        if land + fine_amount <= 0:
            raise ValidationError('Enter a Land Savings amount or a fine payment amount.')
        if account and member and account.member_id != member.id:
            self.add_error('savings_account', 'Select an account belonging to this member.')
        data['calculated_total'] = land + fine_amount
        return data
