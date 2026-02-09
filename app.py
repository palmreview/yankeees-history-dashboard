import os
import pandas as pd
import streamlit as st

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
        </style>
        """,
        unsafe_allow_html=True,
    )


# -----------------------------
# Data loading
# -----------------------------
@st.cache_data(show_spinner=False)
def load_data(path: str):
    df = pd.read_csv(path)

    df["yearID"] = pd.to_numeric(df["yearID"], errors="coerce")

    for col in ["DivWin", "WCWin", "LgWin", "WSWin"]:
        if col in df.columns:
            df[col] = df[col].fillna("")

    if "W" in df.columns and "L" in df.columns:
        w = pd.to_numeric(df["W"], errors="coerce")
        l = pd.to_numeric(df["L"], errors="coerce")
        df["win_pct"] = (w / (w + l)).round(3)

    return df


def get_yankees(df):
    yank = df[df["teamID"] == "NYA"].copy()
    yank = yank.dropna(subset=["yearID"])
    yank = yank.sort_values("yearID", ascending=False)

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
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def read_flags(sb, user_id):
    if sb is None:
        return {}
    resp = sb.table("user_season_flags").select("*").eq("user_id", user_id).execute()
    data = resp.data or []
    return {int(r["year"]): r for r in data}


def save_flag(sb, user_id, year, read, fav, notes):
    if sb is None:
        return
    sb.table("user_season_flags").upsert(
        {
            "user_id": user_id,
            "year": int(year),
            "is_read": read,
            "is_favorite": fav,
            "notes": notes,
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

    # Load data
    try:
        df = load_data("Teams.csv")
    except Exception as e:
        st.error(f"Error loading Teams.csv: {e}")
        st.stop()

    yank = get_yankees(df)

    if yank.empty:
        st.error("No Yankees seasons found.")
        st.stop()

    # Sidebar filters
    years_all = yank["yearID"].astype(int).tolist()
    min_year, max_year = min(years_all), max(years_all)

    st.sidebar.header("Filters")
    start_year = st.sidebar.slider("Start year", min_year, max_year, min_year)

    decade_options = ["All"] + sorted(
        list({f"{(y//10)*10}s" for y in years_all})
    )
    decade = st.sidebar.selectbox("Decade", decade_options)

    postseason_only = st.sidebar.checkbox("Postseason only")
    ws_only = st.sidebar.checkbox("World Series titles only")

    # Apply filters
    filtered = yank[yank["yearID"] >= start_year]

    if decade != "All":
        d0 = int(decade[:4])
        filtered = filtered[
            (filtered["yearID"] >= d0) & (filtered["yearID"] <= d0 + 9)
        ]

    if postseason_only:
        filtered = filtered[filtered["postseason"] != "—"]

    if ws_only:
        filtered = filtered[filtered["WSWin"] == "Y"]

    filtered = filtered.sort_values("yearID", ascending=False)

    if filtered.empty:
        st.warning("No seasons match filters.")
        return

    sb = get_supabase()
    user_id = "default_user"
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

        # Safe slider
        n = len(filtered)
        if n <= 10:
            show_n = n
            st.caption(f"Showing all {n} seasons.")
        else:
            show_n = st.slider(
                "How many seasons to show",
                min_value=10,
                max_value=n,
                value=min(30, n),
            )

        for _, row in filtered.head(show_n).iterrows():
            year = int(row["yearID"])
            st.markdown(f"<div class='season-card'><b>{year}</b> — {row['record']} — {row['postseason']}</div>", unsafe_allow_html=True)

    with right:
        year = st.session_state.selected_year
        row = filtered[filtered["yearID"] == year].iloc[0]

        st.subheader(f"{year} Season")
        st.metric("Record", row["record"])
        st.metric("Win %", row.get("win_pct", "—"))
        st.metric("Postseason", row["postseason"])

        existing = flags.get(year, {})
        read = st.checkbox("Read", value=existing.get("is_read", False))
        fav = st.checkbox("Favorite", value=existing.get("is_favorite", False))
        notes = st.text_area("Notes", value=existing.get("notes", ""))

        if st.button("Save"):
            save_flag(sb, user_id, year, read, fav, notes)
            st.success("Saved!")

    st.sidebar.caption("Data: Lahman Teams.csv")


if __name__ == "__main__":
    main()
