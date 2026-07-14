from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import MemberProfile
from .forms import MemberRegistrationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from deposits.models import DepositSubmission, WeeklySavingsAllocation
from deposits.utils import savings_position
from django.utils import timezone
from fines.models import Fine
from django.db.models import Sum
from incomes.models import OtherIncome
from Assets_Expenditures.models import Expenditure, Asset
from documents.models import Document
from .forms import ProfileForm
from groupcore.models import GroupSettings
from datetime import date, timedelta
import random
from django.core.mail import send_mail
import random, datetime
from django.core.mail import EmailMultiAlternatives
from django.conf import settings


# Create your views here.
def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            if user.is_chairman():
                return redirect('chairman_dashboard')
            elif user.is_treasurer():
                return redirect('treasurer_dashboard')
            elif user.is_secretary():
                return redirect('secretary_dashboard')
            elif user.is_mobilizer():
                return redirect('mobilizer_dashboard')
            else:
                return redirect('member_dashboard')
        else:
            messages.error(request, "Invalid username or password")

    return render(request, 'groupcore/login.html')



RESET_CODE_EXPIRY_MINUTES = 10

def forgot_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            member = MemberProfile.objects.get(email=email)  # assuming MemberProfile has an email field
            code = str(random.randint(100000, 999999))

            # Store reset info in session
            request.session['reset_email'] = email
            request.session['reset_code'] = code
            request.session['reset_expiry'] = (timezone.now() + datetime.timedelta(minutes=RESET_CODE_EXPIRY_MINUTES)).isoformat()

            # Email content
            subject = "Your Password Reset Code"
            text_content = f"Your password reset code is: {code}. This code will expire in {RESET_CODE_EXPIRY_MINUTES} minutes."
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; background-color:#f8f9fa; padding:20px;">
              <div style="max-width:600px; margin:auto; background:#ffffff; border-radius:8px; padding:20px; border:1px solid #ddd;">
                <h2 style="color:#0d6efd;">Password Reset Request</h2>
                <p>Hello {member.username},</p>
                <p>You requested to reset your password. Use the code below to proceed. This code will expire in <strong>{RESET_CODE_EXPIRY_MINUTES} minutes</strong>:</p>
                <div style="font-size:24px; font-weight:bold; letter-spacing:3px; background:#f1f1f1; padding:10px; border-radius:5px; text-align:center;">
                  {code}
                </div>
                <p>If you did not request this, please ignore this email.</p>
                <p style="color:#888; font-size:12px;">This is an automated message, please do not reply.</p>
              </div>
            </body>
            </html>
            """

            email_msg = EmailMultiAlternatives(subject, text_content, settings.DEFAULT_FROM_EMAIL, [email])
            email_msg.attach_alternative(html_content, "text/html")
            email_msg.send()

            messages.success(request, "A verification code has been sent to your email.")
            return redirect('verify_code')

        except MemberProfile.DoesNotExist:
            messages.error(request, "No account found with that email.")

    return render(request, 'groupcore/forgot_password.html')


def verify_code(request):
    if request.method == 'POST':
        entered_code = request.POST.get('code')
        saved_code = request.session.get('reset_code')
        expiry_str = request.session.get('reset_expiry')

        if not saved_code or not expiry_str:
            messages.error(request, "Your reset request has expired. Please try again.")
            return redirect('forgot_password')

        expiry_time = datetime.datetime.fromisoformat(expiry_str)

        if timezone.now() > expiry_time:
            request.session.pop('reset_code', None)
            request.session.pop('reset_expiry', None)
            messages.error(request, "The verification code has expired. Please request a new one.")
            return redirect('forgot_password')

        if entered_code == saved_code:
            return redirect('set_new_password')
        else:
            messages.error(request, "Invalid verification code.")

    return render(request, 'groupcore/verify_code.html')


def set_new_password(request):
    if request.method == 'POST':
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, "Passwords do not match.")
            return redirect('set_new_password')

        email = request.session.get('reset_email')
        try:
            member = MemberProfile.objects.get(email=email)
            member.set_password(password1)  # change linked User's password
            member.save()

            # Clear all reset-related session data
            request.session.pop('reset_email', None)
            request.session.pop('reset_code', None)
            request.session.pop('reset_expiry', None)

            messages.success(request, "Password has been reset successfully. You can now log in.")
            return redirect('login')
        except MemberProfile.DoesNotExist:
            messages.error(request, "Error resetting password. Please try again.")

    return render(request, 'groupcore/set_new_password.html')


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out successfully.")
    return redirect('login')

def register_member(request):
    if not request.user.is_authenticated or not request.user.is_chairman():
        return redirect('login')

    if request.method == 'POST':
        form = MemberRegistrationForm(request.POST)
        if form.is_valid():
            member = form.save(commit=False)
            member.set_password(form.cleaned_data['password'])
            member.save()
            messages.success(request, "Member registered successfully.")
            return redirect('register')
    else:
        form = MemberRegistrationForm()

    return render(request, 'groupcore/register.html', {'form': form})



@login_required
def treasurer_dashboard(request):
    if not request.user.is_treasurer():
        messages.error(request, "Access denied.")
        return redirect('member_dashboard')

    # Sum of all approved deposits
    total_deposits = DepositSubmission.objects.filter(status='APPROVED').aggregate(total=Sum('amount'))['total'] or 0

    # Sum of other income
    total_other_income = OtherIncome.objects.aggregate(total=Sum('amount'))['total'] or 0

    # Group total cash = deposits + other income
    group_total_cash = total_deposits + total_other_income

    # Count of all pending deposits
    pending_deposits_count = DepositSubmission.objects.filter(status='PENDING').count()

    # Sum of unpaid fines
    total_unpaid_fines = Fine.objects.filter(is_paid=False).aggregate(total=Sum('amount'))['total'] or 0

    # Recent deposit submissions
    recent_deposits = DepositSubmission.objects.select_related('member').order_by('-date_submitted')[:10]

    # Total expenditures from each source
    spent_from_deposits = Expenditure.objects.filter(source='DEPOSITS').aggregate(Sum('amount'))['amount__sum'] or 0
    spent_from_income = Expenditure.objects.filter(source='INCOME').aggregate(Sum('amount'))['amount__sum'] or 0

    # Final balances
    available_deposits = total_deposits - spent_from_deposits
    available_income = total_other_income - spent_from_income

    context = {
        'group_total_cash': group_total_cash,
        'pending_deposits_count': pending_deposits_count,
        'total_unpaid_fines': total_unpaid_fines,
        'total_other_income': total_other_income,  # ✅ Add this to use in template
        'recent_deposits': recent_deposits,
        'available_deposits': available_deposits,
        'available_income': available_income,
    }

    return render(request, 'groupcore/treasurer_dashboard.html', context)


@login_required
def member_dashboard(request):
    member = request.user

    
    group_total_cash = DepositSubmission.objects.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or 0

    
    user_total = DepositSubmission.objects.filter(member=member, status='APPROVED').aggregate(Sum('land_savings_amount'))['land_savings_amount__sum'] or 0
    account = member.savings_accounts.filter(is_active=True).first()
    position = savings_position(member, account)
    settings_obj = GroupSettings.objects.first()
    weeks_paid = 0
    if account and settings_obj:
        weeks_paid = sum(1 for row in WeeklySavingsAllocation.objects.filter(savings_account=account).values('week_start').annotate(total=Sum('amount')) if row['total'] >= settings_obj.weekly_contribution)

    
    unpaid_fines = Fine.objects.filter(member=member).exclude(status='PAID')
    outstanding_fines = sum((fine.outstanding_balance for fine in unpaid_fines), 0)

    
    recent_deposits = DepositSubmission.objects.filter(member=member).order_by('-date_submitted')[:5]

    context = {
        'group_total_cash': group_total_cash,
        'user_total': user_total,
        'weeks_paid': weeks_paid,
        'outstanding_fines': outstanding_fines,
        'recent_deposits': recent_deposits,
        'unpaid_fines': unpaid_fines,
        'savings_position': position,
    }
    return render(request, 'groupcore/member_dashboard.html', context)

@login_required
def secretary_dashboard(request):
    total_documents = Document.objects.count()
    personal_documents = Document.objects.filter(user=request.user).count()
    total_members = MemberProfile.objects.exclude(is_superuser=True).count()

    return render(request, 'groupcore/secretary_dashboard.html', {
        'total_documents': total_documents,
        'personal_documents': personal_documents,
        'total_members': total_members
    })


@login_required
def my_profile(request):
    user = request.user
    editing = request.GET.get('edit') == 'true'

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            return redirect('my_profile')
    else:
        form = ProfileForm(instance=user)

    # Get the user's national ID document (if uploaded)
    nid_document = Document.objects.filter(user=user, document_type='NID').first()

    return render(request, 'groupcore/my_profile.html', {
        'form': form,
        'nid_document': nid_document,
        'editing': editing,
    })


@login_required
def mobilizer_dashboard(request):
    if not request.user.is_mobilizer:
        messages.error(request, "Access denied.")
        return redirect('login')

    settings = GroupSettings.objects.first()
    if not settings:
        messages.error(request, "Group starting week is not set.")
        return redirect('home')

    start_date = settings.week_one_start
    today = date.today()
    weeks_since_start = ((today - start_date).days) // 7
    current_week_start = start_date + timedelta(weeks=weeks_since_start)

    members = MemberProfile.objects.filter(is_superuser=False)
    paid_count = 0
    unpaid_count = 0

    for member in members:
        deposits = member.deposits.filter(status='APPROVED')
        covered_weeks = []

        for deposit in deposits:
            covered_weeks += deposit.get_covered_weeks()

        if current_week_start in covered_weeks:
            paid_count += 1
        else:
            unpaid_count += 1

    personal_deposits = request.user.deposits.filter(status='APPROVED').count()

    context = {
        'total_members': members.count(),
        'paid_this_week': paid_count,
        'unpaid_this_week': unpaid_count,
        'personal_deposits': personal_deposits,
        'current_week': current_week_start
    }
    return render(request, 'groupcore/mobilizer_dashboard.html', context)




@login_required
def chairman_dashboard(request):
    if not request.user.is_chairman():
        return redirect('home')  # Access control

    total_members = MemberProfile.objects.exclude(is_superuser=True).count()

    # Sum of approved deposits amounts
    total_deposits = DepositSubmission.objects.filter(status='APPROVED').aggregate(
        total=Sum('amount'))['total'] or 0

    # Sum of fines amounts
    total_fines = Fine.objects.filter(is_paid='True').aggregate(total=Sum('amount'))['total'] or 0

    total_documents = Document.objects.count()

    # Sum of other incomes
    total_income = OtherIncome.objects.aggregate(total=Sum('amount'))['total'] or 0

    # Sum of expenditures
    total_expenditures = Expenditure.objects.aggregate(total=Sum('amount'))['total'] or 0

    total_assets = Asset.objects.count()

    summary_cards = [
        {'title': 'Total Members', 'count': total_members, 'color': 'success'},
        {'title': 'Approved Deposits (UGX)', 'count': f"{total_deposits:,}", 'color': 'info'},
        {'title': 'Fines Collected (UGX)', 'count': f"{total_fines:,}", 'color': 'danger'},
        {'title': 'Other Income (UGX)', 'count': f"{total_income:,}", 'color': 'warning'},
        {'title': 'Documents', 'count': total_documents, 'color': 'secondary'},
        {'title': 'Assets', 'count': total_assets, 'color': 'dark'},
        {'title': 'Expenditures (UGX)', 'count': f"{total_expenditures:,}", 'color': 'primary'}
    ]

    # Weekly payment data for chart
    settings = GroupSettings.objects.first()
    weekly_status = {"paid": 0, "unpaid": 0}
    if settings:
        start_date = settings.week_one_start
        today = date.today()
        weeks_since_start = ((today - start_date).days) // 7
        current_week_start = start_date + timedelta(weeks=weeks_since_start)

        for member in MemberProfile.objects.filter(is_superuser=False):
            deposits = member.deposits.filter(status='APPROVED')
            covered_weeks = []
            for deposit in deposits:
                covered_weeks += deposit.get_covered_weeks()
            if current_week_start in covered_weeks:
                weekly_status["paid"] += 1
            else:
                weekly_status["unpaid"] += 1

    # Recent deposits - latest 5 deposits (all statuses)
    recent_deposits = DepositSubmission.objects.select_related('member').order_by('-date_submitted')[:5]

    # Recent fines - latest 5 fines
    recent_fines = Fine.objects.select_related('member').order_by('-date_issued')[:5]

    context = {
        "summary_cards": summary_cards,
        "total_members": total_members,
        "total_deposits": total_deposits,
        "total_fines": total_fines,
        "total_documents": total_documents,
        "total_income": total_income,
        "total_expenditures": total_expenditures,
        "total_assets": total_assets,
        "weekly_status": weekly_status,
        "recent_deposits": recent_deposits,
        "recent_fines": recent_fines,
    }

    return render(request, 'groupcore/chairman_dashboard.html', context)
