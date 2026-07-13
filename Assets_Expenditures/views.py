from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import Expenditure, Asset
from .forms import ExpenditureForm, AssetForm
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from deposits.models import DepositSubmission
from incomes.models import OtherIncome 
from django.core.paginator import Paginator

# Create your views here.

def get_current_balances():
    from decimal import Decimal

    total_deposits = DepositSubmission.objects.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    total_other_income = OtherIncome.objects.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    total_expenditures = Expenditure.objects.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    
    deposit_assets = Asset.objects.filter(source='DEPOSIT').aggregate(Sum('value'))['value__sum'] or Decimal('0')
    other_assets = Asset.objects.filter(source='OTHER').aggregate(Sum('value'))['value__sum'] or Decimal('0')

    available_deposit_cash = total_deposits - total_expenditures - deposit_assets
    available_other_income = total_other_income - other_assets

    return {
        'deposit_cash': available_deposit_cash,
        'other_income': available_other_income,
    }
# 📦 View Assets
@login_required
def list_assets(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    assets = Asset.objects.order_by('-date_acquired')
    total_assets = assets.aggregate(Sum('value'))['value__sum'] or 0

    return render(request, 'Assets_Expenditures/assets_list.html', {
        'assets': Paginator(assets, 20).get_page(request.GET.get('page')),
        'total_assets': total_assets,
    })


# ➕ Add Asset
@login_required
def add_asset(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = AssetForm(request.POST)
        if form.is_valid():
            asset = form.save()
            messages.success(request, f"Asset '{asset.name}' added successfully.")
            return redirect('list_assets')
    else:
        form = AssetForm()

    available_deposits, _ = get_current_balances()

    return render(request, 'Assets_Expenditures/add_asset.html', {
        'form': form,
        'available_deposits': available_deposits
    })


# 💸 View Expenditures
@login_required
def list_expenditures(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    expenditures = Expenditure.objects.order_by('-date_spent')
    total_expenditures = expenditures.aggregate(Sum('amount'))['amount__sum'] or 0

    return render(request, 'Assets_Expenditures/expenditures_list.html', {
        'expenditures': Paginator(expenditures, 20).get_page(request.GET.get('page')),
        'total_expenditures': total_expenditures,
    })


# ➕ Add Expenditure
@login_required
def add_expenditure(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = ExpenditureForm(request.POST)
        if form.is_valid():
            expenditure = form.save()
            messages.success(request, f"Expenditure '{expenditure.description}' added successfully.")
            return redirect('list_expenditures')
    else:
        form = ExpenditureForm()

    available_deposits, available_other_income = get_current_balances()

    return render(request, 'Assets_Expenditures/add_expenditure.html', {
        'form': form,
        'available_deposits': available_deposits,
        'available_other_income': available_other_income,
    })
