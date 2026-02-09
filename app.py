import os
import pandas as pd
import streamlit as st

# -----------------------------
# Optional Supabase (safe import)
# -----------------------------
SUPABASE_ENABLED = False
try:
    from supabase import create_client  # type: ignore
    SUPABASE_ENABLED = True
except Exception:
    SUPABASE_ENABLED = False


# -----------------------------
# Yankees-ish styling (no logos)
# -----------------------------
def inject_css():
    st.markdown(
        """
        <style>
        /* Subtle pinstripe background */
        .stApp {
          background-image: repeating-linear-gradient(
            90deg,
            rgba(12,35,64,0.03),
            rgba(12,35,64,0.03) 2px,
            rgba(255,255,255,1) 2px,
            rgba(255,255,255,1) 10px
          );
        }

        h1, h2, h3 { letter-spacing: 0.3px; }

        .season-card {
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 16px;
          padding: 14px 14px 10px 14px;
          box-shadow: 0 6px 18px rgba(17,24,39,0.06);
          margin-bottom: 10px;
        }
        .season-meta {
          color: rgba(17,24,39,0.75);
          font-size: 0.9rem;
          margin-top: 4px;
        }
        .pill {
          display: inline-block;
          padding: 3px 10px;
          border-radius: 999px;
          border: 1px solid rgba(12,35,64,0.25);
          background: rgba(12,35,64,0.06);
          font-size: 0.78rem;
          margin-right: 6px;
          margin-top: 6px;
          white-space: nowrap;
        }
        .muted { color: rgba(17,24,39,0.70); }

        .kpi-card {
          background: rgba(255,255,255,0.92);
          border: 1px solid rgba(12,35,64,0.18);
          border-radius: 16px;
          padding: 12px 14px;
          box-shadow: 0 6px 18px rgba(17,24,39,0.06);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Data loading
# -----------------------------
@st.cache_data(show_spinner=False)
def load_lahman_teams(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)

    if "yearID" in df.columns:
        df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce").astype("Int64")

    # Normalize common postseason flag columns if present
    for col in ["DivWin", "WCWin", "LgWin", "WSWin"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    if "W" in df.columns and "L" in df.columns:
        denom = (pd.to_numeric(df["W"], errors="coerce") + pd.to_numeric(df["L"], errors="coerce"))
        df["win_pct"] = (pd.to_numeric(df["W"], errors="coerce") / denom).round(3)

    return df


def get_yankees_seasons(df: pd.DataFrame) -> pd.DataFrame:
    # MVP: Modern Yankees
    if "teamID" not in df.columns:
        return pd.DataFrame()

    yank = df[df["teamID"] == "NYA"].copy()
    if yank.empty:
        return yank

    yank = yank.dropna(subset=["yearID"]).sort_values("yearID", ascending=False)

    # Friendly columns
    def mk_record(r):
        w = r.get("W")
        l = r.get("L")
        try:
            if pd.notna(w) and pd.notna(l):
                return f"{int(w)}-{int(l)}"
        except Exception:
            pass
        return "—"

    yank["record"] = yank.apply(mk_record, axis=1)

    if "Rank" in yank.columns:
        yank["finish"] = yank["Rank"].apply(lambda x: f"Finish: #{int(x)}" if pd.notna(x) else "Finish: —")
    else:
        yank["finish"] = "Finish: —"

    def postseason_row(r):
        flags = []
        if r.get("WCWin", "") == "Y":
            flags.append("WC")
        if r.get("DivWin", "") == "Y":
            flags.append("DIV")
        if r.get("LgWin", "") == "Y":
            flags.append("AL")
        if r.get("WSWin", "") == "Y":
            flags.append("WS")
        return " · ".join(flags) if flags else "—"

    yank["postseason"] = yank.apply(postseason_row, axis=1)
    return yank


# -----------------------------
# Supabase helpers (optional)
# -----------------------------
def get_supabase_client():
    if not SUPABASE_ENABLED:
        return None
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "")).strip()
    key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", "")).strip()
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None


def ensure_user_id() -> str:
    # MVP identity; later we can add real auth
    if "user_id" not in st.session_state:
        st.session_state.user_id = "default_user"
    return st.session_state.user_id


def read_flags(sb, user_id: str) -> pd.DataFrame:
    if sb is None:
        return pd.DataFrame(columns=["year", "is_read", "is_favorite", "notes"])
    try:
        resp = sb.table("user_season_flags").select("*").eq("user_id", user_id).execute()
        rows = resp.data or []
        df = pd.DataFrame(rows)
        if not df.empty and "year" in df.columns:
            df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
        return df
    except Exception:
        return pd.DataFrame(columns=["year", "is_read", "is_favorite", "notes"])


def upsert_flag(sb, user_id: str, year: int, is_read: bool, is_favorite: bool, notes: str):
    if sb is None:
        return
    payload = {
        "user_id": user_id,
        "year": int(year),
        "is_read": bool(is_read),
        "is_favorite": bool(is_favorite),
        "notes": notes or "",
    }
    sb.table("user_season_flags").upsert(payload, on_conflict="user_id,year").execute()


# -----------------------------
# UI bits
# -----------------------------
def season_card(row: pd.Series, flags_row: dict | None):
    year = int(row["yearID"])
    record = row.get("record", "—")
    win_pct = row.get("win_pct", None)
    finish = row.get("finish", "Finish: —")
    postseason = row.get("postseason", "—")

    is_read = bool(flags_row.get("is_read")) if flags_row else False
    is_fav = bool(flags_row.get("is_favorite")) if flags_row else False

    pills = []
    if postseason != "—":
        pills.append(f"<span class='pill'>Postseason: {postseason}</span>")
    if row.get("WSWin", "") == "Y":
        pills.append("<span class='pill'>World Series Champs</span>")
    if is_fav:
        pills.append("<span class='pill'>★ Favorite</span>")
    if is_read:
        pills.append("<span class='pill'>✓ Read</span>")

    wp = f"{float(win_pct):.3f}" if pd.notna(win_pct) else "—"

    st.markdown(
        f"""
        <div class="season-card">
          <div style="display:flex; justify-content:space-between; align-items:baseline; gap:12px;">
            <div style="font-size:1.15rem; font-weight:800;">{year} Season</div>
            <div class="muted" style="font-size:0.95rem;">
              Record: <b>{record}</b> &nbsp;•&nbsp; Win%: <b>{wp}</b>
            </div>
          </div>
          <div class="season-meta">{finish}</div>
          <div style="margin-top:8px;">{''.join(pills) if pills else "<span class='muted'>No flags yet</span>"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str):
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="muted" style="font-size:0.85rem; margin-bottom:4px;">{label}</div>
          <div style="font-size:1.15rem; font-weight:800;">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Main app
# -----------------------------
def main():
    st.set_page_config(page_title="Yankees History Timeline", layout="wide")
    inject_css()

    st.title("Yankees History Timeline")
    st.caption("Seasons-first dashboard — explore seasons, flag favorites, and keep notes. (No logos; just a Yankees vibe.)")

    # Sidebar
    st.sidebar.header("Timeline Filters")

    # You placed Teams.csv at the ROOT of the GitHub repo:
    TEAMS_PATH = "Teams.csv"

    start_year = st.sidebar.slider("Start year", 1903, 2025, 1903)
    decade = st.sidebar.selectbox("Decade", ["All"] + [f"{d}s" for d in range(1900, 2030, 10)], index=0)
    postseason_only = st.sidebar.checkbox("Postseason seasons only", value=False)
    ws_titles_only = st.sidebar.checkbox("World Series titles only", value=False)

    # Load data
    try:
        teams = load_lahman_teams(TEAMS_PATH)
    except Exception as e:
        st.error(
            "Could not load **Teams.csv** from the repo root.\n\n"
            "✅ Fix: make sure `Teams.csv` is committed at the top level of your GitHub repo.\n\n"
            f"Error: {e}"
        )
        st.stop()

    yank = get_yankees_seasons(teams)
    if yank.empty:
        st.error("No Yankees seasons found. Check that your Lahman Teams.csv is valid and includes teamID = 'NYA'.")
        st.stop()

    yank = yank[yank["yearID"] >= start_year]

    if decade != "All":
        d0 = int(decade[:4])
        yank = yank[(yank["yearID"] >= d0) & (yank["yearID"] <= d0 + 9)]

    if postseason_only:
        def any_post(r):
            return (
                r.get("WCWin", "") == "Y"
                or r.get("DivWin", "") == "Y"
                or r.get("LgWin", "") == "Y"
                or r.get("WSWin", "") == "Y"
            )
        yank = yank[yank.apply(any_post, axis=1)]

    if ws_titles_only:
        yank = yank[yank.get("WSWin", "") == "Y"]

    yank = yank.sort_values("yearID", ascending=False)

    # Supabase
    sb = get_supabase_client()
    user_id = ensure_user_id()

    flags_df = read_flags(sb, user_id)
    flags_map: dict[int, dict] = {}
    if not flags_df.empty:
        for _, r in flags_df.iterrows():
            y = r.get("year")
            if pd.notna(y):
                flags_map[int(y)] = r.to_dict()

    # Top KPIs
    total_seasons = len(yank)
    total_ws = int((yank.get("WSWin", "") == "Y").sum()) if "WSWin" in yank.columns else 0
    total_post = int((yank["postseason"] != "—").sum())

    k1, k2, k3 = st.columns(3)
    with k1:
        kpi("Seasons in view", str(total_seasons))
    with k2:
        kpi("Postseason seasons", str(total_post))
    with k3:
        kpi("World Series titles (in view)", str(total_ws))

    st.markdown("")

    # Layout: left timeline, right details
    left, right = st.columns([1.2, 0.8], gap="large")

    with left:
        st.subheader("Timeline")
        years = yank["yearID"].astype(int).tolist()
        selected_year = st.selectbox("Pick a season", years, index=0)

        show_n = st.slider("How many seasons to show", 10, min(160, len(yank)), min(30, len(yank)))
        for _, row in yank.head(show_n).iterrows():
            y = int(row["yearID"])
            season_card(row, flags_map.get(y))

    with right:
        st.subheader("Season Details")

        sel = yank[yank["yearID"].astype(int) == int(selected_year)]
        if sel.empty:
            st.info("Select a season to see details.")
            return

        r = sel.iloc[0]
        year = int(r["yearID"])
        st.markdown(f"### {year}")

        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Record", r.get("record", "—"))
        with c2:
            st.metric("Win %", f"{float(r['win_pct']):.3f}" if pd.notna(r.get("win_pct")) else "—")
        with c3:
            st.metric("Postseason", r.get("postseason", "—"))

        # Snapshot (only show fields present)
        extras = []
        for label, col in [
            ("Finish", "finish"),
            ("Runs Scored", "R"),
            ("Runs Allowed", "RA"),
            ("HR", "HR"),
            ("Stolen Bases", "SB"),
            ("ERA", "ERA"),
            ("Attendance", "attendance"),
            ("Park", "park"),
            ("Team Name", "name"),
        ]:
            if col in r.index and pd.notna(r.get(col)):
                extras.append((label, r.get(col)))

        if extras:
            st.markdown("**Season snapshot**")
            for label, val in extras[:12]:
                st.write(f"- {label}: **{val}**")

        # Notes / flags
        st.markdown("---")
        st.markdown("**Your notes & flags**")

        existing = flags_map.get(year, {})
        default_read = bool(existing.get("is_read")) if existing else False
        default_fav = bool(existing.get("is_favorite")) if existing else False
        default_notes = existing.get("notes") if existing else ""

        is_read = st.checkbox("Mark as read", value=default_read)
        is_fav = st.checkbox("Favorite", value=default_fav)
        notes = st.text_area("Notes", value=default_notes, height=120, placeholder="What stands out about this season?")

        if sb is None:
            st.warning(
                "Supabase not configured yet (or secrets missing). "
                "Add `SUPABASE_URL` and `SUPABASE_KEY` in Streamlit Cloud → App settings → Secrets to persist flags."
            )
        else:
            if st.button("Save", use_container_width=True):
                try:
                    upsert_flag(sb, user_id, year, is_read, is_fav, notes)
                    st.success("Saved!")
                except Exception as e:
                    st.error(f"Save failed: {e}")

        st.markdown("---")
        with st.expander("Next upgrades (planned)"):
            st.write("- Era bands (Ruth/Gehrig, DiMaggio, Mantle, Core Four, etc.)")
            st.write("- Dynasty highlighting + ring counter across all seasons")
            st.write("- Curated story blurbs per season (short history-first narratives)")
            st.write("- Season of the Day (daily discovery)")

    # Footer
    st.sidebar.markdown("---")
    st.sidebar.caption("Data: Lahman Baseball Database (Teams.csv).")


if __name__ == "__main__":
    main()
