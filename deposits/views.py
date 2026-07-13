import csv
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from fines.models import Fine
from groupcore.models import GroupSettings, MemberProfile
from .forms import DepositSubmissionForm, DirectDepositForm
from .models import DepositAuditLog, DepositSubmission, SavingsAccount
from .services import approve_deposit as approve_deposit_service, get_or_create_account, reject_deposit as reject_deposit_service
from .utils import savings_position, week_label

MONTHS = [(f'{i:02d}', datetime(2000, i, 1).strftime('%B')) for i in range(1, 13)]


def _page(request, queryset, size=20):
    return Paginator(queryset, size).get_page(request.GET.get('page'))


def _filtered_deposits(request, queryset):
    q = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').upper()
    category = request.GET.get('category', '')
    date_from, date_to = request.GET.get('date_from'), request.GET.get('date_to')
    if q:
        queryset = queryset.filter(Q(member__username__icontains=q) | Q(member__first_name__icontains=q) |
                                   Q(member__last_name__icontains=q) | Q(transaction_reference__icontains=q) |
                                   Q(savings_account__account_number__icontains=q))
    if status in dict(DepositSubmission.STATUS_CHOICES):
        queryset = queryset.filter(status=status)
    if category == 'land': queryset = queryset.filter(land_savings_amount__gt=0)
    if category == 'fine': queryset = queryset.filter(fine_payment_amount__gt=0)
    if date_from: queryset = queryset.filter(payment_date__gte=date_from)
    if date_to: queryset = queryset.filter(payment_date__lte=date_to)
    return queryset


@login_required
def submit_deposit(request):
    if request.user.is_treasurer():
        return redirect('manage_deposits')
    settings_obj = GroupSettings.objects.first()
    if not settings_obj:
        messages.error(request, 'Treasurer must configure Group Settings first.')
        return redirect('member_dashboard')
    get_or_create_account(request.user)
    form = DepositSubmissionForm(request.POST or None, request.FILES or None, member=request.user)
    if request.method == 'POST' and form.is_valid():
        deposit = form.save(commit=False)
        deposit.member = request.user
        deposit.submitted_by = request.user
        deposit.starting_week = settings_obj.week_one_start
        deposit.weeks_covered = 0
        deposit.land_savings_amount = form.cleaned_data.get('land_savings_amount') or 0
        deposit.fine_payment_amount = form.cleaned_data.get('fine_payment_amount') or 0
        deposit.amount = form.cleaned_data['calculated_total']
        deposit.save()
        DepositAuditLog.objects.create(deposit=deposit, actor=request.user, action='SUBMITTED')
        messages.success(request, f'Deposit submitted for review. Total: UGX {deposit.amount:,.0f}.')
        return redirect('my_contributions')
    return render(request, 'deposits/submit_deposit.html', {'form': form})


