from django.urls import path
from . import views

urlpatterns = [
    # ── Provisioning (Sandbox only) ──────────────────────────────
    path("provision/user/",                        views.provision_create_user,    name="provision_create_user"),
    path("provision/user/<str:ref_id>/",           views.provision_get_user,       name="provision_get_user"),
    path("provision/user/<str:ref_id>/apikey/",    views.provision_create_key,     name="provision_create_key"),

    # ── Token ────────────────────────────────────────────────────
    path("token/",                                 views.get_token,                name="get_token"),

    # ── Account ──────────────────────────────────────────────────
    path("account/balance/",                       views.account_balance,          name="account_balance"),
    path("account/balance/<str:currency>/",        views.account_balance_currency, name="account_balance_currency"),
    path("account/validate/<str:id_type>/<str:account_id>/", views.validate_holder, name="validate_holder"),
    path("account/userinfo/<str:id_type>/<str:account_id>/", views.basic_user_info, name="basic_user_info"),

    # ── Request to Pay ───────────────────────────────────────────
    path("requesttopay/",                                              views.request_to_pay,        name="request_to_pay"),
    path("requesttopay/<str:reference_id>/status/",                    views.request_to_pay_status, name="rtp_status"),
    path("requesttopay/<str:reference_id>/notify/",                    views.delivery_notification, name="delivery_notification"),

    # ── Request to Withdraw ──────────────────────────────────────
    path("requesttowithdraw/",                                         views.request_to_withdraw,   name="request_to_withdraw"),
    path("requesttowithdraw/<str:reference_id>/status/",               views.withdraw_status,       name="withdraw_status"),

    # ── Invoices ─────────────────────────────────────────────────
    path("invoice/",                                                   views.create_invoice,        name="create_invoice"),
    path("invoice/<str:reference_id>/status/",                         views.invoice_status,        name="invoice_status"),
    path("invoice/<str:reference_id>/cancel/",                         views.cancel_invoice_view,   name="cancel_invoice"),

    # ── Payments ─────────────────────────────────────────────────
    path("payment/",                                                   views.create_payment,        name="create_payment"),
    path("payment/<str:reference_id>/status/",                         views.payment_status,        name="payment_status"),

    # ── Pre-Approvals ────────────────────────────────────────────
    path("preapproval/",                                               views.create_pre_approval,   name="create_pre_approval"),
    path("preapproval/<str:reference_id>/status/",                     views.pre_approval_status,   name="pre_approval_status"),
    path("preapproval/list/<str:id_type>/<str:account_id>/",           views.approved_pre_approvals, name="approved_pre_approvals"),
    path("preapproval/<str:preapproval_id>/cancel/",                   views.cancel_pre_approval,   name="cancel_pre_approval"),
]
