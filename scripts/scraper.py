"""
BME Bioimaging Daily Intelligence Scraper
------------------------------------------
Fetches papers, news, and clinical trials relevant to:
  - Magnetic Particle Imaging (MPI)
  - Intraoperative / Surgical AI
  - Ultrasound + Photoacoustic Imaging
  - Explainable AI for Medical Imaging
  - General Bioimaging + BME

Sources:
  arXiv API         → https://export.arxiv.org/api/query
  PubMed API        → https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
  ClinicalTrials    → https://clinicaltrials.gov/api/v2/studies
  OpenAlex API      → https://api.openalex.org/works
  Semantic Scholar  → https://api.semanticscholar.org/graph/v1/paper/search
  RSS (9 feeds)     → See FEEDS dict below
  BS4 scrape (3)    → ITN, AuntMinnie, MedGadget

Output:
  docs/index.html   → GitHub Pages dashboard (auto-refreshes daily)
  docs/data.json    → raw JSON for any downstream use

Usage:
  python scripts/scraper.py
"""

import requests
import feedparser
import json
import time
import re
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict, field
from typing import Optional
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────

KEYWORDS = [
    # Your primary research focus
    "magnetic particle imaging",
    "MPI reconstruction",
    "superparamagnetic nanoparticles imaging",
    # Intraoperative / surgical AI
    "intraoperative imaging",
    "intraoperative AI",
    "real-time surgical navigation",
    "surgical video segmentation",
    "nerve detection surgery",
    "fluorescence-guided surgery",
    "augmented reality surgery",
    # Ultrasound + photoacoustic
    "photoacoustic imaging",
    "photoacoustic tomography",
    "ultrasound deep learning",
    "ultrasound reconstruction",
    "wearable ultrasound",
    # XAI + foundation models
    "explainable AI medical imaging",
    "foundation model medical imaging",
    "XAI radiology",
    # Broader bioimaging
    "bioimaging AI",
    "medical image segmentation",
    "diffuse optical imaging",
    "optical coherence tomography AI",
    "multimodal medical imaging",
]

ARXIV_QUERIES = [
    "magnetic+particle+imaging",
    "intraoperative+imaging+deep+learning",
    "surgical+video+AI+segmentation",
    "photoacoustic+imaging+reconstruction+neural",
    "explainable+AI+medical+imaging",
    "ultrasound+foundation+model",
    "real+time+surgical+navigation+AI",
]

ARXIV_CATS = ["cs.CV", "eess.IV", "physics.med-ph", "q-bio.QM", "cs.LG"]

PUBMED_QUERIES = [
    "magnetic particle imaging reconstruction deep learning",
    "intraoperative AI imaging real-time",
    "real-time surgical navigation artificial intelligence",
    "photoacoustic imaging machine learning",
    "explainable AI medical imaging clinical",
]

CLINICALTRIALS_QUERIES = [
    "intraoperative imaging artificial intelligence",
    "surgical navigation AI",
    "real-time tumor detection surgery",
    "fluorescence guided surgery AI",
]

SEMANTIC_SCHOLAR_QUERIES = [
    "magnetic particle imaging reconstruction",
    "intraoperative AI imaging",
    "surgical video segmentation real-time",
]

OPENALEX_QUERIES = [
    "magnetic particle imaging 2024 2025",
    "intraoperative imaging deep learning 2025",
]

# RSS feeds — all public, no auth required
FEEDS = {
    "Imaging Technology News":
        "https://www.itnonline.com/rss.xml",
    "IEEE Spectrum Biomedical":
        "https://spectrum.ieee.org/feeds/blog/biomedical.rss",
    "BioPharmaDive":
        "https://www.biopharmadive.com/feeds/news/",
    "MedCity News":
        "https://medcitynews.com/feed/",
    "STAT News":
        "https://www.statnews.com/feed/",
    "MedTech Dive":
        "https://www.medtechdive.com/feeds/news/",
    "Radiology Business":
        "https://radiologybusiness.com/feed",
    "Health Imaging":
        "https://www.healthimaging.com/rss.xml",
    "AuntMinnie News":
        "https://www.auntminnie.com/rss/news",
}

