# Yankees History Timeline Dashboard
# Version: 0.8.2 (loc.gov search ops + better presets; preserves all existing functionality)
# Date: 2026-02-10
#
# Preserved:
# - Loads Lahman Teams.csv from repo root
# - Seasons-first timeline with decade / start-year filters
# - Season details view
# - Optional Supabase persistence (read/favorite/notes) via user_season_flags
# - Ring Counter (overall + in current filter)
# - Dynasty/Era bands in timeline
# - Safe selection (never crashes on small filtered sets)
# - Articles panel via loc.gov Chronicling America collection (clickable links)
#
# Updated (v0.8.2):
# - loc.gov search now uses explicit `ops` (AND / PHRASE / OR) instead of relying on quotes
# - Preset queries no longer use quotes (OCR tolerant)
# - Optional "Prefer New York papers" facet to reduce noise without killing results
# - Keeps strict filter (team term required) and sorts by baseball-likeness

import json
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st

__version__ = "0.8.2"

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
        .article-meta { color: rgba(17,24,39,0.68); font-size: 0.90rem; margin-top: 4px; }
        .article-snippet { margin-top: 8px; color: rgba(17,24,39,0.85); }

        .small-note { color: rgba(17,24,39,0.65); font-size: 0.9rem; }
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
    ("pre", "Early Years (Highlanders / pre-Ruth)", 1903, 1919, "pre"),
    ("ruth", "Ruth & Gehrig Era", 1920, 1934, "ruth"),
    ("dim", "DiMaggio Era", 1936, 1951, "dim"),
    ("mant", "Mantle / 50s–60s Dynasty", 1952, 1964, "mant"),
    ("zoo", "Bronx Zoo / Late-70s Rise", 1976, 1981, "zoo"),
    ("lean", "Lean Years / Mattingly Era", 1982, 1995, "lean"),
    ("core", "Core Four Era", 1996, 2009, "core"),
    ("mod", "Modern Era", 2010, 2026, "mod"),
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
# Articles (loc.gov Chronicling America collection)
# -----------------------------
CHRONAM_BASE = "https://www.loc.gov/collections/chronicling-america/"

BASEBALL_TERMS = [
    "baseball",
    "base ball",
    "american league",
    "national league",
    "world series",
    "box score",
    "boxscore",
    "innings",
    "pitcher",
    "pitching",
    "batting",
    "batted",
    "home run",
    "home-run",
    "homered",
    "doubleheader",
    "double-header",
    "ball club",
    "ballclub",
    "diamond",
    "runs",
    "hits",
    "rbi",
]

TEAM_TERMS_PRE1913 = ["highlanders", "new york highlanders"]
TEAM_TERMS_POST1912 = ["yankees", "new york yankees"]


