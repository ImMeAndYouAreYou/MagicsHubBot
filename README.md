# Roblox Systems Sales Discord Bot

Production-ready Discord bot built with Python and discord.py 2.x using slash commands only. The bot manages admin users, sellable systems, blacklist appeals, PayPal purchase fulfillment, ownership tracking, vouches, Roblox OAuth linking, and DM-based delivery workflows.

## Important Note About Credentials

This project is wired for environment variables only. Sensitive credentials are not written into source files. Create a local `.env` file from `.env.example` and keep it out of version control.

## Project Structure

```text
.
|-- .env.example
|-- .gitignore
|-- .vscode/
|   `-- launch.json
|-- main.py
|-- README.md
|-- requirements.txt
`-- sales_bot/
    |-- __init__.py
    |-- bot.py
    |-- checks.py
    |-- config.py
    |-- db.py
    |-- exceptions.py
    |-- logging_config.py
    |-- models.py
    |-- storage.py
    |-- web.py
    |-- cogs/
    |   |-- __init__.py
    |   |-- admin.py
    |   |-- blacklist.py
    |   |-- oauth.py
    |   |-- ownership.py
    |   |-- payments.py
    |   |-- support.py
    |   |-- systems.py
    |   `-- vouches.py
    |-- services/
    |   |-- __init__.py
    |   |-- admins.py
    |   |-- blacklist.py
    |   |-- delivery.py
    |   |-- oauth.py
    |   |-- ownership.py
    |   |-- payments.py
    |   |-- systems.py
    |   `-- vouches.py
    |-- sql/
    |   `-- schema.sql
    `-- ui/
        |-- __init__.py
        |-- appeals.py
        |-- common.py
        `-- vouches.py