# Direct scrape targets (BS4) — public pages, no login
SCRAPE_URLS = {
    "ITN (direct)":
        "https://www.itnonline.com/content/news",
    "MedGadget":
        "https://medgadget.com/",
    "AuntMinnie":
        "https://www.auntminnie.com/index.aspx?sec=nws",
}

LOOKBACK_DAYS = 2
REQUEST_TIMEOUT = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; BME-research-bot/1.0; "
        "educational use; UNC Chapel Hill BME)"
    )
}


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODEL
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Article:
    title:          str
    source:         str
    url:            str
    summary:        str
    date:           str
    relevance_tags: list  = field(default_factory=list)
    category:       str   = "news"   # "paper" | "news" | "trial"
    authors:        list  = field(default_factory=list)
    citations:      int   = 0


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_relevant(text: str) -> list:
    t = text.lower()
    return [kw for kw in KEYWORDS if kw.lower() in t]

def clean(text: str, maxlen: int = 450) -> str:
    text = re.sub(r'\s+', ' ', (text or "")).strip()
    return (text[:maxlen] + "…") if len(text) > maxlen else text

def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def safe_get(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=HEADERS,
                         timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"    [GET failed {url[:60]}… → {e}]")
        return None

def dedupe(articles: list) -> list:
    seen, out = set(), []
    for a in articles:
        key = a.url or a.title
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# SOURCES
# ─────────────────────────────────────────────────────────────────────────────

def fetch_arxiv() -> list:
    print("  [1/7] arXiv …", end=" ", flush=True)
    out = []
    base = "https://export.arxiv.org/api/query"
    cats = "+OR+".join(f"cat:{c}" for c in ARXIV_CATS)

    for term in ARXIV_QUERIES:
        r = safe_get(
            base,
            params={
                "search_query": f"{term}+AND+({cats})",
                "sortBy":       "submittedDate",
                "sortOrder":    "descending",
                "max_results":  8,
            },
        )
        if not r:
            continue
        feed = feedparser.parse(r.text)
        for e in feed.entries:
            text = e.get("title", "") + " " + e.get("summary", "")
            tags = is_relevant(text)
            if tags:
                authors = [a.get("name", "") for a in e.get("authors", [])][:4]
                out.append(Article(
                    title=clean(e.get("title", "Untitled")),
                    source="arXiv",
                    url=e.get("link", ""),
                    summary=clean(e.get("summary", "")),
                    date=e.get("published", today())[:10],
                    relevance_tags=tags,
                    category="paper",
                    authors=authors,
                ))
        time.sleep(0.4)

    result = dedupe(out)
    print(f"{len(result)} papers")
    return result


def fetch_pubmed() -> list:
    print("  [2/7] PubMed …", end=" ", flush=True)
    out = []
    search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    fetch_url  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

    for query in PUBMED_QUERIES:
        r = safe_get(search_url, params={
            "db":       "pubmed",
            "term":     query,
            "retmax":   6,
            "sort":     "pub+date",
            "retmode":  "json",
            "reldate":  str(LOOKBACK_DAYS * 20),
        })
        if not r:
            continue
        ids = r.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            continue

        r2 = safe_get(fetch_url, params={
            "db":      "pubmed",
            "id":      ",".join(ids),
            "retmode": "xml",
            "rettype": "abstract",
        })
        if not r2:
            continue

        soup = BeautifulSoup(r2.text, "lxml-xml")
        for art in soup.find_all("PubmedArticle"):
            title   = (art.find("ArticleTitle")  or {}).get_text("")
            summary = (art.find("AbstractText")  or {}).get_text("")
            pmid    = (art.find("PMID")          or {}).get_text("")
            year_el = art.find("PubDate")
            year    = year_el.get_text()[:4] if year_el else today()[:4]
            authors_els = art.find_all("LastName")
            authors = [a.get_text() for a in authors_els[:4]]

            tags = is_relevant(title + " " + summary)
            if tags:
                out.append(Article(
                    title=clean(title),
                    source="PubMed",
                    url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    summary=clean(summary),
                    date=year,
                    relevance_tags=tags,
                    category="paper",
                    authors=authors,
                ))
        time.sleep(0.35)

    result = dedupe(out)
    print(f"{len(result)} abstracts")
    return result


