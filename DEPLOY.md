# Going live (July 9)

The repo is **private for now** to keep it away from competitors. The app is already built and
verified to work when served from a GitHub Pages subpath. When ready to publish the live demo,
run these three steps:

```bash
# 1) make the repo public
gh repo edit jaiw1/drishti-msme-early-warning --visibility public --accept-visibility-change-consequences

# 2) turn on GitHub Pages with Actions as the build source
gh api -X POST repos/jaiw1/drishti-msme-early-warning/pages -f build_type=workflow \
  || gh api -X PUT repos/jaiw1/drishti-msme-early-warning/pages -f build_type=workflow

# 3) run the deploy workflow (builds app/ and publishes)
gh workflow run "Deploy to GitHub Pages"
```

**Live URL:** `https://jaiw1.github.io/drishti-msme-early-warning/`

Deep links for the pitch/demo:
- Watch-list (default): `/`
- Portfolio risk: `/?view=risk`
- Model & Metrics: `/?view=analytics`
- Real-data model: `/?view=real`
- A specific account: `/?account=MSME00242`

> The Vite `base` is `'./'`, so the app works at the `/drishti-msme-early-warning/` subpath —
> verified locally by serving `app/dist` from that path. No config change needed at go-live.

## Alternative: Vercel (nicer URL, custom domain)
If you'd rather host on Vercel: import the repo, set **root directory = `app`**, framework
**Vite**, build `npm run build`, output `dist`. Vercel serves at the domain root, which also works
with `base:'./'`. (Requires a Vercel login.)
