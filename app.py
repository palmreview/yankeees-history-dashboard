# Yankees History Timeline Dashboard
# Version: 0.8 (adds Season Stories; preserves all v0.7 functionality)
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
# - Season Stories (read + add) via Supabase table season_stories
#   Fields: id(uuid), year(int), title(text), story(text), tags(text), source_url(text), created_at

import os
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
# Styling
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
        }
        .era-title { font-weight: 900; letter-spacing: 0.2px; }
        .era-years { color: rgba(17,24,39,0.65); font-size: 0.9rem; margin-top: 2px; }

        /* Era-specific left borders */
        .season-era-pre  { border-left: 8px solid rgba(12,35,64,0.35); }
        .season-era-ruth { border-left: 8px solid rgba(12,35,64,0.55); }
        .season-era-dim  { border-left: 8px solid rgba(12,35,64,0.48); }
        .season-era-mant { border-left: 8px solid rgba(12,35,64,0.40); }
        .season-era-zoo  { border-left: 8px solid rgba(12,35,64,0.32); }
        .season-era-lean { border-left: 8px solid rgba(12,35,64,0.26); }
        .season-era-core { border-left: 8px solid rgba(12,35,64,0.52); }
        .season-era-mod  { border-left: 8px solid rgba(12,35,64,0.34); }
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
# Stories (v0.8)
# -----------------------------
def read_stories_for_year(sb, year: int) -> list[dict]:
    if sb is None:
        return []
    try:
        resp = (
            sb.table("season_stories")
            .select("id,year,title,story,tags,source_url,created_at")
            .eq("year", int(year))
            .order("created_at", desc=True)
            .execute()
        )
        return resp.data or []
    except Exception as e:
        if "PGRST205" in str(e) or "Could not find the table" in str(e):
            st.warning("Stories table `season_stories` not found yet. Create it in Supabase to enable stories.")
            return []
        st.error(f"Supabase read error (stories): {e}")
        return []


def add_story(sb, year: int, title: str, story: str, tags: str, source_url: str):
    if sb is None:
        return
    payload = {
        "year": int(year),
        "title": title.strip(),
        "story": story.strip(),
        "tags": tags.strip(),
        "source_url": source_url.strip(),
    }
    sb.table("season_stories").insert(payload).execute()


