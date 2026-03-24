# BME Bioimaging Daily Digest

Personal daily intelligence feed for UNC Chapel Hill BME — bioimaging track.
Auto-scrapes papers, news, and clinical trials filtered to your research interests.

**Live dashboard:** `https://YOUR-USERNAME.github.io/bme-digest/`

---

## What it does

Runs every morning at 6am UTC via GitHub Actions and pushes a fresh HTML
dashboard to GitHub Pages. You open the URL, everything is already there.

### Sources (7 total)

| Source | What you get |
|--------|-------------|
| **arXiv** (cs.CV, eess.IV, physics.med-ph) | Preprints, usually 1-2 days after posting |
| **PubMed** | Published abstracts, peer-reviewed |
| **Semantic Scholar** | Papers with citation counts |
| **OpenAlex** | Broader academic papers, open access |
| **9 RSS feeds** | ITN, IEEE Spectrum, BioPharmaDive, STAT News, MedTech Dive, Radiology Business, Health Imaging, AuntMinnie, MedCity News |
| **3 direct scrapes** | ITN (BS4), MedGadget, AuntMinnie |
| **ClinicalTrials.gov** | Active surgical/imaging AI trials |

---

## Setup (10 minutes)

### Step 1 — Create the repo

```bash
# Create a new GitHub repo named: bme-digest
# Then clone it locally
git clone https://github.com/YOUR-USERNAME/bme-digest.git
cd bme-digest
```

### Step 2 — Add the files

Copy these files into your repo:
```
bme-digest/
├── .github/
│   └── workflows/
│       └── daily_digest.yml   ← GitHub Actions schedule
├── scripts/
│   └── scraper.py             ← main scraper
├── requirements.txt
└── README.md
```

### Step 3 — Enable GitHub Pages

1. Go to your repo → **Settings → Pages**
2. Set source to **"Deploy from a branch"**
3. Branch: **`gh-pages`**, folder: **`/ (root)`**
4. Click Save

### Step 4 — Run it once to test

```bash
# Install deps locally
pip install -r requirements.txt

# Run the scraper
python scripts/scraper.py

# Open docs/index.html in your browser to preview
open docs/index.html   # Mac
```

### Step 5 — Push and let GitHub Actions take over

```bash
git add .
git commit -m "initial setup"
git push
```

GitHub Actions will run automatically at 6am UTC daily.
You can also trigger it manually: **Actions tab → Daily BME Digest → Run workflow**

Your live URL will be:
```
https://YOUR-USERNAME.github.io/bme-digest/
```

---

## Customizing keywords

Open `scripts/scraper.py` and edit the `KEYWORDS` list at the top.
The more specific, the better the signal-to-noise ratio.

```python
KEYWORDS = [
    "magnetic particle imaging",
    "intraoperative AI",
    # add yours here
    "focused ultrasound brain",
    "diffuse optical tomography",
]
```

Push the change — next morning's run picks it up automatically.

---

## Changing the schedule

Edit `.github/workflows/daily_digest.yml`:

```yaml
# Every day at 7am UTC
- cron: '0 7 * * *'

# Twice daily (6am + 6pm UTC)
- cron: '0 6,18 * * *'

# Weekdays only
- cron: '0 6 * * 1-5'
```

Use https://crontab.guru to build expressions.

---

## Upgrading later

When you're ready to go further:

**Smarter relevance filtering** — replace keyword matching with embeddings:
```bash
pip install sentence-transformers
```
Then use `SentenceTransformer("allenai-specter")` (trained on scientific papers)
to compute cosine similarity instead of simple string matching.

**Citation tracking** — track papers citing specific foundational MPI papers:
```python
# Semantic Scholar API — free, no key needed
url = "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/citations"
```

**Obsidian integration** — add a step to `daily_digest.yml` that writes each
paper as a markdown file to a `vault/` folder, then sync that folder to
iCloud/Dropbox where Obsidian reads it.

**Discord/Slack notification** — add a webhook call at the end of `scraper.py`
to ping yourself when the digest is ready.

---

## Why not Vercel / Railway / Render?

- **Vercel** is built for JS frontends. Python cron jobs are awkward there.
- **Railway** has no permanent free tier (credits run out).
- **Render** free tier spins down after 15min of inactivity — bad for cron jobs.
- **GitHub Actions** is free up to 2,000 minutes/month. A daily scrape uses ~15 min/month. It's the right tool for this.

---

*Built for: UNC Chapel Hill · Lampe Joint BME · Class of 2030*