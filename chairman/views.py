from groupcore.models import MemberProfile, GroupSettings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required, user_passes_test
from deposits.models import DepositSubmission
from fines.models import Fine
from documents.models import Document
from incomes.models import OtherIncome
from django.conf import settings
from datetime import timedelta, date, datetime
from Assets_Expenditures.models import Asset, Expenditure
from .forms import AddUserForm
from django.db.models import Q
from django.utils.timezone import now
import calendar
from calendar import month_name
from django.http import HttpResponse
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from django.core.paginator import Paginator
from deposits.utils import savings_position, week_label

# Create your views here.
def is_chairman(user):
    return user.is_authenticated and user.is_chairman()

@login_required
def manage_users(request):
    if not is_chairman(request.user):
        messages.error(request, "Access denied. Only Chairman can manage users.")
        return redirect('chairman_dashboard')

    users = MemberProfile.objects.exclude(id=request.user.id).exclude(is_superuser=True).order_by('username')
    return render(request, 'chairman/manage_users.html', {'users': Paginator(users, 20).get_page(request.GET.get('page'))})

@login_required
def toggle_user_status(request, user_id):
    if not is_chairman(request.user):
        messages.error(request, "Access denied. Only Chairman can toggle user status.")
        return redirect('chairman_dashboard')

    user = get_object_or_404(MemberProfile, pk=user_id)
    user.is_active = not user.is_active
    user.save()
    status = "activated" if user.is_active else "deactivated"
    messages.success(request, f"{user.username} has been {status}.")
    return redirect('manage_users')


@login_required
def add_user(request):
    if not is_chairman(request.user):
        messages.error(request, "Access denied. Only Chairman can add users.")
        return redirect('chairman_dashboard')

    if request.method == 'POST':
        form = AddUserForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "User added successfully.")
            return redirect('manage_users')
    else:
        form = AddUserForm()

    return render(request, 'chairman/add_user.html', {'form': form})



#Reports Views

@login_required
def chairman_deposit_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    # Base queryset: all approved deposits, ordered newest first
    base_qs = DepositSubmission.objects.filter(status='APPROVED').order_by('-payment_date')

    # Dropdown options (always from base dataset)
    years = base_qs.dates('payment_date', 'year', order='DESC')
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]

    # Get filter parameters
    name_query = request.GET.get('name')
    if not name_query or name_query.strip().lower() == 'none':
        name_query = None
    year_query = request.GET.get('year')
    month_query = request.GET.get('month')

    # Start with full dataset for display
    deposits = base_qs

    # Apply filters
    if name_query:
        deposits = deposits.filter(member__username__icontains=name_query)

    if year_query:
        try:
            deposits = deposits.filter(payment_date__year=int(year_query))
        except (ValueError, TypeError):
            pass

    if month_query:
        try:
            deposits = deposits.filter(payment_date__month=int(month_query))
        except (ValueError, TypeError):
            pass

    # Handle PDF export
    if request.GET.get('export') == 'pdf':
        export_qs = deposits  # export what’s currently filtered

        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="member_deposits_report.pdf"'

        doc = SimpleDocTemplate(response, pagesize=A4)
        styles = getSampleStyleSheet()

        elements = [
            Paragraph("Member Deposits Report", styles['Heading1']),
            Spacer(1, 12),
        ]

        # Table header
        data = [['#', 'Member', 'Amount (UGX)', 'Payment Date', 'Payment Time', 'Status']]

        # Table rows
        for i, dep in enumerate(export_qs, 1):
            data.append([
                i,
                dep.member.username,
                f"{dep.amount:,.0f}",
                dep.payment_date.strftime('%Y-%m-%d') if dep.payment_date else '-',
                dep.payment_time.strftime('%H:%M') if dep.payment_time else '-',
                dep.status
            ])

        # Table styling
        table = Table(data, colWidths=[30, 100, 80, 90, 90, 80])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#4CAF50")),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.grey),
        ]))

        elements.append(table)
        doc.build(elements)
        return response

    # Render HTML page
    return render(request, 'chairman/deposit_report.html', {
        'deposits': Paginator(deposits, 20).get_page(request.GET.get('page')),
        'years': years,
        'months': months,
        'name_query': name_query,
        'year_query': year_query,
        'month_query': month_query,
    })

@login_required
def chairman_fine_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    fines = Fine.objects.all().order_by('-date_issued')
    return render(request, 'chairman/fine_report.html', {'fines': Paginator(fines, 20).get_page(request.GET.get('page'))})


@login_required
def chairman_document_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    documents = Document.objects.all().order_by('-uploaded_at')
    return render(request, 'chairman/document_report.html', {'documents': Paginator(documents, 20).get_page(request.GET.get('page'))})


@login_required
def chairman_income_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    incomes = OtherIncome.objects.all().order_by('-date_received')
    return render(request, 'chairman/income_report.html', {'incomes': Paginator(incomes, 20).get_page(request.GET.get('page'))})


@login_required
def chairman_weekly_payment_status(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    settings = GroupSettings.objects.first()
    if not settings:
        messages.error(request, "Group starting week is not set.")
        return redirect('chairman_dashboard')

    today = date.today()
    rows = [{'member': member, 'position': savings_position(member)} for member in MemberProfile.objects.exclude(is_superuser=True)]
    current_label = rows[0]['position']['current_week_label'] if rows else week_label(today)
    context = {'current_week_label': current_label, 'members_status': Paginator(rows, 20).get_page(request.GET.get('page'))}
    return render(request, 'chairman/current_week_status.html', context)


@login_required
def chairman_asset_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    assets = Asset.objects.all().order_by('-date_acquired')
    return render(request, 'chairman/asset_report.html', {'assets': Paginator(assets, 20).get_page(request.GET.get('page'))})


@login_required
def chairman_expenditure_report(request):
    if not request.user.is_chairman():
        messages.error(request, "Access denied.")
        return redirect('chairman_dashboard')

    expenditures = Expenditure.objects.all().order_by('-date_spent')
    return render(request, 'chairman/expenditure_report.html', {'expenditures': Paginator(expenditures, 20).get_page(request.GET.get('page'))})


from django.http import JsonResponse
from django.db.models.functions import ExtractYear

@login_required
def debug_deposit_years(request):
    # Only allow chairman to view this debug info
    if not request.user.is_chairman():
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Get distinct years from all approved deposits
    years_in_db = (
        DepositSubmission.objects.filter(status='APPROVED')
        .annotate(year=ExtractYear('payment_date'))
        .values_list('year', flat=True)
        .distinct()
        .order_by('-year')
    )

    return JsonResponse({'years': list(years_in_db)})






