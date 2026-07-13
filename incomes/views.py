from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from .models import OtherIncome
from .forms import OtherIncomeForm
from django.core.paginator import Paginator

# Create your views here.

@login_required
def income_list(request):
    incomes = Paginator(OtherIncome.objects.select_related('fine', 'recorded_by').order_by('-date_received'), 20).get_page(request.GET.get('page'))
    return render(request, 'incomes/income_list.html', {'incomes': incomes})

@login_required
def add_income(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = OtherIncomeForm(request.POST)
        if form.is_valid():
            income = form.save(commit=False)
            income.recorded_by = request.user
            income.save()
            messages.success(request, "Income recorded successfully.")
            return redirect('income_list')
    else:
        form = OtherIncomeForm()

    return render(request, 'incomes/add_income.html', {'form': form})
