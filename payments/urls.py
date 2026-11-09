from django.urls import path

from payments import views

urlpatterns = [
    path("boost/packages/", views.boost_packages),
    path("boost/", views.create_boost_payment),
    path("boost/mine/", views.my_boost_payments),
    path("boost/<str:merchant_reference>/", views.boost_payment_detail),
    path("pesapal/ipn/", views.pesapal_ipn),
    path("pesapal/callback/", views.pesapal_callback),
]