@login_required
def approve_deposit(request, deposit_id):
    if request.method != 'POST': return HttpResponseNotAllowed(['POST'])
    if not request.user.is_treasurer():
        messages.error(request, 'Only the Treasurer can approve deposits.')
        return redirect('member_dashboard')
    try:
        deposit = DepositSubmission.objects.get(pk=deposit_id)
        deposit.review_comment = request.POST.get('comment', '').strip()
        deposit.save(update_fields=['review_comment'])
        approve_deposit_service(deposit_id, request.user)
        messages.success(request, 'Deposit approved and all allocations posted atomically.')
    except (DepositSubmission.DoesNotExist, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect('manage_deposits')


@login_required
def reject_deposit(request, deposit_id):
    if request.method != 'POST': return HttpResponseNotAllowed(['POST'])
    if not request.user.is_treasurer():
        messages.error(request, 'Only the Treasurer can reject deposits.')
        return redirect('member_dashboard')
    try:
        reject_deposit_service(deposit_id, request.user, request.POST.get('comment', '').strip())
        messages.warning(request, 'Deposit rejected. No savings or fine balances were changed.')
    except (DepositSubmission.DoesNotExist, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect('manage_deposits')


def _member_deposits(request, member):
    qs = DepositSubmission.objects.filter(member=member).select_related('savings_account', 'reviewed_by').order_by('-payment_date', '-id')
    year, month, status = request.GET.get('year'), request.GET.get('month'), request.GET.get('status')
    if year: qs = qs.filter(payment_date__year=year)
    if month: qs = qs.filter(payment_date__month=month)
    if status: qs = qs.filter(status=status)
    return qs


@login_required
def my_contributions(request):
    deposits = _member_deposits(request, request.user)
    total_approved = deposits.filter(status='APPROVED').aggregate(total=Sum('amount'))['total'] or 0
    years = DepositSubmission.objects.filter(member=request.user).dates('payment_date', 'year')
    return render(request, 'deposits/my_contributions.html', {
        'deposits': _page(request, deposits), 'total_approved': total_approved, 'years': years,
        'months': MONTHS, 'selected_year': request.GET.get('year'), 'selected_month': request.GET.get('month'),
        'selected_status': request.GET.get('status', ''), 'querystring': request.GET.copy(),
    })


@login_required
def download_my_contributions(request, format):
    deposits = _member_deposits(request, request.user)
    headers = ['Transaction date', 'Reference', 'Account', 'Category', 'Land Savings', 'Fine Payment', 'Total', 'Status', 'Approved by', 'Approval date', 'Rejection reason']
    rows = [[d.payment_date, d.transaction_reference or '-', d.savings_account.account_number if d.savings_account else '-',
             d.categories_display, d.land_savings_amount, d.fine_payment_amount, d.amount, d.get_status_display(),
             d.reviewed_by.get_full_name() or d.reviewed_by.username if d.reviewed_by else '-',
             d.date_reviewed.strftime('%Y-%m-%d') if d.date_reviewed else '-', d.review_comment or '-'] for d in deposits]
    return _export(format, f'{request.user.username}-contributions', 'My Contribution History', headers, rows)


@login_required
def manage_deposits(request):
    if not request.user.is_treasurer():
        messages.error(request, 'Access denied.')
        return redirect('member_dashboard')
    form = DirectDepositForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and request.POST.get('direct_deposit') and form.is_valid():
        settings_obj = GroupSettings.objects.first()
        if not settings_obj:
            messages.error(request, 'Configure Group Settings first.')
        else:
            deposit = form.save(commit=False)
            deposit.submitted_by = request.user
            deposit.starting_week, deposit.weeks_covered = settings_obj.week_one_start, 0
            deposit.land_savings_amount = form.cleaned_data.get('land_savings_amount') or 0
            deposit.fine_payment_amount = form.cleaned_data.get('fine_payment_amount') or 0
            deposit.amount = form.cleaned_data['calculated_total']
            if not deposit.savings_account_id: deposit.savings_account = get_or_create_account(deposit.member)
            deposit.save()
            DepositAuditLog.objects.create(deposit=deposit, actor=request.user, action='SUBMITTED_DIRECT')
            try:
                approve_deposit_service(deposit.pk, request.user)
                messages.success(request, 'Direct deposit recorded and approved.')
            except ValidationError as exc: messages.error(request, str(exc))
            return redirect('manage_deposits')
    deposits = _filtered_deposits(request, DepositSubmission.objects.select_related('member', 'savings_account', 'reviewed_by').order_by('-date_submitted'))
    return render(request, 'deposits/manage_deposits.html', {
        'deposits': _page(request, deposits), 'form': form, 'active_status': request.GET.get('status', ''),
        'status_counts': {s: DepositSubmission.objects.filter(status=s).count() for s in ('PENDING','APPROVED','REJECTED')},
    })


@login_required
def treasurer_reports(request):
    if not request.user.is_treasurer(): return redirect('member_dashboard')
    today = timezone.localdate()
    settings_obj = GroupSettings.objects.first()
    period_date = settings_obj.week_one_start + timedelta(weeks=max((today - settings_obj.week_one_start).days // 7, 0)) if settings_obj else today
    members = MemberProfile.objects.exclude(is_superuser=True).order_by('first_name', 'username')
    report_data = []
    for member in members:
        account = member.savings_accounts.filter(is_active=True).first()
        position = savings_position(member, account)
        report_data.append({'member': member, 'account': account, 'position': position,
            'total_land': member.deposits.filter(status='APPROVED').aggregate(total=Sum('land_savings_amount'))['total'] or 0,
            'outstanding_fines': sum((f.outstanding_balance for f in member.fines.all()), Decimal('0'))})
    return render(request, 'deposits/treasurer_reports.html', {'report_data': _page(request, report_data), 'current_week': week_label(period_date)})


@login_required
def download_member_report(request, member_id, format):
    if not request.user.is_treasurer(): return redirect('member_dashboard')
    member = get_object_or_404(MemberProfile, id=member_id)
    deposits = DepositSubmission.objects.filter(member=member, status='APPROVED').order_by('payment_date')
    headers = ['Date', 'Reference', 'Land Savings', 'Fine Payment', 'Total', 'Approved by']
    rows = [[d.payment_date, d.transaction_reference or '-', d.land_savings_amount, d.fine_payment_amount, d.amount,
             d.reviewed_by.get_full_name() or d.reviewed_by.username if d.reviewed_by else '-'] for d in deposits]
    return _export(format, f'{member.username}-report', f'Contribution Report: {member.get_full_name() or member.username}', headers, rows)


@login_required
def download_all_reports(request, format):
    if not request.user.is_treasurer(): return redirect('member_dashboard')
    deposits = DepositSubmission.objects.filter(status='APPROVED').select_related('member', 'reviewed_by').order_by('member', 'payment_date')
    headers = ['Member', 'Date', 'Reference', 'Land Savings', 'Fine Payment', 'Total', 'Approved by']
    rows = [[d.member.get_full_name() or d.member.username, d.payment_date, d.transaction_reference or '-', d.land_savings_amount,
             d.fine_payment_amount, d.amount, d.reviewed_by.username if d.reviewed_by else '-'] for d in deposits]
    return _export(format, 'all-member-reports', 'All Member Contributions', headers, rows)


def _export(format, filename, title, headers, rows):
    if format in ('csv', 'excel'):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}.csv"'
        writer = csv.writer(response); writer.writerow([title]); writer.writerow(headers); writer.writerows(rows)
        return response
    if format == 'pdf':
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'
        doc = SimpleDocTemplate(response, pagesize=landscape(A4), leftMargin=24, rightMargin=24)
        styles = getSampleStyleSheet(); data = [headers] + [[str(value) for value in row] for row in rows]
        table = Table(data, repeatRows=1); table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#166534')),('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('GRID',(0,0),(-1,-1),.25,colors.grey),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP')]))
        doc.build([Paragraph(title, styles['Title']), Spacer(1, 12), table]); return response
    return HttpResponse('Unsupported format', status=400)


@login_required
def current_week_payment_status(request):
    if not (request.user.is_treasurer() or request.user.is_chairman() or request.user.is_mobilizer()): return redirect('member_dashboard')
    data = [{'member': m, 'position': savings_position(m)} for m in MemberProfile.objects.exclude(is_superuser=True)]
    current_label = data[0]['position']['current_week_label'] if data else week_label(timezone.localdate())
    return render(request, 'deposits/current_week_status.html', {'members_status': _page(request, data), 'current_week_label': current_label})
