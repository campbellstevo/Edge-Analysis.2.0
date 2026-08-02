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
