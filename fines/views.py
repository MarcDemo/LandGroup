from django.shortcuts import render, redirect, get_object_or_404
from .models import Fine
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Sum
from django.core.paginator import Paginator
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseNotAllowed
from deposits.views import _export
from django.contrib import messages
from django.utils import timezone
from .forms import FineForm
from .services import decide_automatic_fine, ordered_for_management, reconcile_automatic_fines
from incomes.models import OtherIncome

# Create your views here.
@login_required
def my_fines(request):
    fines = Fine.objects.active().filter(member=request.user).order_by('-date_issued')
    total_fines = fines.aggregate(Sum('amount'))['amount__sum'] or 0
    outstanding_total = sum((fine.outstanding_balance for fine in fines), 0)
    fines = Paginator(fines, 20).get_page(request.GET.get('page'))
    return render(request, 'fines/my_fines.html', {
        'fines': fines,
        'total_fines': total_fines,
        'outstanding_total': outstanding_total,
    })

@login_required
def manage_fines(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    reconcile_automatic_fines()
    fines = Paginator(ordered_for_management(), 20).get_page(request.GET.get('page'))
    return render(request, 'fines/manage_fines.html', {'fines': fines})


@login_required
def add_fine(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    if request.method == 'POST':
        form = FineForm(request.POST)
        if form.is_valid():
            fine = form.save(commit=False)
            fine.issued_by = request.user
            fine.save()
            messages.success(request, f"Fine added for {fine.member.username}.")
            return redirect('manage_fines')
    else:
        form = FineForm()

    return render(request, 'fines/add_fine.html', {'form': form})


@login_required
@transaction.atomic
def mark_fine_paid(request, fine_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    fine = get_object_or_404(Fine.objects.active().select_for_update(), id=fine_id)
    fine.is_paid = True
    fine.amount_paid = fine.amount
    fine.status = 'PAID'
    fine.save(update_fields=['is_paid', 'amount_paid', 'status'])
    if not OtherIncome.objects.filter(fine=fine).exists():
        OtherIncome.objects.create(
            source='FINE',
            fine=fine,
            amount=fine.amount,
            description=f"Fine payment from {fine.member.get_full_name() or fine.member.username}",
            recorded_by=request.user
        )

    messages.success(request, f"Marked fine for {fine.member.username} as paid.")
    return redirect('manage_fines')


@login_required
def download_my_fines(request, format):
    fines = Fine.objects.active().filter(member=request.user).prefetch_related('payment_allocations__deposit__reviewed_by').order_by('-date_issued')
    headers = ['Fine date', 'Description', 'Original amount', 'Amount paid', 'Balance', 'Status', 'Related transactions', 'Approved by', 'Approval date']
    rows = []
    for fine in fines:
        allocations = list(fine.payment_allocations.select_related('deposit__reviewed_by'))
        rows.append([fine.date_issued, fine.reason, fine.amount, fine.amount_paid, fine.outstanding_balance, fine.get_status_display(),
                     ', '.join(a.deposit.transaction_reference or f'Deposit #{a.deposit_id}' for a in allocations) or '-',
                     ', '.join((a.deposit.reviewed_by.get_full_name() or a.deposit.reviewed_by.username) for a in allocations if a.deposit.reviewed_by) or '-',
                     ', '.join(a.deposit.date_reviewed.strftime('%Y-%m-%d') for a in allocations if a.deposit.date_reviewed) or '-'])
    return _export(format, f'{request.user.username}-fines', 'My Fine Transaction History', headers, rows)


def _decide_fine(request, fine_id, decision):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if not request.user.is_treasurer():
        messages.error(request, 'Access denied.')
        return redirect('member_dashboard')
    try:
        fine = decide_automatic_fine(
            fine_id, request.user, decision, request.POST.get('comment', '').strip()
        )
        verb = 'activated' if decision == 'ACTIVE' else 'dismissed'
        messages.success(request, f'Fine for {fine.member.username} {verb}.')
    except (Fine.DoesNotExist, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect('manage_fines')


@login_required
def activate_fine(request, fine_id):
    return _decide_fine(request, fine_id, 'ACTIVE')


@login_required
def dismiss_fine(request, fine_id):
    return _decide_fine(request, fine_id, 'DISMISSED')