def fetch_semantic_scholar() -> list:
    print("  [3/7] Semantic Scholar …", end=" ", flush=True)
    out = []
    base = "https://api.semanticscholar.org/graph/v1/paper/search"

    for query in SEMANTIC_SCHOLAR_QUERIES:
        r = safe_get(base, params={
            "query":  query,
            "limit":  6,
            "fields": "title,abstract,authors,year,citationCount,url,externalIds",
        })
        if not r:
            continue
        for p in r.json().get("data", []):
            text = (p.get("title") or "") + " " + (p.get("abstract") or "")
            tags = is_relevant(text)
            if tags:
                doi  = (p.get("externalIds") or {}).get("DOI", "")
                url  = p.get("url") or (f"https://doi.org/{doi}" if doi else "")
                authors = [
                    a.get("name", "") for a in (p.get("authors") or [])[:4]
                ]
                out.append(Article(
                    title=clean(p.get("title", "Untitled")),
                    source="Semantic Scholar",
                    url=url,
                    summary=clean(p.get("abstract", "")),
                    date=str(p.get("year", today()[:4])),
                    relevance_tags=tags,
                    category="paper",
                    authors=authors,
                    citations=p.get("citationCount", 0),
                ))
        time.sleep(0.3)

    result = dedupe(out)
    print(f"{len(result)} papers")
    return result


def fetch_openalex() -> list:
    print("  [4/7] OpenAlex …", end=" ", flush=True)
    out = []
    base = "https://api.openalex.org/works"
    cutoff = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")

    for query in OPENALEX_QUERIES:
        r = safe_get(base, params={
            "search":        query,
            "filter":        f"from_publication_date:{cutoff},type:article",
            "sort":          "cited_by_count:desc",
            "per-page":      5,
            "select":        "title,abstract_inverted_index,doi,publication_date,authorships,cited_by_count,primary_location",
        })
        if not r:
            continue
        for w in r.json().get("results", []):
            title   = w.get("title", "") or ""
            # OpenAlex stores abstract as inverted index — reconstruct it
            inv     = w.get("abstract_inverted_index") or {}
            words   = {}
            for word, positions in inv.items():
                for pos in positions:
                    words[pos] = word
            abstract = " ".join(words[k] for k in sorted(words.keys()))

            tags = is_relevant(title + " " + abstract)
            if tags:
                doi     = w.get("doi", "") or ""
                url     = doi if doi.startswith("http") else f"https://doi.org/{doi}" if doi else ""
                authors = [
                    a.get("author", {}).get("display_name", "")
                    for a in (w.get("authorships") or [])[:4]
                ]
                out.append(Article(
                    title=clean(title),
                    source="OpenAlex",
                    url=url,
                    summary=clean(abstract),
                    date=w.get("publication_date", today())[:10],
                    relevance_tags=tags,
                    category="paper",
                    authors=authors,
                    citations=w.get("cited_by_count", 0),
                ))
        time.sleep(0.3)

    result = dedupe(out)
    print(f"{len(result)} papers")
    return result


def fetch_rss() -> list:
    print("  [5/7] RSS feeds …", end=" ", flush=True)
    out = []
    for source, url in FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for e in feed.entries[:20]:
                text = e.get("title", "") + " " + e.get("summary", "")
                tags = is_relevant(text)
                if tags:
                    pub = e.get("published", today())
                    out.append(Article(
                        title=clean(e.get("title", "Untitled")),
                        source=source,
                        url=e.get("link", ""),
                        summary=clean(BeautifulSoup(
                            e.get("summary", ""), "html.parser"
                        ).get_text()),
                        date=pub[:10] if pub else today(),
                        relevance_tags=tags,
                        category="news",
                    ))
        except Exception as ex:
            print(f"\n    [RSS {source}: {ex}]", end="")

    result = dedupe(out)
    print(f"{len(result)} articles")
    return result