```

## Slash Commands

Discord slash command names must be lowercase, so the bot exposes these command names:

- `/addadmin`
- `/removeadmin`
- `/adminsite`
- `/discount`
- `/removediscount`
- `/editdiscount`
- `/discountcalculator`
- `/calculatetax`
- `/addsystem`
- `/editsystem`
- `/systemslist`
- `/removesystem`
- `/sendsystem`
- `/sendspecialsystem`
- `/blacklist`
- `/removeblacklist`
- `/requestblacklistremove`
- `/buywithpaypal`
- `/buywithrobux`
- `/sendorderpanel`
- `/checksystems`
- `/revokesystem`
- `/givesystem`
- `/tempsave`
- `/transfer`
- `/claimrolepanel`
- `/vouch`
- `/vouches`
- `/revokevouch`
- `/link`
- `/linkasowner`
- `/ownergamepasses`
- `/creategamepass`
- `/configuregamepass`
- `/connectgamepass`
- `/sendgamepass`
- `/checkroblox`
- `/poll`
- `/editpoll`
- `/giveaway`
- `/editgiveaway`
- `/createevent`
- `/editevent`
- `/rollrandomuser`
- `/rerolluser`
- `/trainbot`
- `/endtraining`

## Feature Overview

- Admins are stored in SQLite, with the configured owner always treated as a permanent admin.
- Systems store metadata plus uploaded files on disk under `data/systems/`.
- Systems also persist uploaded asset bytes in the database so deliveries can still work after Render deploys or other ephemeral filesystem resets.
- Systems can optionally store a Roblox gamepass ID or full link for Robux purchases.
- System deliveries go through DMs, send embeds plus attached files, and are logged so blacklist and revoke actions can delete prior bot-sent system messages.
- Blacklist appeals use a modal and a persistent owner-DM button view that survives bot restarts.
- Legacy direct PayPal purchases still exist for per-system links, and the website checkout can now create real PayPal orders, capture them on return, verify webhooks, and deliver systems automatically when PayPal is configured.
- The website now includes a multi-system cart, manual card checkout, real PayPal cart checkout, redeemable discount codes, and a user inbox for site notifications and order updates.
- Ownership is tracked in `user_systems` and can be granted, checked, or revoked.
- Admins can save transferable ownership snapshots, transfer supported systems between Discord users without duplication, and permanently block old Roblox reclaims after transfer.
- Vouches use a preview flow with edit support and publish to the configured vouch channel.
- Admins can revoke individual vouches from a dropdown list and remove the posted vouch message from the configured channel.
- Roblox OAuth uses an aiohttp callback server and stores linked Roblox profile data per Discord user.
- The server owner can separately link Roblox creator access with `/linkasowner`, then list, create, update, connect, and publish Roblox game passes for the configured universe.
- Admins can open a Discord-authenticated website with `/adminsite` and manage admins, systems, ownership grants/removals by Discord user ID, special-system publishing, and existing poll/giveaway editors from one place.
- Admins can store per-user per-system discount percentages with `/discount`, `/editdiscount`, and `/removediscount`, while `/discountcalculator` and `/calculatetax` post Roblox pricing math publicly in-channel.
- `/sendspecialsystem` opens the website's special-system composer with a prefilled title so a staff member can publish a custom Hebrew sales page and Discord message.
- Special-system listings support multiple uploaded images, per-method pricing for PayPal / Bit / Robux / 2014 users / JailBreak items, and a public Hebrew web order form behind Discord website login.
- New special-order requests are sent to the configured owner in DM, stored in an admin-only website queue, and can be accepted or rejected from the site with a DM response back to the buyer.
- Published special systems can now be edited, republished, activated again, or deactivated from the admin website without changing their public slug.
- Store admins can create reusable discount codes, review queued website checkout orders, and send inbox notifications to any Discord user by ID.
- After Roblox linking succeeds, the bot can sync the member nickname to `username (display name)` and assign the configured Roblox verified role in the primary guild.
- Admins can inspect another member's linked Roblox account with `/checkroblox`, including live Roblox profile data and the systems owned by that Discord user.
- `/getsystem` checks the linked Roblox account against the configured system gamepass using Roblox inventory ownership before delivering the system.
- A Roblox game pass webhook endpoint can auto-grant a linked user's system as soon as your Roblox experience reports the purchase.
- A persistent role-claim panel lets users self-assign the configured systems role when they qualify via admin-granted systems or matching Roblox gamepasses.
- Incoming user DMs are forwarded to the configured owner for visibility.
- The custom-order flow posts a button panel, collects a modal request, previews it to the user, and sends it to the owner DM with accept or reject buttons.
- Admin-only web panels can create and edit reaction-based polls with custom emoji options, channel selection, stored IDs, and automatic close/result updates.
- Admin-only web panels can create and edit giveaways with durations, winner counts, requirement text, stored IDs, and automatic winner selection when the timer expires.
- Admin-only web panels can create and edit events with reward text, star-reaction entry, stored IDs, and manual `/rollrandomuser` or `/rerolluser` winner control.
- Systems can be edited through an admin dropdown plus web editor, including metadata, file replacement, image replacement, PayPal link, and Roblox gamepass updates.
- The AI assistant answers in the configured support channel, can use a separate configured training channel for `/trainbot`, prioritizes admin-trained local knowledge entries over built-in docs, reads slash-command definitions plus workflow knowledge derived from the bot code and services, can read screenshots, public links, and text files, can silently learn useful support-channel context outside `/trainbot`, and if no training channel is configured it falls back to the support channel.

For PayPal environment setup and webhook instructions, see `docs/paypal-setup.md`.

## Database Schema

SQLite schema lives in `sales_bot/sql/schema.sql` and creates these primary tables:

- `admins`
- `systems`
- `user_systems`
- `system_discounts`
- `delivery_messages`
- `blacklist_entries`
- `blacklist_appeals`
- `paypal_purchases`
- `website_cart_items`
- `website_checkout_orders`
- `website_checkout_order_items`
- `discount_codes`
- `discount_code_redemptions`
- `website_notifications`
- `vouches`
- `temp_saved_systems`
- `transfer_locks`
- `oauth_states`
- `roblox_links`
- `web_oauth_states`
- `web_sessions`
- `admin_panel_sessions`
- `special_systems`
- `special_system_images`
- `special_order_requests`
- `polls`
- `giveaways`
- `events`
- `ai_knowledge_entries`
- `ai_training_state`

The database file path defaults to `data/bot.sqlite3` and is configurable through `SQLITE_PATH`.

## Environment Variables

Copy `.env.example` to `.env` and fill in your real values.

Required values:

- `DISCORD_TOKEN`
- `DISCORD_CLIENT_ID`
- `DISCORD_CLIENT_SECRET`
- `OWNER_USER_ID`
- `VOUCH_CHANNEL_ID`

Optional values:

- `PRIMARY_GUILD_ID`
- `ROBLOX_CLIENT_ID`
- `ROBLOX_CLIENT_SECRET`
- `ROBLOX_REDIRECT_URI`
- `ROBLOX_ENTRY_LINK`
- `ROBLOX_PRIVACY_POLICY_URL`
- `ROBLOX_TERMS_URL`
- `ROBLOX_OWNER_CLIENT_ID`
- `ROBLOX_OWNER_CLIENT_SECRET`
- `ROBLOX_OWNER_REDIRECT_URI`
- `ROBLOX_OWNER_UNIVERSE_ID`
- `ROBLOX_GAMEPASS_WEBHOOK_TOKEN`
- `ROBLOX_VERIFIED_ROLE_ID`
- `AI_SUPPORT_CHANNEL_ID`
- `AI_TRAINING_CHANNEL_ID`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `PUBLIC_BASE_URL`
- `PAYPAL_CLIENT_ID`
- `PAYPAL_CLIENT_SECRET`
- `PAYPAL_ENV`
- `PAYPAL_WEBHOOK_ID`
- `PAYPAL_WEBHOOK_TOKEN`
- `WEB_HOST`
- `WEB_PORT`
- `PORT`
- `SQLITE_PATH`
- `LOG_LEVEL`
- `SYNC_COMMANDS_ON_STARTUP`
- `DEV_GUILD_ID`
- `ADMIN_PANEL_SESSION_MINUTES`
- `SELF_PING_ENABLED`
- `SELF_PING_INTERVAL_SECONDS`

If the Roblox OAuth variables are omitted, the bot still starts normally and the `/link` flow stays unavailable until those values are configured.

If the Roblox owner OAuth variables are omitted, the bot still starts normally and the owner-only game pass commands stay unavailable until those values are configured.

If `AI_TRAINING_CHANNEL_ID` is omitted, `/trainbot` keeps using `AI_SUPPORT_CHANNEL_ID` as the training location.

If `PAYPAL_CLIENT_ID` and `PAYPAL_CLIENT_SECRET` are omitted, the website PayPal checkout stays disabled and the cart falls back to manual handling.

If you enable the real website PayPal checkout, also set `PAYPAL_WEBHOOK_ID` and make sure the PayPal webhook points to `/webhooks/paypal` on your public domain.

## Render

Render Web Service settings:

- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`