def _fetch_json(url: str, timeout_sec: int = 15) -> Dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; YankeesHistoryDashboard/0.8.2)",
            "Accept": "application/json,text/javascript,*/*;q=0.1",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw_bytes = resp.read()

        text = raw_bytes.decode("utf-8", errors="replace").strip()
        if not text:
            raise RuntimeError(f"Empty response (HTTP {status}).")

        if "json" not in ctype and not text.lstrip().startswith("{"):
            preview = text[:220].replace("\n", " ").replace("\r", " ")
            raise RuntimeError(
                f"Did not return JSON (HTTP {status}, Content-Type: {ctype or 'unknown'}). Preview: {preview}"
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            preview = text[:220].replace("\n", " ").replace("\r", " ")
            raise RuntimeError(
                f"Invalid JSON (HTTP {status}, Content-Type: {ctype or 'unknown'}). Preview: {preview}"
            )

    except Exception as e:
        raise RuntimeError(f"Article fetch failed: {e}") from e


@st.cache_data(show_spinner=False)
def chronam_search_locgov(
    year: int,
    query: str,
    rows: int = 20,
    ops: str = "AND",
    state: str | None = None,
) -> List[Dict[str, Any]]:
    """
    loc.gov Chronicling America collection search.
    Uses explicit `ops` (AND/PHRASE/OR) instead of relying on quotes.
    Optional state facet reduces noise without requiring baseball words in the snippet.
    """
    query = (query or "").strip()
    if not query:
        return []

    rows = max(1, min(int(rows), 50))
    ops = (ops or "AND").strip().upper()

    params = {
        "fo": "json",
        "c": str(rows),
        "qs": query,
        "ops": ops,
        "start_date": f"{year}-01-01",
        "end_date": f"{year}-12-31",
        "dl": "page",
    }

    if state:
        params["location_state"] = state

    url = CHRONAM_BASE + "?" + urllib.parse.urlencode(params, doseq=True)
    data = _fetch_json(url)

    results = data.get("results")
    return results if isinstance(results, list) else []


# ✅ Updated presets: no quotes (OCR tolerant) + period-accurate "base ball"
def pick_default_queries(year: int) -> List[str]:
    if year <= 1912:
        return [
            "new york highlanders base ball",
            "highlanders american league base ball",
            "new york highlanders box score",
            "highlanders pitcher base ball",
        ]
    return [
        "new york yankees base ball",
        "yankees american league base ball",
        "new york yankees box score",
        "yankees pitcher base ball",
    ]


def _best_public_url(item: Dict[str, Any]) -> str:
    url = ""
    v = item.get("url")
    if isinstance(v, str) and v.strip():
        url = v.strip()

    aka = item.get("aka")
    if (not url) and isinstance(aka, list) and aka:
        if isinstance(aka[0], str) and aka[0].strip():
            url = aka[0].strip()

    item_url = item.get("item_url")
    if (not url) and isinstance(item_url, str) and item_url.strip():
        url = item_url.strip()

    return url


def normalize_article_item(item: Dict[str, Any]) -> Dict[str, str]:
    date = str(item.get("date") or "")
    title = str(item.get("title") or "Newspaper page")
    url = _best_public_url(item)
    snippet = str(item.get("snippet") or item.get("description") or "")

    if len(snippet) > 420:
        snippet = snippet[:420].rstrip() + "…"

    return {"date": date, "paper": title, "headline": title, "url": url, "snippet": snippet}


def _text_blob_for_relevance(item: Dict[str, Any]) -> str:
    parts = [
        str(item.get("title") or ""),
        str(item.get("snippet") or ""),
        str(item.get("description") or ""),
    ]
    return " ".join(parts).lower()


def is_team_relevant(item: Dict[str, Any], year: int) -> bool:
    blob = _text_blob_for_relevance(item)
    team_terms = TEAM_TERMS_PRE1913 if year <= 1912 else TEAM_TERMS_POST1912
    return any(t in blob for t in team_terms)


def baseball_score(item: Dict[str, Any]) -> int:
    blob = _text_blob_for_relevance(item)
    return sum(1 for t in BASEBALL_TERMS if t in blob)


def display_articles_panel(year: int):
    st.markdown("### Articles (1903–1922)")

    if year < 1903 or year > 1922:
        st.info("Articles are enabled for **1903–1922** right now. (We’ll expand later.)")
        return

    defaults = pick_default_queries(year)
    preset = st.selectbox("Preset searches", defaults, index=0)

    custom = st.text_input(
        "Add/override search terms (optional)",
        value="",
        help='Try: "box score", "American League", pitcher names. Early papers often use "base ball" (two words).',
    )
    query = custom.strip() if custom.strip() else preset

    colA, colB, colC = st.columns([1, 1, 1])
    with colA:
        rows = st.slider("Results to fetch", min_value=10, max_value=50, value=20, step=10)
    with colB:
        ops = st.selectbox("Search mode", ["AND", "PHRASE", "OR"], index=0, help="AND = all words; PHRASE = exact phrase; OR = any word.")
    with colC:
        ny_only = st.checkbox("Prefer New York papers", value=False, help="Facet filter that reduces off-topic results.")

    strict = st.checkbox("Require team mention (recommended)", value=True)

    state = "new york" if ny_only else None

    with st.spinner("Searching newspaper pages…"):
        try:
            items = chronam_search_locgov(year, query=query, rows=rows, ops=ops, state=state)
        except Exception as e:
            st.error(f"Could not fetch articles: {e}")
            return

    if strict:
        items = [it for it in items if is_team_relevant(it, year)]
        items.sort(key=baseball_score, reverse=True)

    if not items:
        st.warning(
            "No results found with these settings. "
            "Try switching Search mode to OR, removing 'base ball', disabling 'Prefer New York', or disabling strict."
        )
        return

    st.caption("These are digitized newspaper pages with OCR snippets. Click to open on Library of Congress.")

    for it in items:
        a = normalize_article_item(it)
        date = a["date"] or "Unknown date"
        paper = a["paper"] or "Newspaper"
        url = a["url"]
        snippet = a["snippet"] or ""

        if url:
            top_line = f"[{date} • {paper}]({url})"
            link_line = f"🔗 [View newspaper page]({url})"
        else:
            top_line = f"{date} • {paper}"
            link_line = "<i>No link available for this result.</i>"

        st.markdown(
            f"""
            <div class="article-card">
              <div class="article-title">{top_line}</div>
              <div class="article-meta">{link_line}</div>
              <div class="article-snippet">{snippet if snippet else "<i>No OCR snippet available.</i>"}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


# -----------------------------
# UI helpers
# -----------------------------
def ws_rings_count(df: pd.DataFrame) -> int:
    if df.empty or "WSWin" not in df.columns:
        return 0
    return int((df["WSWin"] == "Y").sum())


def season_pills(row: pd.Series) -> str:
    pills = []
    if row.get("WSWin") == "Y":
        pills.append("<span class='pill'>🏆 WS Champs</span>")
    if row.get("LgWin") == "Y":
        pills.append("<span class='pill'>AL Champs</span>")
    if row.get("DivWin") == "Y":
        pills.append("<span class='pill'>Div Champs</span>")
    if row.get("WCWin") == "Y":
        pills.append("<span class='pill'>Wild Card</span>")
    return "".join(pills)


def safe_default_year(available_years_desc: List[int], requested: Optional[int]) -> int:
    if not available_years_desc:
        return 0
    if requested is not None and requested in available_years_desc:
        return requested
    return available_years_desc[0]


def render_season_card(row: pd.Series, flags: Optional[dict] = None):
    year = int(row["yearID"])
    era = era_for_year(year)
    css = f"season-card season-era-{era['css']}"

    record = str(row.get("record") or "—")
    win_pct = row.get("win_pct")
    win_pct_str = f"{float(win_pct):.3f}" if pd.notna(win_pct) else "—"
    postseason = str(row.get("postseason") or "—")

    read_mark = ""
    fav_mark = ""
    notes_hint = ""

    if flags:
        f = flags.get(year) or {}
        if f.get("is_read"):
            read_mark = " ✅ Read"
        if f.get("is_favorite"):
            fav_mark = " ⭐ Favorite"
        if (f.get("notes") or "").strip():
            notes_hint = " 📝 Notes"

    pills = season_pills(row)
    marker_text = (read_mark + fav_mark + notes_hint).strip()
    marker_html = f"<span class='pill'>{marker_text}</span>" if marker_text else ""

    st.markdown(
        f"""
        <div class="{css}">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px;">
            <div>
              <div style="font-size:1.2rem; font-weight:900;">{year} Yankees</div>
              <div class="small-note">{era['label']}</div>
            </div>
            <div style="text-align:right;">
              <div style="font-weight:800;">{record}</div>
              <div class="small-note">Win% {win_pct_str}</div>
            </div>
          </div>
          <div style="margin-top:8px;">
            <span class="pill">Postseason: {postseason}</span>
            {pills}
            {marker_html}
          </div>
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

    # Supabase sidebar
    st.sidebar.header("Persistence (optional)")
    sb = get_supabase()
    use_sb = False
    user_id = "default"
    flags: dict[int, dict] = {}

    if sb is None:
        if SUPABASE_ENABLED:
            st.sidebar.info("Supabase library is available, but SUPABASE_URL / SUPABASE_KEY not set in secrets.")
        else:
            st.sidebar.info("Supabase not installed in this environment (optional).")
    else:
        use_sb = st.sidebar.toggle("Enable Supabase saving", value=True)
        user_id = st.sidebar.text_input("User ID", value="andrew", help="Simple identifier for your flags/notes.")
        if use_sb:
            flags = read_flags(sb, user_id=user_id)

    st.sidebar.divider()

    # Sidebar filters
    years_all = yank["yearID"].dropna().astype(int).tolist()
    min_year, max_year = min(years_all), max(years_all)

    st.sidebar.header("Filters")
    start_year = st.sidebar.slider("Start year", min_year, max_year, min_year)

    # Decades (safe)
    try:
        years_for_decades = [int(y) for y in years_all if y is not None]
    except Exception:
        years_for_decades = []

    decade_starts = sorted({(y // 10) * 10 for y in years_for_decades}) if years_for_decades else []
    selected_decades = st.sidebar.multiselect(
        "Decades (optional)",
        options=decade_starts,
        default=[],
        format_func=lambda d: f"{d}s",
        help="Pick one or more decades to narrow the timeline.",
    )

    only_ws = st.sidebar.toggle("World Series champs only", value=False)
    only_favs = st.sidebar.toggle("Favorites only", value=False) if use_sb else False
    only_read = st.sidebar.toggle("Read only", value=False) if use_sb else False

    # Apply filters
    filt = yank[yank["yearID"].astype(int) >= int(start_year)].copy()

    if selected_decades:
        filt["decade"] = (filt["yearID"].astype(int) // 10) * 10
        filt = filt[filt["decade"].isin(selected_decades)].copy()

    if only_ws and "WSWin" in filt.columns:
        filt = filt[filt["WSWin"] == "Y"].copy()

    if use_sb and (only_favs or only_read):
        keep_years = set()
        for y, r in flags.items():
            if only_favs and r.get("is_favorite"):
                keep_years.add(int(y))
            if only_read and r.get("is_read"):
                keep_years.add(int(y))
        filt = filt[filt["yearID"].astype(int).isin(sorted(keep_years))].copy()

    filt = filt.sort_values("yearID", ascending=False)
    years_filt_desc = filt["yearID"].dropna().astype(int).tolist()

    # Ring counters
    total_rings = ws_rings_count(yank)
    filtered_rings = ws_rings_count(filt)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        kpi_card("Total WS Rings", str(total_rings), "All seasons in dataset")
    with c2:
        kpi_card("Rings in Filter", str(filtered_rings), "Matches current filters")
    with c3:
        st.markdown(
            "<div class='kpi'><div class='kpi-label'>Filter Summary</div>"
            f"<div class='kpi-sub'>Start year ≥ <b>{start_year}</b>"
            + (f" • Decades: <b>{', '.join([str(d)+'s' for d in selected_decades])}</b>" if selected_decades else "")
            + (" • WS only" if only_ws else "")
            + (" • Favorites only" if only_favs else "")
            + (" • Read only" if only_read else "")
            + "</div></div>",
            unsafe_allow_html=True,
        )

    if filt.empty:
        st.warning("No seasons match your current filters.")
        st.stop()

    # Selected year (safe)
    if "selected_year" not in st.session_state:
        st.session_state["selected_year"] = years_filt_desc[0]

    st.session_state["selected_year"] = safe_default_year(
        available_years_desc=years_filt_desc, requested=st.session_state.get("selected_year")
    )

    # Layout: timeline + details
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.subheader("Timeline")

        last_era_key = None
        for _, row in filt.iterrows():
            year = int(row["yearID"])
            era = era_for_year(year)

            if era["key"] != last_era_key:
                render_era_header(era)
                last_era_key = era["key"]

            cols = st.columns([0.82, 0.18])
            with cols[0]:
                render_season_card(row, flags=flags if use_sb else None)
            with cols[1]:
                if st.button("View", key=f"view_{year}"):
                    st.session_state["selected_year"] = year
                    st.rerun()

    with right:
        st.subheader("Season Details")

        sel = st.selectbox(
            "Jump to season",
            options=years_filt_desc,
            index=0,
            format_func=lambda y: str(y),
            key="jump_selectbox",
        )
        if sel != st.session_state["selected_year"]:
            st.session_state["selected_year"] = int(sel)

        sel_year = int(st.session_state["selected_year"])
        row_df = yank[yank["yearID"].astype(int) == sel_year]
        if row_df.empty:
            st.error("Selected season not found in dataset.")
            st.stop()
        row = row_df.iloc[0]

        render_season_card(row, flags=flags if use_sb else None)

        if use_sb:
            f = flags.get(sel_year) or {}
            st.markdown("#### Your Flags")

            colA, colB = st.columns(2)
            with colA:
                is_read = st.checkbox("Mark as read", value=bool(f.get("is_read")), key=f"read_{sel_year}")
            with colB:
                is_fav = st.checkbox("Favorite", value=bool(f.get("is_favorite")), key=f"fav_{sel_year}")

            notes = st.text_area(
                "Notes",
                value=str(f.get("notes") or ""),
                height=110,
                key=f"notes_{sel_year}",
                placeholder="What stood out? Players, stories, memories…",
            )

            if st.button("Save", key=f"save_{sel_year}"):
                try:
                    save_flag(sb, user_id=user_id, year=sel_year, read=is_read, fav=is_fav, notes=notes)
                    st.success("Saved.")
                    flags = read_flags(sb, user_id=user_id)
                except Exception as e:
                    st.error(f"Could not save: {e}")

        st.markdown("#### Season Snapshot")
        snap = {
            "Year": sel_year,
            "Record": row.get("record", "—"),
            "Win %": f"{float(row['win_pct']):.3f}" if pd.notna(row.get("win_pct")) else "—",
            "Postseason": row.get("postseason", "—"),
            "WSWin": row.get("WSWin", ""),
            "LgWin": row.get("LgWin", ""),
            "DivWin": row.get("DivWin", ""),
            "WCWin": row.get("WCWin", ""),
        }
        st.write(snap)

        st.divider()
        display_articles_panel(sel_year)


if __name__ == "__main__":
    main()