def fetch_bs4_sites() -> list:
    print("  [6/7] Direct scrape (BS4) …", end=" ", flush=True)
    out = []

    # ── ITN ──────────────────────────────────────────────────────────────────
    r = safe_get("https://www.itnonline.com/content/news")
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        for card in soup.select("div.views-row, article, .node--type-article")[:25]:
            t = card.select_one("h3 a, h2 a, .field--name-title a")
            s = card.select_one(".field--name-body, .field-body, p")
            if not t:
                continue
            title   = t.get_text(strip=True)
            href    = t.get("href", "")
            url     = href if href.startswith("http") else "https://www.itnonline.com" + href
            summary = s.get_text(strip=True) if s else ""
            tags    = is_relevant(title + " " + summary)
            if tags:
                out.append(Article(
                    title=clean(title), source="ITN",
                    url=url, summary=clean(summary),
                    date=today(), relevance_tags=tags, category="news",
                ))

    # ── MedGadget ─────────────────────────────────────────────────────────────
    r = safe_get("https://medgadget.com/")
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select("article, .post, h2.entry-title")[:20]:
            t = item.select_one("a, h2")
            s = item.select_one(".entry-summary, p")
            if not t:
                continue
            title   = t.get_text(strip=True)
            href    = t.get("href", "") if t.name == "a" else (t.find("a") or {}).get("href", "")
            url     = href if href.startswith("http") else "https://medgadget.com" + href
            summary = s.get_text(strip=True) if s else ""
            tags    = is_relevant(title + " " + summary)
            if tags:
                out.append(Article(
                    title=clean(title), source="MedGadget",
                    url=url, summary=clean(summary),
                    date=today(), relevance_tags=tags, category="news",
                ))

    # ── AuntMinnie ────────────────────────────────────────────────────────────
    r = safe_get("https://www.auntminnie.com/index.aspx?sec=nws")
    if r:
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".headline, .article-title, h3 a")[:20]:
            title   = item.get_text(strip=True)
            href    = item.get("href", "") if item.name == "a" else ""
            url     = href if href.startswith("http") else "https://www.auntminnie.com" + href
            tags    = is_relevant(title)
            if tags:
                out.append(Article(
                    title=clean(title), source="AuntMinnie",
                    url=url, summary="",
                    date=today(), relevance_tags=tags, category="news",
                ))

    result = dedupe(out)
    print(f"{len(result)} articles")
    return result


def fetch_clinicaltrials() -> list:
    print("  [7/7] ClinicalTrials.gov …", end=" ", flush=True)
    out = []
    base = "https://clinicaltrials.gov/api/v2/studies"

    for query in CLINICALTRIALS_QUERIES:
        r = safe_get(base, params={
            "query.term":          query,
            "filter.overallStatus": "RECRUITING|ACTIVE_NOT_RECRUITING|COMPLETED",
            "pageSize":            6,
            "format":              "json",
        })
        if not r:
            continue
        for study in r.json().get("studies", []):
            ps      = study.get("protocolSection", {})
            id_m    = ps.get("identificationModule", {})
            desc_m  = ps.get("descriptionModule", {})
            stat_m  = ps.get("statusModule", {})
            title   = id_m.get("briefTitle", "Untitled")
            summary = desc_m.get("briefSummary", "")
            nct     = id_m.get("nctId", "")
            date    = stat_m.get("startDateStruct", {}).get("date", today())
            tags    = is_relevant(title + " " + summary) or ["surgical AI"]
            out.append(Article(
                title=clean(title),
                source="ClinicalTrials.gov",
                url=f"https://clinicaltrials.gov/study/{nct}",
                summary=clean(summary),
                date=str(date)[:10],
                relevance_tags=tags,
                category="trial",
            ))
        time.sleep(0.3)

    result = dedupe(out)
    print(f"{len(result)} trials")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# HTML RENDERER
# ─────────────────────────────────────────────────────────────────────────────

