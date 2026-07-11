# LinkedIn App Setup (one-time, takes ~5 minutes)

Before `publish.py` can post to Jason's LinkedIn, Jason needs to create a LinkedIn Developer app and grab its Client ID + Client Secret. Only Jason can do this — LinkedIn ties it to his personal profile.

## Step 1 — Create the app

1. Go to **https://developer.linkedin.com/** and sign in with Jason's LinkedIn account.
2. Click **Create app**.
3. Fill out the form:
   - **App name:** "Ricky Bobby" (or anything — users never see it).
   - **LinkedIn Page:** attach it to Locafy's page (or Growth Pro — doesn't matter functionally, it's just metadata).
   - **App logo:** upload any square image.
   - **Legal agreement:** agree.
4. Hit **Create app**.

## Step 2 — Enable the two Products we need

In the new app → **Products** tab → request access to these two (both auto-approve, no review queue):

- **Sign In with LinkedIn using OpenID Connect** — gives us `openid profile` scopes so we can read the member URN.
- **Share on LinkedIn** — gives us `w_member_social` so we can post.

Wait a few seconds for each to flip from "Requested" to "Added".

## Step 3 — Configure the OAuth redirect

**Auth** tab → under **OAuth 2.0 settings** → **Authorized redirect URLs for your app** → **Add redirect URL**:

```
http://localhost:8765/callback
```

Save.

## Step 4 — Copy the Client ID + Secret into .env

Still on the **Auth** tab, under **Application credentials**:

- Copy **Client ID** → paste into `.claude/scripts/.env` as the value of `LINKEDIN_CLIENT_ID`.
- Copy **Client Secret** → paste into `.env` as `LINKEDIN_CLIENT_SECRET`.

The final two lines in `.env` should look like this (with your real values in place of the `xxx`):

```
LINKEDIN_CLIENT_ID=xxxxxxxxxxxxxxxx
LINKEDIN_CLIENT_SECRET=xxxxxxxxxxxxxxxx
```

## Step 5 — Authenticate

```bash
cd .claude/scripts
uv run python setup_auth.py --linkedin
```

A browser will open, LinkedIn will show the consent screen listing `openid`, `profile`, and `w_member_social`. Approve. The tab will say "You can close this tab." The token is saved at `.claude/scripts/integrations/linkedin_token.json`.

## Troubleshooting

- **"Redirect URI mismatch"** — double-check the redirect URL in the app matches `http://localhost:8765/callback` exactly (no trailing slash, http not https).
- **"Invalid client"** — the Client ID or Secret got a typo. Re-copy from the dashboard.
- **Token expires** — LinkedIn access tokens last ~60 days. Re-run `setup_auth.py --linkedin` when it lapses.
