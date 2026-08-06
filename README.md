# Youtube-Automation-V1

## Paid Desktop App

This repo now has two customer-facing surfaces:

- `payment_website/`: Vite React site for signup, login, Razorpay checkout, verification, and access status.
- `desktop_app/`: Electron React app that checks paid entitlement before opening the studio.

Local development:

```bash
docker compose up --build backend worker payment_website
cd desktop_app
npm install
npm start
```

Payment website: `http://localhost:3001`

Backend API: `http://localhost:8084/api`

Required Razorpay values live in `.env`: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `PAYMENT_MONTHLY_PLAN_ID`, and `PAYMENT_YEARLY_PLAN_ID`. Lifetime checkout uses `PAYMENT_LIFETIME_AMOUNT_PAISE`; subscription display prices use the monthly/yearly amount env vars.

For local webhook testing, expose the backend with a tunnel and point Razorpay to:

```text
https://your-tunnel.example/api/billing/webhook
```

Successful checkout verification grants local access immediately; webhooks keep subscription state in sync afterward.
