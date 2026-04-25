# PayPal Setup Guide

This project now supports a real PayPal-backed website checkout flow for cart orders. The backend creates the PayPal order, redirects the buyer to PayPal, captures the payment on the return route, verifies real PayPal webhooks, and then delivers the purchased systems automatically.

This guide covers:

- how to create the PayPal developer app
- how to get the client ID and client secret
- how to create and register the webhook
- which environment variables to set
- which system fields must be configured in the admin panel
- how to test in sandbox before going live

## What The Code Uses

The website checkout flow now uses these routes and settings:

- checkout page: `/checkout`
- PayPal return URL: `/checkout/paypal/return`
- PayPal cancel URL: `/checkout/paypal/cancel`
- real PayPal webhook: `/webhooks/paypal`
- legacy simulation webhook: `/webhooks/paypal/simulate`

The per-system `paypal_link` field is now considered legacy and optional. The real website checkout uses:

- `website_price`
- `website_currency`
- `is_visible_on_website`
- `is_for_sale`
- `is_in_stock`

If a system does not have a website price, it cannot go through the new PayPal cart checkout.

## Step 1: Create A PayPal Developer Account

1. Go to https://developer.paypal.com/
2. Sign in with your PayPal account.
3. Open `Dashboard`.
4. Make sure you can access both `Sandbox` and `Live` sections.

Use `Sandbox` first. Do not start with live credentials.

## Step 2: Create The PayPal App

1. In the PayPal developer dashboard, open `Apps & Credentials`.
2. In `Sandbox`, click `Create App`.
3. Give it a name like `Magic Studios Checkout`.
4. Choose your sandbox business account.
5. Save the app.

After saving, PayPal will show:

- `Client ID`
- `Secret`

These map to:

- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`

When you are ready for production, repeat the same process in the `Live` section and replace the sandbox credentials with live ones.

## Step 3: Create The Webhook

1. Still in the same PayPal app, find the `Webhooks` section.
2. Click `Add Webhook`.
3. Set the URL to:

   `https://your-domain.example/webhooks/paypal`

4. Subscribe at least to these events:

- `CHECKOUT.ORDER.APPROVED`
- `PAYMENT.CAPTURE.COMPLETED`

Recommended extra events because the code can store them too:

- `PAYMENT.CAPTURE.DENIED`
- `PAYMENT.CAPTURE.DECLINED`
- `PAYMENT.CAPTURE.REFUNDED`
- `CHECKOUT.ORDER.VOIDED`

5. Save the webhook.
6. Open the webhook details and copy the `Webhook ID`.

That value maps to:

- `PAYPAL_WEBHOOK_ID`

Important:

- `PUBLIC_BASE_URL` must be the real public HTTPS domain of your site.
- If the URL is wrong, PayPal return and webhook verification will fail.

## Step 4: Fill The Environment Variables

Set these environment variables in your local `.env` and in Render:

- `PUBLIC_BASE_URL=https://your-domain.example`
- `PAYPAL_CLIENT_ID=...`
- `PAYPAL_CLIENT_SECRET=...`
- `PAYPAL_ENV=sandbox`
- `PAYPAL_WEBHOOK_ID=...`

Optional legacy variable:

- `PAYPAL_WEBHOOK_TOKEN=...`

That last one is only for the old simulation route `/webhooks/paypal/simulate`. It is not the real PayPal webhook secret.

## Step 5: Configure Systems In The Admin Panel

For the new website checkout, each sellable system should have:

1. `מחיר באתר / לקופת PayPal`
2. `מטבע`
3. `להציג את המערכת באתר`
4. `להציג את המערכת למכירה`
5. `המערכת במלאי`

The legacy field `קישור פייפאל ישיר (ישן, אופציונלי)` is not required for the real website checkout.

Use it only if you still want the old direct-link flow elsewhere.

## Step 6: Test In Sandbox

1. Set `PAYPAL_ENV=sandbox`.
2. Start the bot and website.
3. In the admin website, edit a system and set:

- a `website_price`
- a `website_currency`
- sale/visibility/in-stock flags enabled

4. Log in to the public website.
5. Add one or more systems to the cart.
6. Go to `/checkout`.
7. Choose `PayPal`.
8. Submit the checkout.
9. Approve the payment in the sandbox buyer flow.
10. Let PayPal redirect back to `/checkout/paypal/return`.

Expected result:

- the local checkout order stores PayPal order state
- the payment is captured by the backend
- systems are delivered automatically
- the order becomes `completed`
- the user gets a notification
- admins can see PayPal status in `/admin/checkouts`

## Step 7: Go Live

When sandbox works:

1. Create a live PayPal app.
2. Create a live webhook with the same production URL.
3. Replace:

- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_WEBHOOK_ID`
- `PAYPAL_ENV=live`

4. Restart the service.

## Troubleshooting

If PayPal option does not appear in checkout:

- check `PAYPAL_CLIENT_ID`
- check `PAYPAL_CLIENT_SECRET`
- restart the service after updating env vars

If PayPal returns but the payment is not captured:

- check `PUBLIC_BASE_URL`
- check the return route is reachable at `/checkout/paypal/return`
- check server logs for PayPal API errors

If the real webhook fails:

- confirm the webhook URL is `/webhooks/paypal`
- confirm `PAYPAL_WEBHOOK_ID` matches the webhook created inside the same PayPal app
- confirm webhook events are subscribed in PayPal

If a system does not appear usable in website checkout:

- make sure `website_price` is set
- make sure `is_visible_on_website` is enabled
- make sure `is_for_sale` is enabled
- make sure `is_in_stock` is enabled
- make sure it is not hidden behind a special-system-only flow unless that is intentional
