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
- `/addsystem`
- `/editsystem`
- `/systemslist`
- `/removesystem`
- `/sendsystem`
- `/blacklist`
- `/removeblacklist`
- `/requestblacklistremove`
- `/buywithpaypal`
- `/buywithrobux`
- `/getsystem`
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
- `/checkroblox`
- `/poll`
- `/editpoll`
- `/giveaway`
- `/editgiveaway`
- `/trainbot`
- `/endtraining`

## Feature Overview

- Admins are stored in SQLite, with the configured owner always treated as a permanent admin.
- Systems store metadata plus uploaded files on disk under `data/systems/`.
- Systems can optionally store a Roblox gamepass ID or full link for Robux purchases.
- System deliveries go through DMs, send embeds plus attached files, and are logged so blacklist and revoke actions can delete prior bot-sent system messages.
- Blacklist appeals use a modal and a persistent owner-DM button view that survives bot restarts.
- PayPal purchases create a pending purchase record and are completed by a webhook simulation endpoint that triggers automatic delivery.
- Ownership is tracked in `user_systems` and can be granted, checked, or revoked.
- Admins can save transferable ownership snapshots, transfer supported systems between Discord users without duplication, and permanently block old Roblox reclaims after transfer.
- Vouches use a preview flow with edit support and publish to the configured vouch channel.
- Admins can revoke individual vouches from a dropdown list and remove the posted vouch message from the configured channel.
- Roblox OAuth uses an aiohttp callback server and stores linked Roblox profile data per Discord user.
- After Roblox linking succeeds, the bot can sync the member nickname to `username (display name)` and assign the configured Roblox verified role in the primary guild.
- Admins can inspect another member's linked Roblox account with `/checkroblox`, including live Roblox profile data and the systems owned by that Discord user.
- `/getsystem` checks the linked Roblox account against the configured system gamepass using Roblox inventory ownership before delivering the system.
- A persistent role-claim panel lets users self-assign the configured systems role when they qualify via admin-granted systems or matching Roblox gamepasses.
- Incoming user DMs are forwarded to the configured owner for visibility.
- The custom-order flow posts a button panel, collects a modal request, previews it to the user, and sends it to the owner DM with accept or reject buttons.
- Admin-only web panels can create and edit reaction-based polls with custom emoji options, channel selection, stored IDs, and automatic close/result updates.
- Admin-only web panels can create and edit giveaways with durations, winner counts, requirement text, stored IDs, and automatic winner selection when the timer expires.
- Systems can be edited through an admin dropdown plus web editor, including metadata, file replacement, image replacement, PayPal link, and Roblox gamepass updates.
- The AI assistant answers in the configured support channel, can use a separate configured training channel for `/trainbot`, prioritizes admin-trained local knowledge entries over built-in docs, can read screenshots, public links, and text files, can silently learn useful support-channel context outside `/trainbot`, and if no training channel is configured it falls back to the support channel.

## Database Schema

SQLite schema lives in `sales_bot/sql/schema.sql` and creates these primary tables:

- `admins`
- `systems`
- `user_systems`
- `delivery_messages`
- `blacklist_entries`
- `blacklist_appeals`
- `paypal_purchases`
- `vouches`
- `temp_saved_systems`
- `transfer_locks`
- `oauth_states`
- `roblox_links`
- `admin_panel_sessions`
- `polls`
- `giveaways`
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
- `PAYPAL_WEBHOOK_TOKEN`

Optional values:

- `PRIMARY_GUILD_ID`
- `ROBLOX_CLIENT_ID`
- `ROBLOX_CLIENT_SECRET`
- `ROBLOX_REDIRECT_URI`
- `ROBLOX_ENTRY_LINK`
- `ROBLOX_PRIVACY_POLICY_URL`
- `ROBLOX_TERMS_URL`
- `ROBLOX_VERIFIED_ROLE_ID`
- `AI_SUPPORT_CHANNEL_ID`
- `AI_TRAINING_CHANNEL_ID`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `PUBLIC_BASE_URL`
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

If `AI_TRAINING_CHANNEL_ID` is omitted, `/trainbot` keeps using `AI_SUPPORT_CHANNEL_ID` as the training location.

## Render

Render Web Service settings:

- Build command: `pip install -r requirements.txt`
- Start command: `python main.py`

The app now falls back to Render's `PORT` environment variable automatically, so `WEB_PORT=$PORT` is no longer required in the start command.

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

## Validation Performed

- Installed runtime dependencies into the workspace virtual environment.
- Compiled all Python files successfully with `compileall`.
- Imported the core bot, cog, service, UI, and web modules successfully.
