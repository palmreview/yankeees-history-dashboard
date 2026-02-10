# Yankees History Timeline Dashboard
# Version: 0.6 (adds Ring Counter; preserves all v0.5 functionality)
# Date: 2026-02-09
#
# v0.5 functionality preserved:
# - Loads Lahman Teams.csv from repo root
# - Seasons-first timeline with decade / start-year filters
# - Season details view
# - Optional Supabase persistence (read/favorite/notes) via user_season_flags
#
# v0.6 adds:
# - World Series "Ring Counter" (overall + in current filter)

import os
import pandas as pd
import streamlit as st

__version__ = "0.6"

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
# Styling (Yankees vibe)
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
        }
        .kpi-row {
          display:flex;
          gap:12px;
          flex-wrap:wrap;
          margin: 6px 0 14px 0;
        }
        .kpi {
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 14px;
          padding: 10px 12px;
          box-shadow: 0 6px 18px rgba(17,24,39,0.06);
          min-width: 180px;
        }
        .kpi-label { font-size: 0.80rem; color: rgba(17,24,39,0.70); }
        .kpi-value { font-size: 1.25rem; font-weight: 800; margin-top: 2px; }
        .kpi-sub { font-size: 0.85rem; color: rgba(17,24,39,0.70); margin-top: 2px; }
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
# Data loading
# -----------------------------
@st.cache_data(show_spinner=False)
def load_data(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)

    # yearID can be int; keep as numeric
    if "yearID" in df.columns:
        df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce")

    # postseason flags
    for col in ["DivWin", "WCWin", "LgWin", "WSWin"]:
        if col in df.columns:
            df[col] = df[col].fillna("")

    # win pct
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
    """
    Returns dict: {year: row}
    If table doesn't exist yet, returns empty dict (and warns once).
    """
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
        # Don't crash the whole app if the table isn't created yet.
        # Common: PGRST205 "Could not find the table ..."
        if "PGRST205" in str(e) or "Could not find the table" in str(e):
            st.sidebar.warning("Supabase table `user_season_flags` not found yet. Create it in Supabase (SQL) to enable saving.")
            return {}
        # For anything else, surface it (still not removing functionality, just visibility)
        st.sidebar.error(f"Supabase read error: {e}")
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

    # stable decade list (sorted by decade start)
    decade_starts = sorted({(y // 10) * 10 for y in years_all})
    decade_options = ["All"] + [f"{d}s" for d in decade_starts]
    decade = st.sidebar.selectbox("Decade", decade_options, index=0)

    postseason_only = st.sidebar.checkbox("Postseason only", value=False)
    ws_only = st.sidebar.checkbox("World Series titles only", value=False)

    # Apply filters
    filtered = yank[yank["yearID"] >= start_year].copy()

    if decade != "All":
        d0 = int(decade[:4])
        filtered = filtered[(filtered["yearID"] >= d0) & (filtered["yearID"] <= d0 + 9)]

    if postseason_only:
        filtered = filtered[filtered["postseason"] != "—"]

    if ws_only:
        if "WSWin" in filtered.columns:
            filtered = filtered[filtered["WSWin"] == "Y"]
        else:
            filtered = filtered.iloc[0:0]

    filtered = filtered.sort_values("yearID", ascending=False)

    if filtered.empty:
        st.warning("No seasons match filters.")
        return

    # -----------------------------
    # v0.6 Ring Counter (overall + in-filter)
    # -----------------------------
    overall_rings = int((yank["WSWin"] == "Y").sum()) if "WSWin" in yank.columns else 0
    filtered_rings = int((filtered["WSWin"] == "Y").sum()) if "WSWin" in filtered.columns else 0

    seasons_in_view = len(filtered)
    postseason_in_view = int((filtered["postseason"] != "—").sum())

    st.markdown("<div class='kpi-row'>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    with c1:
        kpi_card("🏆 Ring Counter (all time)", f"{overall_rings}", "World Series titles (NYA)")
    with c2:
        kpi_card("🏆 Rings (current filters)", f"{filtered_rings}", "Titles in this filtered view")
    with c3:
        kpi_card("Seasons in view", f"{seasons_in_view}", f"Postseason seasons: {postseason_in_view}")
    st.markdown("</div>", unsafe_allow_html=True)

    # Supabase + flags
    sb = get_supabase()
    user_id = "default_user"  # MVP identity
    flags = read_flags(sb, user_id)

    # Layout
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

        # Safe slider (never crashes)
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

        for _, row in filtered.head(show_n).iterrows():
            year = int(row["yearID"])
            record = row.get("record", "—")
            post = row.get("postseason", "—")

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
                <div class='season-card'>
                  <div style="display:flex; justify-content:space-between; gap:10px; align-items:baseline;">
                    <div style="font-size:1.05rem; font-weight:800;">{year}</div>
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

        st.subheader(f"{year} Season")
        st.metric("Record", row.get("record", "—"))
        st.metric("Win %", row.get("win_pct", "—"))
        st.metric("Postseason", row.get("postseason", "—"))

        existing = flags.get(year, {})
        read = st.checkbox("Read", value=bool(existing.get("is_read", False)))
        fav = st.checkbox("Favorite", value=bool(existing.get("is_favorite", False)))
        notes = st.text_area("Notes", value=existing.get("notes", ""))

        if sb is None:
            st.warning("Supabase not configured. Add SUPABASE_URL and SUPABASE_KEY in Streamlit Cloud secrets to enable saving.")
        else:
            if st.button("Save"):
                try:
                    save_flag(sb, user_id, year, read, fav, notes)
                    st.success("Saved!")
                except Exception as e:
                    st.error(f"Save failed: {e}")

    st.sidebar.caption("Data: Lahman Teams.csv (repo root)")


if __name__ == "__main__":
    main()