def render_html(articles: list) -> str:
    cats = {"paper": [], "news": [], "trial": []}
    for a in articles:
        cats.get(a.category, cats["news"]).append(a)

    total = len(articles)
    generated = datetime.now(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")

    def badge(tag: str) -> str:
        return (
            f'<span style="background:rgba(124,108,252,0.12);color:#9d8ffd;'
            f'padding:2px 7px;border-radius:4px;font-size:10px;'
            f'margin:0 3px 3px 0;display:inline-block;white-space:nowrap">'
            f'{tag}</span>'
        )

    def card(a: Article) -> str:
        color_map = {"paper": "#7c6cfc", "news": "#4fc3a1", "trial": "#f0874a"}
        c = color_map.get(a.category, "#888")
        tags_html  = "".join(badge(t) for t in a.relevance_tags[:4])
        auth_html  = (
            f'<span style="color:#5a5878;font-size:11px">'
            f'{", ".join(a.authors[:3])}{"…" if len(a.authors) > 3 else ""}</span>'
            if a.authors else ""
        )
        cite_html  = (
            f'<span style="color:#f0874a;font-size:11px;margin-left:10px">'
            f'↑ {a.citations} citations</span>'
            if a.citations else ""
        )
        return f"""
        <div class="card" style="border-left:3px solid {c}">
          <a class="card-title" href="{a.url}" target="_blank"
             rel="noopener noreferrer">{a.title}</a>
          <div class="card-meta">
            <span class="source-pill">{a.source}</span>
            <span style="color:#5a5878">{a.date}</span>
            {auth_html}{cite_html}
          </div>
          <div style="margin:6px 0 8px;flex-wrap:wrap;display:flex">{tags_html}</div>
          {f'<p class="card-summary">{a.summary}</p>' if a.summary else ""}
        </div>"""

    def section(cat: str, icon: str, label: str) -> str:
        items = cats[cat]
        if not items:
            return ""
        color  = {"paper": "#7c6cfc", "news": "#4fc3a1", "trial": "#f0874a"}[cat]
        cards  = "\n".join(card(a) for a in items)
        return f"""
        <section class="section">
          <div class="section-header">
            <span style="color:{color};margin-right:8px">{icon}</span>
            <span style="color:{color}">{label}</span>
            <span class="section-count">{len(items)}</span>
            <span class="section-line"></span>
          </div>
          {cards}
        </section>"""

    sections = (
        section("paper", "◈", "New Papers") +
        section("news",  "◉", "News + Industry") +
        section("trial", "◎", "Clinical Trials")
    )

    # keyword stats for sidebar
    kw_counts = {}
    for a in articles:
        for t in a.relevance_tags:
            kw_counts[t] = kw_counts.get(t, 0) + 1
    top_kw = sorted(kw_counts.items(), key=lambda x: -x[1])[:8]
    kw_pills = "".join(
        f'<div class="kw-row"><span class="kw-label">{k}</span>'
        f'<span class="kw-num">{v}</span></div>'
        for k, v in top_kw
    )

    source_counts = {}
    for a in articles:
        source_counts[a.source] = source_counts.get(a.source, 0) + 1
    src_pills = "".join(
        f'<div class="kw-row"><span class="kw-label">{s}</span>'
        f'<span class="kw-num">{n}</span></div>'
        for s, n in sorted(source_counts.items(), key=lambda x: -x[1])[:8]
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>BME Digest — {today()}</title>
<link href="https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,300;0,400;0,500;1,300&display=swap" rel="stylesheet">
<style>
  :root{{
    --bg:#08080f; --s1:#0f0f1a; --s2:#16162a;
    --b1:rgba(255,255,255,0.06); --b2:rgba(255,255,255,0.11);
    --t1:#ddd9f5; --t2:#8883a8; --t3:#4e4b68;
    --p:#7c6cfc; --g:#4fc3a1; --o:#f0874a;
  }}
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:var(--bg);color:var(--t1);font-family:"IBM Plex Sans",sans-serif;
       font-weight:300;min-height:100vh;line-height:1.7}}
  a{{color:inherit;text-decoration:none}}
  /* LAYOUT */
  .shell{{display:grid;grid-template-columns:1fr 260px;gap:0;max-width:1200px;
          margin:0 auto;padding:0 24px 80px;align-items:start}}
  .main{{padding:0 32px 0 0;border-right:1px solid var(--b1)}}
  .sidebar{{padding:32px 0 0 28px;position:sticky;top:24px}}
  /* HEADER */
  .header{{padding:48px 0 36px}}
  .header-kicker{{font-family:"IBM Plex Mono",monospace;font-size:10px;
                  letter-spacing:0.14em;color:var(--p);text-transform:uppercase;
                  margin-bottom:12px;display:flex;align-items:center;gap:8px}}
  .header-kicker::before{{content:"";width:18px;height:1px;background:var(--p)}}
  h1{{font-family:"Syne",sans-serif;font-size:clamp(28px,4vw,44px);font-weight:800;
      letter-spacing:-0.025em;line-height:1.05;margin-bottom:8px}}
  h1 em{{color:var(--p);font-style:normal}}
  .header-sub{{font-size:13px;color:var(--t2)}}
  /* STAT ROW */
  .stats{{display:flex;gap:20px;margin:24px 0 8px;flex-wrap:wrap}}
  .stat{{background:var(--s1);border:1px solid var(--b1);border-radius:10px;
         padding:12px 16px;min-width:100px}}
  .stat-num{{font-family:"Syne",sans-serif;font-size:22px;font-weight:800;
             line-height:1}}
  .stat-label{{font-size:11px;color:var(--t2);margin-top:3px}}
  /* SECTIONS */
  .section{{margin-bottom:36px}}
  .section-header{{display:flex;align-items:center;gap:8px;margin-bottom:16px;
                   font-family:"IBM Plex Mono",monospace;font-size:11px;
                   letter-spacing:0.1em;text-transform:uppercase}}
  .section-count{{background:var(--s2);padding:2px 7px;border-radius:10px;
                  font-size:10px;color:var(--t2)}}
  .section-line{{flex:1;height:1px;background:var(--b1)}}
  /* CARDS */
  .card{{background:var(--s1);border:1px solid var(--b1);border-radius:12px;
         padding:14px 16px;margin-bottom:10px;
         transition:border-color 0.15s,background 0.15s}}
  .card:hover{{border-color:var(--b2);background:var(--s2)}}
  .card-title{{font-family:"Syne",sans-serif;font-size:14px;font-weight:700;
               color:var(--t1);display:block;margin-bottom:6px;line-height:1.35}}
  .card-title:hover{{color:var(--p)}}
  .card-meta{{display:flex;align-items:center;gap:8px;flex-wrap:wrap;
              margin-bottom:6px;font-size:11px;font-family:"IBM Plex Mono",monospace}}
  .source-pill{{background:var(--s2);border:1px solid var(--b1);padding:1px 7px;
                border-radius:4px;font-size:10px;color:var(--t2)}}
  .card-summary{{font-size:12px;color:var(--t2);line-height:1.65;
                 display:-webkit-box;-webkit-line-clamp:3;
                 -webkit-box-orient:vertical;overflow:hidden}}
  /* SIDEBAR */
  .sidebar-block{{margin-bottom:28px}}
  .sidebar-title{{font-family:"IBM Plex Mono",monospace;font-size:10px;
                  letter-spacing:0.12em;text-transform:uppercase;color:var(--t3);
                  margin-bottom:12px}}
  .kw-row{{display:flex;justify-content:space-between;align-items:center;
           padding:5px 0;border-bottom:1px solid var(--b1)}}
  .kw-label{{font-size:12px;color:var(--t2)}}
  .kw-num{{font-family:"IBM Plex Mono",monospace;font-size:11px;color:var(--p)}}
  .refresh-note{{font-size:11px;color:var(--t3);line-height:1.6;margin-top:8px}}
  /* FILTER BAR */
  .filters{{display:flex;gap:8px;margin-bottom:24px;flex-wrap:wrap}}
  .filter-btn{{background:var(--s1);border:1px solid var(--b1);border-radius:6px;
               padding:5px 12px;font-size:12px;color:var(--t2);cursor:pointer;
               font-family:"IBM Plex Sans",sans-serif;transition:all 0.15s}}
  .filter-btn:hover,.filter-btn.active{{background:var(--p);border-color:var(--p);
                                        color:#fff}}
  /* SEARCH */
  .search-wrap{{margin-bottom:20px}}
  #search{{width:100%;background:var(--s1);border:1px solid var(--b1);
           border-radius:8px;padding:9px 14px;color:var(--t1);font-size:13px;
           font-family:"IBM Plex Sans",sans-serif;outline:none;
           transition:border-color 0.15s}}
  #search:focus{{border-color:var(--p)}}
  #search::placeholder{{color:var(--t3)}}
  /* RESPONSIVE */
  @media(max-width:800px){{
    .shell{{grid-template-columns:1fr;padding:0 16px 60px}}
    .main{{padding:0;border-right:none}}
    .sidebar{{padding:0;border-top:1px solid var(--b1);margin-top:32px;
              position:static}}
  }}
