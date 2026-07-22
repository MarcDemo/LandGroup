from django.urls import path
from . import views

urlpatterns = [
    path('my-fines/', views.my_fines, name='my_fines'),
    path('manage/', views.manage_fines, name='manage_fines'),
    path('add/', views.add_fine, name='add_fine'),
    path('mark-paid/<int:fine_id>/', views.mark_fine_paid, name='mark_fine_paid'),
    path('activate/<int:fine_id>/', views.activate_fine, name='activate_fine'),
    path('dismiss/<int:fine_id>/', views.dismiss_fine, name='dismiss_fine'),
    path('my-fines/download/<str:format>/', views.download_my_fines, name='download_my_fines'),
]
