# MTN MoMo Django Integration

## Quick Start

### 1. Replace your credentials in `momo_project/momo_config.py`

```python
SUBSCRIPTION_KEY    = "your_subscription_key"
API_USER            = "your_api_user_uuid"
API_KEY             = "your_api_key"
TARGET_ENVIRONMENT  = "sandbox"           # change to e.g. "mtnuganda" in production
PROVIDER_CALLBACK_HOST = "https://yourcallback.com"
```

### 2. Install & run

```bash
pip install django requests
python manage.py migrate
python manage.py runserver
```

---

## All Endpoints

All URLs are prefixed with `/momo/`.

### Provisioning (Sandbox only — one-time setup)

| Method | URL | Description |
|--------|-----|-------------|
| POST | `/momo/provision/user/` | Create API user (returns reference_id) |
| GET | `/momo/provision/user/<ref_id>/` | Get API user details |
| POST | `/momo/provision/user/<ref_id>/apikey/` | Generate API key |

### Token

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/momo/token/` | Get a fresh Bearer token |

### Account

| Method | URL | Description |
|--------|-----|-------------|
| GET | `/momo/account/balance/` | Get account balance |
| GET | `/momo/account/balance/<currency>/` | Balance in specific currency (e.g. UGX) |
| GET | `/momo/account/validate/msisdn/256700000000/` | Check if holder is active |
| GET | `/momo/account/userinfo/msisdn/256700000000/` | Get basic KYC info |

### Request to Pay

| Method | URL | Body / Params |
|--------|-----|---------------|
| POST | `/momo/requesttopay/` | `{amount, currency, payer_msisdn, payer_message?, payee_note?, callback_url?}` |
| GET | `/momo/requesttopay/<reference_id>/status/` | `?token=<token>` |
| POST | `/momo/requesttopay/<reference_id>/notify/` | `{message, language?}` |

### Request to Withdraw

| Method | URL | Body |
|--------|-----|------|
| POST | `/momo/requesttowithdraw/` | `{amount, currency, payer_msisdn, version?}` |
| GET | `/momo/requesttowithdraw/<reference_id>/status/` | — |

### Invoices

| Method | URL | Body |
|--------|-----|------|
| POST | `/momo/invoice/` | `{amount, currency, payee_msisdn, validity_seconds?, payer_msisdn?, description?}` |
| GET | `/momo/invoice/<reference_id>/status/` | — |
| DELETE | `/momo/invoice/<reference_id>/cancel/` | — |

### Payments

| Method | URL | Body |
|--------|-----|------|
| POST | `/momo/payment/` | `{amount, currency, customer_reference, service_provider}` |
| GET | `/momo/payment/<reference_id>/status/` | — |

### Pre-Approvals

| Method | URL | Body |
|--------|-----|------|
| POST | `/momo/preapproval/` | `{payer_msisdn, currency, message, validity_seconds?}` |
| GET | `/momo/preapproval/<reference_id>/status/` | — |
| GET | `/momo/preapproval/list/msisdn/256700000000/` | — |
| DELETE | `/momo/preapproval/<preapproval_id>/cancel/` | — |

---

## Example: Charge a customer

```bash
# 1. Get token (or let the API auto-fetch one per request)
curl http://localhost:8000/momo/token/

# 2. Request to Pay
curl -X POST http://localhost:8000/momo/requesttopay/ \
  -H "Content-Type: application/json" \
  -d '{
    "amount": "1000",
    "currency": "UGX",
    "payer_msisdn": "256700000000",
    "payer_message": "Payment for order #42",
    "payee_note": "Order 42"
  }'
# Returns: { "reference_id": "uuid...", "status_code": 202 }

# 3. Poll status
curl http://localhost:8000/momo/requesttopay/<reference_id>/status/
```

---

## Notes

- **Token auto-fetch**: Every endpoint accepts an optional `token` field/param.
  If omitted, the app fetches a fresh token automatically using your config credentials.
- **reference_id**: Always saved — use it to poll status via GET endpoints.
- **Callbacks**: Pass `callback_url` in POST bodies for async push notifications.
- **Production**: Change `BASE_URL` and `TARGET_ENVIRONMENT` in `momo_config.py`.
