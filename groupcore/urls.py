from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_member, name='register'), 
    path('chairman/dashboard/', views.chairman_dashboard, name='chairman_dashboard'),
    path('treasurer/dashboard/', views.treasurer_dashboard, name='treasurer_dashboard'),
    path('member/dashboard/', views.member_dashboard, name='member_dashboard'),
    path('secretary/dashboard/', views.secretary_dashboard, name='secretary_dashboard'),
    path('mobilizer/dashboard/', views.mobilizer_dashboard, name='mobilizer_dashboard'),
    path('my-profile/', views.my_profile, name='my_profile'),
    path('forgot-password/', views.forgot_password, name='forgot_password'),
    path('verify-code/', views.verify_code, name='verify_code'),
    path('set-new-password/', views.set_new_password, name='set_new_password'),

]