</style>
</head>
<body>
<div class="shell">
<main class="main">
  <div class="header">
    <div class="header-kicker">Lampe Joint BME · UNC Chapel Hill</div>
    <h1>Bioimaging<br><em>Daily Digest</em></h1>
    <p class="header-sub">Auto-generated · {generated}</p>
    <div class="stats">
      <div class="stat">
        <div class="stat-num" style="color:var(--p)">{len(cats["paper"])}</div>
        <div class="stat-label">Papers</div>
      </div>
      <div class="stat">
        <div class="stat-num" style="color:var(--g)">{len(cats["news"])}</div>
        <div class="stat-label">News</div>
      </div>
      <div class="stat">
        <div class="stat-num" style="color:var(--o)">{len(cats["trial"])}</div>
        <div class="stat-label">Trials</div>
      </div>
      <div class="stat">
        <div class="stat-num">{total}</div>
        <div class="stat-label">Total</div>
      </div>
    </div>
  </div>

  <div class="search-wrap">
    <input id="search" type="text" placeholder="Filter by keyword, source, or tag…"
           oninput="filterCards(this.value)">
  </div>

  <div class="filters">
    <button class="filter-btn active" onclick="setFilter('all',this)">All</button>
    <button class="filter-btn" onclick="setFilter('paper',this)">Papers</button>
    <button class="filter-btn" onclick="setFilter('news',this)">News</button>
    <button class="filter-btn" onclick="setFilter('trial',this)">Trials</button>
  </div>

  <div id="content">
    {sections}
  </div>
