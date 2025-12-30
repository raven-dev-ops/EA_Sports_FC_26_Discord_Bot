# Billing (Stripe)

This project uses Stripe Subscriptions for the `Pro` plan.

## Required environment variables

- `STRIPE_SECRET_KEY` (server-side Stripe API key)
- `STRIPE_WEBHOOK_SECRET` (from the webhook endpoint configuration)
- `STRIPE_PRICE_PRO_ID` (Stripe Price ID for the `Pro` subscription)

See `.env.example` for the full list.

## Stripe setup (Dashboard)

1. Create a Product (example: `Offside Pro`).
2. Create a recurring Price for that product (monthly, or yearly — pick one to start).
3. Copy the Price ID into `STRIPE_PRICE_PRO_ID`.

## Webhook setup

The web process exposes a Stripe webhook endpoint:

- `POST /api/billing/webhook`

In Stripe:

1. Add a webhook endpoint pointing to: `https://<YOUR_DOMAIN>/api/billing/webhook`
2. Subscribe to events:
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `invoice.payment_failed`
3. Copy the signing secret into `STRIPE_WEBHOOK_SECRET`.

## Stripe Billing Portal

The dashboard includes a self-serve “Manage subscription” button (Stripe Billing Portal).

In Stripe:

1. Enable **Billing Portal** (Settings → Billing → Customer portal).
2. Configure allowed actions (payment method updates, cancellations, etc.) as desired.

## Notes

- The billing UI and webhook processing require MongoDB (`MONGODB_URI`) so subscriptions can be stored per guild.
- On platforms like Heroku, ensure `STRIPE_*` variables are set in config vars (not committed to git).