def normalize_tags(tags_str: str) -> list[str]:
    if not tags_str:
        return []
    parts = [t.strip().lower() for t in tags_str.split(",")]
    return [p for p in parts if p]


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

    years_all = yank["yearID"].dropna().astype(int).tolist()
    min_year, max_year = min(years_all), max(years_all)

    # Sidebar filters
    st.sidebar.header("Filters")
    start_year = st.sidebar.slider("Start year", min_year, max_year, min_year)

    decade_starts = sorted({(y // 10) * 10 for y in years_all})
    decade_options = ["All"] + [f"{d}s" for d in decade_starts]
    decade = st.sidebar.selectbox("Decade", decade_options, index=0)

    postseason_only = st.sidebar.checkbox("Postseason only", value=False)
    ws_only = st.sidebar.checkbox("World Series titles only", value=False)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Era bands")
    for _, label, start, end, _css in ERAS:
        st.sidebar.markdown(f"- **{label}** ({start}–{end})")

    # Apply filters
    filtered = yank[yank["yearID"] >= start_year].copy()

    if decade != "All":
        d0 = int(decade[:4])
        filtered = filtered[(filtered["yearID"] >= d0) & (filtered["yearID"] <= d0 + 9)]

    if postseason_only:
        filtered = filtered[filtered["postseason"] != "—"]

    if ws_only:
        filtered = filtered[filtered["WSWin"] == "Y"] if "WSWin" in filtered.columns else filtered.iloc[0:0]

    filtered = filtered.sort_values("yearID", ascending=False)

    if filtered.empty:
        st.warning("No seasons match filters.")
        return

    # Ring counters
    overall_rings = int((yank["WSWin"] == "Y").sum()) if "WSWin" in yank.columns else 0
    filtered_rings = int((filtered["WSWin"] == "Y").sum()) if "WSWin" in filtered.columns else 0
    seasons_in_view = len(filtered)
    postseason_in_view = int((filtered["postseason"] != "—").sum())

    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("🏆 Ring Counter (all time)", f"{overall_rings}", "World Series titles (NYA)")
    with c2:
        kpi_card("🏆 Rings (current filters)", f"{filtered_rings}", "Titles in this filtered view")
    with c3:
        kpi_card("Seasons in view", f"{seasons_in_view}", f"Postseason seasons: {postseason_in_view}")

    # Supabase + persistence
    sb = get_supabase()
    user_id = "default_user"
    flags = read_flags(sb, user_id)

    left, right = st.columns([1.2, 0.8])

    years = filtered["yearID"].astype(int).tolist()
    if "selected_year" not in st.session_state or st.session_state.selected_year not in years:
        st.session_state.selected_year = years[0]

    with left:
        st.subheader("Timeline")

        st.session_state.selected_year = st.selectbox(
            "Select season",
            years,
            index=years.index(st.session_state.selected_year),
        )

        # Safe slider
        n = len(filtered)
        if n <= 10:
            show_n = n
            st.caption(f"Showing all {n} seasons (filtered).")
        else:
            show_n = st.slider(
                "How many seasons to show",
                min_value=10,
                max_value=min(160, n),
                value=min(30, min(160, n)),
            )

        # Render era bands + season cards
        last_era_key = None
        for _, row in filtered.head(show_n).iterrows():
            year = int(row["yearID"])
            record = row.get("record", "—")
            post = row.get("postseason", "—")

            era = era_for_year(year)
            if era["key"] != last_era_key:
                render_era_header(era)
                last_era_key = era["key"]

            pills = []
            if row.get("WSWin", "") == "Y":
                pills.append("<span class='pill'>🏆 WS Champs</span>")
            if post != "—":
                pills.append(f"<span class='pill'>Postseason: {post}</span>")

            yr_flags = flags.get(year, {})
            if yr_flags.get("is_favorite"):
                pills.append("<span class='pill'>★ Favorite</span>")
            if yr_flags.get("is_read"):
                pills.append("<span class='pill'>✓ Read</span>")

            pills_html = "".join(pills) if pills else "<span style='color:rgba(17,24,39,0.65)'>No flags</span>"

            st.markdown(
                f"""
                <div class='season-card season-era-{era["css"]}'>
                  <div style="display:flex; justify-content:space-between; gap:10px; align-items:baseline;">
                    <div style="font-size:1.05rem; font-weight:900;">{year}</div>
                    <div style="color:rgba(17,24,39,0.70);">{record} · {post}</div>
                  </div>
                  <div style="margin-top:6px;">{pills_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right:
        year = int(st.session_state.selected_year)
        row = filtered[filtered["yearID"].astype(int) == year].iloc[0]
        era = era_for_year(year)

        st.subheader(f"{year} Season")
        st.caption(f"Era: **{era['label']}**")

        st.metric("Record", row.get("record", "—"))
        st.metric("Win %", row.get("win_pct", "—"))
        st.metric("Postseason", row.get("postseason", "—"))

        # Flags/notes
        st.markdown("---")
        st.markdown("### Your flags & notes")

        existing = flags.get(year, {})
        read = st.checkbox("Read", value=bool(existing.get("is_read", False)))
        fav = st.checkbox("Favorite", value=bool(existing.get("is_favorite", False)))
        notes = st.text_area("Notes", value=existing.get("notes", ""), height=100)

        if sb is None:
            st.warning("Supabase not configured. Add SUPABASE_URL and SUPABASE_KEY in Streamlit Cloud secrets to enable saving.")
        else:
            if st.button("Save flags/notes", use_container_width=True):
                try:
                    save_flag(sb, user_id, year, read, fav, notes)
                    st.success("Saved flags/notes!")
                except Exception as e:
                    st.error(f"Save failed: {e}")

        # Stories (v0.8)
        st.markdown("---")
        st.markdown("### Stories")

        stories = read_stories_for_year(sb, year) if sb is not None else []
        all_tags = sorted({t for s in stories for t in normalize_tags(s.get("tags", ""))})

        if stories:
            tag_filter = st.selectbox("Filter by tag", ["All"] + all_tags, index=0)
            for s in stories:
                tags = normalize_tags(s.get("tags", ""))
                if tag_filter != "All" and tag_filter.lower() not in tags:
                    continue

                with st.expander(s.get("title", "Untitled story"), expanded=False):
                    st.write(s.get("story", ""))
                    meta_bits = []
                    if s.get("tags"):
                        meta_bits.append(f"**Tags:** {s.get('tags')}")
                    if s.get("source_url"):
                        meta_bits.append(f"**Source:** {s.get('source_url')}")
                    if meta_bits:
                        st.markdown("  \n".join(meta_bits))
        else:
            st.info("No stories yet for this season. Add the first one below.")

        # Add story form
        st.markdown("#### Add a story")
        with st.form(key="add_story_form", clear_on_submit=True):
            title = st.text_input("Title", placeholder="e.g., 'Turning point season' or 'Iconic moment'")
            story_text = st.text_area("Story (2–6 sentences)", height=140, placeholder="Write a short narrative. Keep it readable.")
            tags = st.text_input("Tags (comma-separated)", placeholder="e.g., dynasty, rivalry, rookie, pitching")
            source_url = st.text_input("Source URL (optional)", placeholder="Paste a link if you used one")
            submitted = st.form_submit_button("Add story")

        if submitted:
            if sb is None:
                st.error("Supabase isn’t configured yet, so stories can’t be saved.")
            else:
                if not title.strip() or not story_text.strip():
                    st.error("Please enter at least a Title and Story.")
                else:
                    try:
                        add_story(sb, year, title, story_text, tags, source_url)
                        st.success("Story added!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Could not add story: {e}")

    st.sidebar.markdown("---")
    st.sidebar.caption("Data: Lahman Teams.csv (repo root)")


if __name__ == "__main__":
    main()