</main>

<aside class="sidebar">
  <div class="sidebar-block">
    <div class="sidebar-title">Top Keywords</div>
    {kw_pills}
  </div>
  <div class="sidebar-block">
    <div class="sidebar-title">By Source</div>
    {src_pills}
  </div>
  <div class="sidebar-block">
    <div class="sidebar-title">About</div>
    <p class="refresh-note">
      Refreshes daily via GitHub Actions.<br>
      Sources: arXiv · PubMed · Semantic Scholar ·
      OpenAlex · ClinicalTrials.gov · 9 RSS feeds ·
      3 direct scrapes.<br><br>
      Edit <code>KEYWORDS</code> in
      <code>scripts/scraper.py</code> to tune relevance.
    </p>
  </div>
</aside>
</div>

<script>
let activeFilter = 'all';

function setFilter(cat, btn) {{
  activeFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}}

function filterCards(query) {{
  applyFilters(query);
}}

function applyFilters(query) {{
  const q = (query !== undefined ? query : document.getElementById('search').value)
    .toLowerCase().trim();
  document.querySelectorAll('.card').forEach(card => {{
    const text  = card.innerText.toLowerCase();
    const cat   = card.dataset.cat || 'news';
    const catOk = activeFilter === 'all' || cat === activeFilter;
    const qOk   = !q || text.includes(q);
    card.style.display = (catOk && qOk) ? '' : 'none';
  }});
  // hide empty sections
  document.querySelectorAll('.section').forEach(sec => {{
    const visible = [...sec.querySelectorAll('.card')]
      .some(c => c.style.display !== 'none');
    sec.style.display = visible ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print(f"\n{'─'*50}")
    print(f"  BME Digest Scraper — {today()}")
    print(f"{'─'*50}\n")

    all_articles = []
    all_articles += fetch_arxiv()
    all_articles += fetch_pubmed()
    all_articles += fetch_semantic_scholar()
    all_articles += fetch_openalex()
    all_articles += fetch_rss()
    all_articles += fetch_bs4_sites()
    all_articles += fetch_clinicaltrials()

    unique = dedupe(all_articles)

    # Sort: papers → news → trials; within each by date desc
    order = {"paper": 0, "news": 1, "trial": 2}
    unique.sort(key=lambda a: (order.get(a.category, 1), a.date), reverse=False)
    unique.sort(key=lambda a: order.get(a.category, 1))

    # add data-cat to cards for JS filtering — patch into card HTML via dataset
    # (handled in render_html via card() inline style)

    print(f"\n✓ {len(unique)} unique relevant articles\n")

    # Ensure output dir exists
    os.makedirs("docs", exist_ok=True)

    # Write HTML dashboard
    html = render_html(unique)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("✓ docs/index.html written")

    # Write raw JSON
    with open("docs/data.json", "w", encoding="utf-8") as f:
        json.dump(
            {"generated": today(), "total": len(unique),
             "articles": [asdict(a) for a in unique]},
            f, indent=2,
        )
    print("✓ docs/data.json written")
    print(f"\n{'─'*50}\n")


if __name__ == "__main__":
    main()