The app now falls back to Render's `PORT` environment variable automatically, so `WEB_PORT=$PORT` is no longer required in the start command.

If you run with Postgres on Render, newly added or updated systems now keep a database-backed copy of their files. That protects DM deliveries after a deploy even if the temporary filesystem is wiped.

If you want the server owner to manage Roblox game passes from Discord on Render, also set these environment variables there:

- `PUBLIC_BASE_URL=https://<your-render-domain>`
- `ROBLOX_OWNER_CLIENT_ID=<your Roblox owner OAuth client id>`
- `ROBLOX_OWNER_CLIENT_SECRET=<your Roblox owner OAuth client secret>`
- `ROBLOX_OWNER_REDIRECT_URI=https://<your-render-domain>/oauth/roblox/owner/callback`
- `ROBLOX_OWNER_UNIVERSE_ID=<your Roblox universe id>`
- `ROBLOX_GAMEPASS_WEBHOOK_TOKEN=<a long random secret used by your Roblox game webhook>`

If you want the real website PayPal checkout on Render, also set:

- `PUBLIC_BASE_URL=https://<your-render-domain>`
- `PAYPAL_CLIENT_ID=<your PayPal app client id>`
- `PAYPAL_CLIENT_SECRET=<your PayPal app secret>`
- `PAYPAL_ENV=sandbox` or `PAYPAL_ENV=live`
- `PAYPAL_WEBHOOK_ID=<your PayPal webhook id>`

The full setup walkthrough is in `docs/paypal-setup.md`.

The bot also supports a background self-ping loop using `PUBLIC_BASE_URL`. By default it pings `/health` every 180 seconds. You can control that with:

- `SELF_PING_ENABLED=true|false`
- `SELF_PING_INTERVAL_SECONDS=180`

## Running In Visual Studio Code

1. Open the project folder.
2. Create `.env` from `.env.example` and fill in real credentials and URLs.
3. Create or select a Python virtual environment.
4. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Start the bot:

   ```powershell
   python main.py
   ```

6. Or use the included debug profile: `Run Discord Sales Bot` in the Run and Debug panel.

## Running In Visual Studio

1. Open the folder as a Python project.
2. Set the startup file to `main.py`.
3. Create a local `.env` file from `.env.example`.
4. Install dependencies into the selected interpreter with `pip install -r requirements.txt`.
5. Run or debug the project.

## PayPal Webhook Simulation

After `/buywithpaypal` creates a pending purchase, complete it by sending a POST request to the webhook endpoint.

PowerShell example:

```powershell
Invoke-RestMethod \
  -Uri "http://localhost:8080/webhooks/paypal/simulate" \
  -Method Post \
  -Headers @{ "X-Webhook-Token" = "your-paypal-webhook-token" } \
  -ContentType "application/json" \
  -Body '{"purchase_id":1,"status":"COMPLETED"}'
```

Once the webhook is accepted, the purchased system is delivered automatically by DM.

## Roblox Game Pass Webhook

After you connect the server owner with `/linkasowner`, connect a Roblox game pass to a system with `/connectgamepass`, and send the buy button with `/sendgamepass`, your Roblox experience can notify the bot when the purchase happens.

Roblox does not send this webhook for you automatically. You need a server script inside the Roblox experience that calls the endpoint. A sample script is included in `GamePassWebhook.server.lua` in this repo.

Endpoint:

- `POST /webhooks/roblox/gamepass`
- Header: `X-Roblox-Webhook-Token: <ROBLOX_GAMEPASS_WEBHOOK_TOKEN>`

Example JSON payload:

```json
{
  "roblox_user_id": 123456789,
  "gamepass_id": 987654321
}
```

The sample server script does two things:

- It sends the webhook immediately after an in-game `PromptGamePassPurchaseFinished` purchase.
- It also re-checks configured game pass ownership for online players so purchases made from a Discord or website link can still be detected while the player is in the experience or when they join later.

Before using it, make sure `HttpService` is enabled in your Roblox experience settings and replace the placeholder values at the top of the Lua file.

If the buyer already linked their Roblox account in Discord with `/link`, the bot grants the linked system automatically. If the buyer has not linked yet, the endpoint returns an accepted-but-unlinked response, and the user can still link later and use `/getsystem` to claim the system from their owned game pass.

## Validation Performed

- Installed runtime dependencies into the workspace virtual environment.
- Compiled all Python files successfully with `compileall`.
- Imported the core bot, cog, service, UI, and web modules successfully.
