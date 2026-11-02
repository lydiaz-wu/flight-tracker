# Flight Tracker · GitHub Pages (local planner)

## Deployment

1. Push the updated project to the `main` branch of `lydiaz-wu/flight-tracker`.
2. Repository **Settings → Pages → Build and deployment → Source → GitHub Actions** (replace `Deploy from a branch`).
3. Under **Actions** confirm the workflow **Deploy static Flight Tracker to GitHub Pages** passes.
4. Visit https://lydiaz-wu.github.io/flight-tracker/ . You may need a hard refresh if the old service worker was cached.

No Python hosting or secrets are needed **for this static planner**. GitHub Pages builds and publishes the `web/` directory directly using `.github/workflows/pages.yml`.

## Important limits (not implemented in this edition)

- Saved plans live in localStorage **on this device/browser only**; clearing website data removes them. Use **Export backup** before clearing data, and **Import backup** on another device.
- There are **no accounts, friend synchronization, flight fare fetching, price histories or Web Push notifications** in the Pages-only edition. These require separately hosted secure services, scheduled scraper and a push sender. The existing Python backend code remains in the repo as a starting point but GitHub Pages does not run it.
- The airline codes are selection preferences, not a guarantee that real fares can be collected for all airlines.
- For installation on iPhone: Safari → Share → Add to Home Screen. The edition does **not** request notification permission.

## Local smoke test

```sh
cd web
python3 -m http.server 8000
# open http://localhost:8000/
```
