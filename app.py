# Yankees History Timeline Dashboard
# Version: 0.8 (Season Articles 1903–1922 via Chronicling America; preserves all v0.7 functionality)
# Date: 2026-02-10
#
# Preserved:
# - Loads Lahman Teams.csv from repo root
# - Seasons-first timeline with decade / start-year filters
# - Season details view
# - Optional Supabase persistence (read/favorite/notes) via user_season_flags
# - Ring Counter (overall + in current filter)
# - Dynasty/Era bands in timeline
# - Safe slider (never crashes on small filtered sets)
#
# Added (v0.8):
# - "Articles" panel that auto-fetches historical newspaper pages for seasons 1903–1922
#   using Chronicling America search results JSON and shows snippet + link.

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

__version__ = "0.8"

# -----------------------------
# Optional Supabase
# -----------------------------
SUPABASE_ENABLED = False
try:
    from supabase import create_client  # type: ignore
    SUPABASE_ENABLED = True
except Exception:
    SUPABASE_ENABLED = False


# -----------------------------
# Styling (Yankees vibe + Era styling)
# -----------------------------
def inject_css():
    st.markdown(
        """
        <style>
        .stApp {
          background-image: repeating-linear-gradient(
            90deg,
            rgba(12,35,64,0.03),
            rgba(12,35,64,0.03) 2px,
            rgba(255,255,255,1) 2px,
            rgba(255,255,255,1) 10px
          );
        }

        .season-card {
          background: rgba(255,255,255,0.95);
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 14px;
          padding: 14px;
          margin-bottom: 10px;
          box-shadow: 0 6px 18px rgba(17,24,39,0.06);
        }

        .pill {
          display:inline-block;
          padding:3px 10px;
          border-radius:999px;
          border:1px solid rgba(12,35,64,0.25);
          background:rgba(12,35,64,0.06);
          font-size:0.75rem;
          margin-right:6px;
          margin-top:6px;
          white-space: nowrap;
        }

        .kpi {
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 14px;
          padding: 10px 12px;
          box-shadow: 0 6px 18px rgba(17,24,39,0.06);
        }
        .kpi-label { font-size: 0.80rem; color: rgba(17,24,39,0.70); }
        .kpi-value { font-size: 1.25rem; font-weight: 800; margin-top: 2px; }
        .kpi-sub { font-size: 0.85rem; color: rgba(17,24,39,0.70); margin-top: 2px; }

        /* Era band header */
        .era-band {
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 14px;
          padding: 10px 12px;
          margin: 14px 0 10px 0;
          box-shadow: 0 6px 18px rgba(17,24,39,0.05);
          background: rgba(255,255,255,0.92);
        }
        .era-title { font-weight: 900; letter-spacing: 0.2px; }
        .era-years { color: rgba(17,24,39,0.65); font-size: 0.9rem; margin-top: 2px; }

        /* Era-specific subtle left borders */
        .season-era-pre  { border-left: 8px solid rgba(12,35,64,0.35); }
        .season-era-ruth { border-left: 8px solid rgba(12,35,64,0.55); }
        .season-era-dim  { border-left: 8px solid rgba(12,35,64,0.48); }
        .season-era-mant { border-left: 8px solid rgba(12,35,64,0.40); }
        .season-era-zoo  { border-left: 8px solid rgba(12,35,64,0.32); }
        .season-era-lean { border-left: 8px solid rgba(12,35,64,0.26); }
        .season-era-core { border-left: 8px solid rgba(12,35,64,0.52); }
        .season-era-mod  { border-left: 8px solid rgba(12,35,64,0.34); }

        .article-card {
          border: 1px solid rgba(12,35,64,0.14);
          border-radius: 14px;
          padding: 12px 12px;
          margin: 10px 0;
          background: rgba(255,255,255,0.95);
          box-shadow: 0 6px 18px rgba(17,24,39,0.04);
        }
        .article-title { font-weight: 800; }
        .article-meta { color: rgba(17,24,39,0.68); font-size: 0.90rem; margin-top: 2px; }
        .article-snippet { margin-top: 8px; color: rgba(17,24,39,0.85); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, sub: str | None = None):
    sub_html = f"<div class='kpi-sub'>{sub}</div>" if sub else ""
    st.markdown(
        f"""
        <div class="kpi">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value">{value}</div>
          {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Era Bands
# -----------------------------
ERAS = [
    ("pre",  "Early Years (Highlanders / pre-Ruth)", 1903, 1919, "pre"),
    ("ruth", "Ruth & Gehrig Era",                    1920, 1934, "ruth"),
    ("dim",  "DiMaggio Era",                         1936, 1951, "dim"),
    ("mant", "Mantle / 50s–60s Dynasty",             1952, 1964, "mant"),
    ("zoo",  "Bronx Zoo / Late-70s Rise",            1976, 1981, "zoo"),
    ("lean", "Lean Years / Mattingly Era",           1982, 1995, "lean"),
    ("core", "Core Four Era",                        1996, 2009, "core"),
    ("mod",  "Modern Era",                           2010, 2026, "mod"),
]

def era_for_year(year: int) -> dict:
    for key, label, start, end, css in ERAS:
        if start <= year <= end:
            return {"key": key, "label": label, "start": start, "end": end, "css": css}
    return {"key": "pre", "label": "Other Years", "start": year, "end": year, "css": "pre"}


def render_era_header(era: dict):
    years = f"{era['start']}–{era['end']}" if era["start"] != era["end"] else f"{era['start']}"
    st.markdown(
        f"""
        <div class="era-band">
          <div class="era-title">{era['label']}</div>
          <div class="era-years">{years}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Data loading
# -----------------------------
@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    if "yearID" in df.columns:
        df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce")

    for col in ["DivWin", "WCWin", "LgWin", "WSWin"]:
        if col in df.columns:
            df[col] = df[col].fillna("")

    if "W" in df.columns and "L" in df.columns:
        w = pd.to_numeric(df["W"], errors="coerce")
        l = pd.to_numeric(df["L"], errors="coerce")
        df["win_pct"] = (w / (w + l)).round(3)

    return df


def get_yankees(df: pd.DataFrame) -> pd.DataFrame:
    if "teamID" not in df.columns:
        return pd.DataFrame()

    yank = df[df["teamID"] == "NYA"].copy()
    if yank.empty:
        return yank

    yank = yank.dropna(subset=["yearID"]).sort_values("yearID", ascending=False)

    yank["record"] = yank.apply(
        lambda r: f"{int(r['W'])}-{int(r['L'])}"
        if pd.notna(r.get("W")) and pd.notna(r.get("L"))
        else "—",
        axis=1,
    )

    def postseason(r):
        flags = []
        if r.get("WCWin") == "Y":
            flags.append("WC")
        if r.get("DivWin") == "Y":
            flags.append("DIV")
        if r.get("LgWin") == "Y":
            flags.append("AL")
        if r.get("WSWin") == "Y":
            flags.append("WS")
        return " · ".join(flags) if flags else "—"

    yank["postseason"] = yank.apply(postseason, axis=1)
    return yank


# -----------------------------
# Supabase helpers
# -----------------------------
def get_supabase():
    if not SUPABASE_ENABLED:
        return None
    url = st.secrets.get("SUPABASE_URL", "").strip()
    key = st.secrets.get("SUPABASE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def read_flags(sb, user_id: str) -> dict[int, dict]:
    if sb is None:
        return {}
    try:
        resp = sb.table("user_season_flags").select("*").eq("user_id", user_id).execute()
        data = resp.data or []
        out: dict[int, dict] = {}
        for r in data:
            try:
                out[int(r["year"])] = r
            except Exception:
                continue
        return out
    except Exception as e:
        if "PGRST205" in str(e) or "Could not find the table" in str(e):
            st.sidebar.warning("Supabase table `user_season_flags` not found yet. Create it to enable saving flags.")
            return {}
        st.sidebar.error(f"Supabase read error (flags): {e}")
        return {}


def save_flag(sb, user_id: str, year: int, read: bool, fav: bool, notes: str):
    if sb is None:
        return
    sb.table("user_season_flags").upsert(
        {
            "user_id": user_id,
            "year": int(year),
            "is_read": bool(read),
            "is_favorite": bool(fav),
            "notes": notes or "",
        },
        on_conflict="user_id,year",
    ).execute()


# -----------------------------
# Chronicling America articles (v0.8)
# -----------------------------
CHRONAM_BASE = "https://chroniclingamerica.loc.gov/search/pages/results/"

def _fetch_json(url: str, timeout_sec: int = 15) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; YankeesHistoryDashboard/0.8)"},
    )
    with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


@st.cache_data(show_spinner=False)
def chronam_search(year: int, query: str, rows: int = 20) -> List[Dict[str, Any]]:
    """
    Searches Chronicling America pages for a year range (same year) and query terms.
    Returns list of item dicts.
    API style is the /search/pages/results endpoint with format=json. :contentReference[oaicite:1]{index=1}
    """
    params = {
        "dateFilterType": "yearRange",
        "date1": str(year),
        "date2": str(year),
        "rows": str(rows),
        "searchType": "advanced",
        "format": "json",
        # Use 'andtext' for AND terms (space-separated becomes +)
        "andtext": query,
    }
    url = CHRONAM_BASE + "?" + urllib.parse.urlencode(params, doseq=True)
    data = _fetch_json(url)
    # Chronicling America search returns 'items' array (older style), but keep defensive.
    items = data.get("items")
    if isinstance(items, list):
        return items
    # Sometimes 'results' may appear in other structures; fallback
    results = data.get("results")
    if isinstance(results, list):
        return results
    return []


def pick_default_queries(year: int) -> List[str]:
    """
    Keep it simple: 2–3 preset searches per year.
    1903–1912: Highlanders era name frequently used.
    """
    if year <= 1912:
        return [
            "highlanders",
            "new york highlanders",
            "yankees",
        ]
    return [
        "yankees",
        "new york yankees",
        "baseball yankees",
    ]


def normalize_article_item(item: Dict[str, Any]) -> Dict[str, str]:
    """
    Normalizes a CA item to consistent fields for display.
    Typical fields in CA items include: title, date, edition, sequence, url, id, snip.
    """
    date = str(item.get("date") or item.get("issue_date") or "")
    paper = str(item.get("newspaper") or item.get("title") or item.get("publisher") or "Newspaper")
    # 'title' in CA items is sometimes paper title, so also check 'headline' or 'ocr_eng' isn't a title.
    headline = str(item.get("headline") or item.get("place_of_publication") or "Newspaper page")
    url = str(item.get("url") or item.get("id") or "")
    snippet = str(item.get("snip") or item.get("snippet") or item.get("ocr_eng") or "")

    # Keep snippet short for UI
    if len(snippet) > 380:
        snippet = snippet[:380].rstrip() + "…"

    return {
        "date": date,
        "paper": paper,
        "headline": headline,
        "url": url,
        "snippet": snippet,
    }


def display_articles_panel(year: int):
    st.markdown("### Articles (1903–1922)")

    if year < 1903 or year > 1922:
        st.info("Articles are enabled for **1903–1922** right now. (We’ll expand later once we pick the next archive source.)")
        return

    defaults = pick_default_queries(year)
    preset = st.selectbox("Preset searches", defaults, index=0)

    custom = st.text_input(
        "Add/override search terms (optional)",
        value="",
        help="Tip: keep it short (e.g., 'highlanders' or 'babe ruth').",
    )
    query = custom.strip() if custom.strip() else preset

    rows = st.slider("Results to fetch", min_value=10, max_value=50, value=20, step=10)

    with st.spinner("Searching newspaper pages…"):
        try:
            items = chronam_search(year, query=query, rows=rows)
        except Exception as e:
            st.error(f"Could not fetch articles: {e}")
            return

    if not items:
        st.warning("No results found for that query. Try different terms.")
        return

    st.caption("Results are digitized newspaper *pages* with OCR snippets. Click through to view the scan.")

    for it in items:
        a = normalize_article_item(it)
        date = a["date"] or "Unknown date"
        paper = a["paper"] or "Newspaper"
        url = a["url"]
        snippet = a["snippet"] or ""

        # Build a nicer label: some CA items use 'title' as newspaper title; treat as paper name.
        top_line = f"{date} • {paper}"
        link = f"[Open page]({url})" if url else ""

        st.markdown(
            f"""
            <div class="article-card">
              <div class="article-title">{top_line}</div>
              <div class="article-meta">{link}</div>
              <div class="article-snippet">{snippet if snippet else "<i>No OCR snippet available.</i>"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# -----------------------------
# Main App
# -----------------------------
def main():
    st.set_page_config(page_title="Yankees History Timeline", layout="wide")
    inject_css()

    st.title("Yankees History Timeline")
    st.sidebar.caption(f"Version {__version__}")

    # Load data
    try:
        df = load_data("Teams.csv")
    except Exception as e:
        st.error(f"Error loading Teams.csv from repo root: {e}")
        st.stop()

    yank = get_yankees(df)
    if yank.empty:
        st.error("No Yankees seasons found (teamID='NYA'). Check your Teams.csv.")
        st.stop()

    # Sidebar filters
    years_all = yank["yearID"].dropna().astype(int).tolist()
    min_year, max_year = min(years_all), max(years_all)

    st.sidebar.header("Filters")
    start_year = st.sidebar.slider("Start year", min_year, max_year, min_year)

    decade_starts = sorted({(y // 10) * 10 for y in years*_
