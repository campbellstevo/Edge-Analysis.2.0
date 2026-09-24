# Deploying Edge Analysis off Streamlit Community Cloud

The repo is host-ready: `Dockerfile` + `render.yaml`. On Render (recommended, ~US$7/mo):

1. render.com → New → Blueprint → connect this GitHub repo. Render reads `render.yaml`.
2. It will prompt for every secret marked `sync: false` — paste the same values as
   Streamlit Cloud's secrets. `EA_STORE_PATH` is preset to the persistent disk, so
   user registrations survive deploys without the Notion mirror.
3. Update the two OAuth redirect URIs (Notion + WHOOP) to the new domain, in both
   the provider dashboards and the corresponding secrets.
4. Custom domain: Render → Settings → Custom Domains, add a CNAME.

App secrets are read via Streamlit secrets *or* environment variables — Render env
vars just work. Keep Streamlit Cloud running until the new URL is verified.

## Who can sign in — the access switch

Set these in Streamlit Cloud → the app → Settings → Secrets (or as Render env vars).
They are read on every run, so a change takes effect on the visitor's next click.

```toml
EA_OWNER  = "you@example.com"        # your Notion sign-in email (or Notion user id)
EA_ACCESS = "owner"                  # owner | allowlist | open | paused
EA_ALLOW  = "a@example.com, b@example.com"   # used when EA_ACCESS = "allowlist"
```

- **Unset or misspelt `EA_ACCESS` means owner-only**, never open.
- `paused` is the kill switch: everyone but the owner sees a paused page; the demo keeps working.
- With no `EA_OWNER` (and no `WHOOP_OWNER` to fall back on) nobody is admitted, so set it **before** pushing a build that has the switch.
- A refused visitor keeps no session and gets no user record.

Checks: `python -m pip install -r requirements-dev.txt` then `python -m pytest tests -q`.
