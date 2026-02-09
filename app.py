import os
import pandas as pd
import streamlit as st

# Optional Supabase (safe import pattern)
SUPABASE_ENABLED = False
try:
    from supabase import create_client
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
        /* Subtle pinstripe background on main content */
        .stApp {
          background-image: repeating-linear-gradient(
            90deg,
            rgba(12,35,64,0.03),
            rgba(12,35,64,0.03) 2px,
            rgba(255,255,255,1) 2px,
            rgba(255,255,255,1) 10px
          );
        }

        /* Make headers feel bold/clean */
        h1, h2, h3 {
          letter-spacing: 0.3px;
        }

        /* "Card" look for season tiles */
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
        }
        .muted {
          color: rgba(17,24,39,0.70);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Data loading (Lahman Teams)
# -----------------------------
@st.cache_data(show_spinner=False)
def load_lahman_teams(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    # Lahman Teams table fields vary slightly by version; handle gracefully
    # Common fields: yearID, teamID, franchID, lgID, divID, Rank, W, L, G,
    # R, RA, HR, SB, SOA, ERA, attendance, name, park, DP, FP, etc.
    # We’ll compute a few nice-to-have fields:
    if "yearID" in df.columns:
        df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce").astype("Int64")

    if "W" in df.columns and "L" in df.columns:
        df["win_pct"] = (df["W"] / (df["W"] + df["L"])).round(3)

    # Postseason flags often exist: DivWin, WCWin, LgWin, WSWin (Y/N)
    for col in ["DivWin", "WCWin", "LgWin", "WSWin"]:
        if col in df.columns:
            df[col] = df[col].fillna("").astype(str)

    return df


def get_yankees_seasons(df: pd.DataFrame) -> pd.DataFrame:
    # Modern Yankees are teamID == "NYA"
    # (MVP scope: 1903+; we can expand earlier franchise history later)
    yank = df[df.get("teamID", "") == "NYA"].copy()
    yank = yank.dropna(subset=["yearID"]).sort_values("yearID", ascending=False)

    # Friendly labels
    yank["record"] = yank.apply(
        lambda r: f"{int(r['W'])}-{int(r['L'])}" if pd.notna(r.get("W")) and pd.notna(r.get("L")) else "—",
        axis=1,
    )
    if "Rank" in yank.columns:
        yank["finish"] = yank["Rank"].apply(lambda x: f"Finish: #{int(x)}" if pd.notna(x) else "Finish: —")
    else:
        yank["finish"] = "Finish: —"

    # Simple postseason summary
    def postseason_row(r):
        flags = []
        if r.get("WCWin", "") == "Y": flags.append("WC")
        if r.get("DivWin", "") == "Y": flags.append("DIV")
        if r.get("LgWin", "") == "Y": flags.append("AL")
        if r.get("WSWin", "") == "Y": flags.append("WS")
        return " · ".join(flags) if flags else "—"

    yank["postseason"] = yank.apply(postseason_row, axis=1)

    return yank


# -----------------------------
# Supabase (optional MVP hooks)
# -----------------------------
def get_supabase_client():
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_KEY", os.getenv("SUPABASE_KEY", ""))
    if not url or not key or not SUPABASE_ENABLED:
        return None
    return create_client(url, key)


def ensure_user_id():
    # Simple local identity for MVP (later: auth, device id, etc.)
    if "user_id" not in st.session_state:
        st.session_state.user_id = "default_user"
    return st.session_state.user_id


def read_flags(sb, user_id: str) -> pd.DataFrame:
    # Table: user_season_flags(user_id text, year int, is_read bool, is_favorite bool, notes text)
    if sb is None:
        return pd.DataFrame(columns=["year", "is_read", "is_favorite", "notes"])

    resp = sb.table("user_season_flags").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    df = pd.DataFrame(rows)
    if not df.empty and "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    return df


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
# UI
# -----------------------------
def season_card(row, flags_row: dict | None):
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

    wp = f"{win_pct:.3f}" if pd.notna(win_pct) else "—"

    st.markdown(
        f"""
        <div class="season-card">
          <div style="display:flex; justify-content:space-between; align-items:baseline;">
            <div style="font-size:1.15rem; font-weight:700;">{year} Season</div>
            <div class="muted" style="font-size:0.95rem;">Record: <b>{record}</b> &nbsp;•&nbsp; Win%: <b>{wp}</b></div>
          </div>
          <div class="season-meta">{finish}</div>
          <div style="margin-top:8px;">{''.join(pills) if pills else "<span class='muted'>No flags yet</span>"}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title="Yankees History Timeline", layout="wide")
    inject_css()

    st.title("Yankees History Timeline")
    st.caption("Seasons-first dashboard — explore, favorite, and keep notes. (No logos; just Yankees vibe.)")

    # Sidebar controls
    st.sidebar.header("Filters")
    start_year = st.sidebar.slider("Start year", 1903, 2025, 1903)
    decade = st.sidebar.selectbox("Decade", ["All"] + [f"{d}s" for d in range(1900, 2030, 10)], index=0)
    postseason_only = st.sidebar.checkbox("Postseason seasons only", value=False)
    ws_titles_only = st.sidebar.checkbox("World Series titles only", value=False)

    # Load data
    teams_path = st.sidebar.text_input("Lahman Teams.csv path", "data/lahman/Teams.csv")
    try:
        teams = load_lahman_teams(teams_path)
    except Exception as e:
        st.error(f"Could not load Teams.csv from: {teams_path}\n\n{e}")
        st.stop()

    yank = get_yankees_seasons(teams)
    yank = yank[yank["yearID"] >= start_year]

    if decade != "All":
        d0 = int(decade[:4])
        yank = yank[(yank["yearID"] >= d0) & (yank["yearID"] <= d0 + 9)]

    if postseason_only:
        # any of the postseason flags
        def any_post(r):
            return (r.get("WCWin", "") == "Y" or r.get("DivWin", "") == "Y" or r.get("LgWin", "") == "Y" or r.get("WSWin", "") == "Y")
        yank = yank[yank.apply(any_post, axis=1)]

    if ws_titles_only:
        yank = yank[yank.get("WSWin", "") == "Y"]

    # Supabase setup
    sb = get_supabase_client()
    user_id = ensure_user_id()
    flags_df = read_flags(sb, user_id)
    flags_map = {}
    if not flags_df.empty:
        flags_map = {int(r["year"]): r for _, r in flags_df.iterrows() if pd.notna(r.get("year"))}

    # Layout: left timeline, right details
    left, right = st.columns([1.15, 0.85], gap="large")

    with left:
        st.subheader("Timeline")
        st.write(f"Showing **{len(yank)}** seasons.")

        # Select a season
        years = yank["yearID"].astype(int).tolist()
        selected_year = st.selectbox("Pick a season", years, index=0)

        # Render cards (most recent first)
        # Keep it efficient: show first ~30 by default, with option to expand
        show_n = st.slider("How many seasons to show in timeline", 10, min(150, len(yank)), min(30, len(yank)))
        for _, row in yank.head(show_n).iterrows():
            season_year = int(row["yearID"])
            season_card(row, flags_map.get(season_year))

    with right:
        st.subheader("Season Details")

        sel = yank[yank["yearID"].astype(int) == int(selected_year)]
        if sel.empty:
            st.info("Select a season to see details.")
        else:
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

            # A few extra fields if present
            extras = []
            for label, col in [
                ("Runs Scored", "R"),
                ("Runs Allowed", "RA"),
                ("HR", "HR"),
                ("Stolen Bases", "SB"),
                ("ERA", "ERA"),
                ("Attendance", "attendance"),
                ("Park", "park"),
                ("Team Name", "name"),
            ]:
                if col in yank.columns and pd.notna(r.get(col)):
                    extras.append((label, r.get(col)))

            if extras:
                st.markdown("**Season snapshot**")
                for label, val in extras[:10]:
                    st.write(f"- {label}: **{val}**")

            # Flags + notes
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
                st.warning("Supabase not configured (or supabase lib not installed). Flags/notes will not persist yet.")
            else:
                if st.button("Save", use_container_width=True):
                    upsert_flag(sb, user_id, year, is_read, is_fav, notes)
                    st.success("Saved!")

            st.markdown("---")
            st.markdown("**Next (coming soon)**")
            st.write("- Manager + roster highlights")
            st.write("- Curated story snippets (dynasties, turning points, iconic moments)")
            st.write("- ‘On this season’ daily rotation")


if __name__ == "__main__":
    main()
