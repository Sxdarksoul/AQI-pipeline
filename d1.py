import sqlite3
import requests
import pandas as pd
from datetime import datetime, timedelta
import os

# ---- relative paths so it works locally AND on GitHub Actions ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "air.db")

# Token: env var (GitHub Secret) se uthata; nahi mile to local fallback
WAQI_TOKEN = os.environ.get("WAQI_TOKEN", "4a3acaf2c59eb9397d3cedccc086e112d4b88ff4")

MAX_AGE_HOURS = 3

CITIES = [
    {"name": "New Delhi",          "state": "Delhi",            "lat": 28.6139, "lon": 77.2090},
    {"name": "Gurugram",           "state": "Haryana",          "lat": 28.4595, "lon": 77.0266},
    {"name": "Noida",              "state": "Uttar Pradesh",    "lat": 28.5355, "lon": 77.3910},
    {"name": "Lucknow",            "state": "Uttar Pradesh",    "lat": 26.8467, "lon": 80.9462},
    {"name": "Kanpur",             "state": "Uttar Pradesh",    "lat": 26.4499, "lon": 80.3319},
    {"name": "Patna",              "state": "Bihar",            "lat": 25.5941, "lon": 85.1376},
    {"name": "Varanasi",           "state": "Uttar Pradesh",    "lat": 25.3176, "lon": 82.9739},
    {"name": "Agra",               "state": "Uttar Pradesh",    "lat": 27.1767, "lon": 78.0081},
    {"name": "Chandigarh",         "state": "Chandigarh",       "lat": 30.7333, "lon": 76.7794},
    {"name": "Jaipur",             "state": "Rajasthan",        "lat": 26.9124, "lon": 75.7873},
    {"name": "Mumbai",             "state": "Maharashtra",      "lat": 19.0760, "lon": 72.8777},
    {"name": "Ahmedabad",          "state": "Gujarat",          "lat": 23.0225, "lon": 72.5714},
    {"name": "Pune",               "state": "Maharashtra",      "lat": 18.5204, "lon": 73.8567},
    {"name": "Surat",              "state": "Gujarat",          "lat": 21.1702, "lon": 72.8311},
    {"name": "Indore",             "state": "Madhya Pradesh",   "lat": 22.7196, "lon": 75.8577},
    {"name": "Nagpur",             "state": "Maharashtra",      "lat": 21.1458, "lon": 79.0882},
    {"name": "Bhopal",             "state": "Madhya Pradesh",   "lat": 23.2599, "lon": 77.4126},
    {"name": "Bengaluru",          "state": "Karnataka",        "lat": 12.9716, "lon": 77.5946},
    {"name": "Hyderabad",          "state": "Telangana",        "lat": 17.3850, "lon": 78.4867},
    {"name": "Chennai",            "state": "Tamil Nadu",       "lat": 13.0827, "lon": 80.2707},
    {"name": "Visakhapatnam",      "state": "Andhra Pradesh",   "lat": 17.6868, "lon": 83.2185},
    {"name": "Dehradun",           "state": "Uttarakhand",      "lat": 30.3165, "lon": 78.0322},
    {"name": "Coimbatore",         "state": "Tamil Nadu",       "lat": 11.0168, "lon": 76.9558},
    {"name": "Thiruvananthapuram", "state": "Kerala",           "lat": 8.5241,  "lon": 76.9366},
    {"name": "Kolkata",            "state": "West Bengal",      "lat": 22.5726, "lon": 88.3639},
    {"name": "Ranchi",             "state": "Jharkhand",        "lat": 23.3441, "lon": 85.3096},
    {"name": "Bhubaneswar",        "state": "Odisha",           "lat": 20.2961, "lon": 85.8245},
    {"name": "Guwahati",           "state": "Assam",            "lat": 26.1445, "lon": 91.7362},
    {"name": "Shimla",             "state": "Himachal Pradesh", "lat": 31.1048, "lon": 77.1734},
    {"name": "Ooty",               "state": "Tamil Nadu",       "lat": 11.4102, "lon": 76.6950},
]


def aqi_tier(a):
    if pd.isna(a):
        return "No Data"
    if a <= 50:   return "Good"
    if a <= 100:  return "Satisfactory"
    if a <= 200:  return "Moderate"
    if a <= 300:  return "Poor"
    if a <= 400:  return "Very Poor"
    return "Severe"


def init_database():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS aqi_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT,
            state TEXT,
            station TEXT,
            latitude REAL,
            longitude REAL,
            aqi REAL,
            pm25 REAL, pm10 REAL, no2 REAL, o3 REAL, co REAL, so2 REAL,
            last_update TEXT,
            fetched_at TEXT,
            UNIQUE(city, last_update)
        )
    ''')
    conn.commit()
    conn.close()
    print("DB history table ready.")


def _pick_station(results, city_name, state_name):
    if not results:
        return None
    india = [r for r in results
             if "india" in r.get("station", {}).get("name", "").lower()]
    if not india:
        return None
    cl = city_name.lower()
    sl = state_name.lower()
    for r in india:
        if cl in r.get("station", {}).get("name", "").lower():
            return r
    for r in india:
        if sl in r.get("station", {}).get("name", "").lower():
            return r
    return india[0]


def _parse_feed(d, city):
    aqi = d.get("aqi")
    try:
        aqi = float(aqi)
    except (TypeError, ValueError):
        return None

    ts = d.get("time", {}).get("s", "")
    try:
        t = pd.to_datetime(ts)
        if pd.notna(t) and (datetime.now() - t.to_pydatetime()) > timedelta(hours=MAX_AGE_HOURS):
            return None
    except Exception:
        pass

    iaqi = d.get("iaqi", {})
    def g(k):
        v = iaqi.get(k, {}).get("v")
        try: return float(v)
        except: return None
    return {
        "station": d.get("city", {}).get("name", city["name"]),
        "ts": ts,
        "aqi": aqi,
        "pm25": g("pm25"), "pm10": g("pm10"), "no2": g("no2"),
        "o3": g("o3"), "co": g("co"), "so2": g("so2"),
    }


def fetch_live_data():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    inserted = 0
    fetched_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"\n[{fetched_at}] WAQI fetch for {len(CITIES)} cities...")

    session = requests.Session()

    for c in CITIES:
        rec = None

        try:
            sr = session.get("https://api.waqi.info/search/",
                             params={"keyword": c["name"], "token": WAQI_TOKEN},
                             timeout=20).json()
            if sr.get("status") == "ok":
                best = _pick_station(sr.get("data", []), c["name"], c["state"])
                if best and best.get("uid") is not None:
                    fr = session.get(f"https://api.waqi.info/feed/@{best['uid']}/",
                                     params={"token": WAQI_TOKEN}, timeout=20).json()
                    if fr.get("status") == "ok":
                        rec = _parse_feed(fr["data"], c)
        except Exception as e:
            print(f"  {c['name']}: search error {e}")

        if rec is None:
            try:
                gr = session.get(f"https://api.waqi.info/feed/geo:{c['lat']};{c['lon']}/",
                                 params={"token": WAQI_TOKEN}, timeout=20).json()
                if gr.get("status") == "ok":
                    rec = _parse_feed(gr["data"], c)
            except Exception as e:
                print(f"  {c['name']}: geo error {e}")

        if rec is None:
            print(f"  {c['name']}: no usable station, skip")
            continue

        cur.execute('''
            INSERT OR IGNORE INTO aqi_history
            (city, state, station, latitude, longitude, aqi,
             pm25, pm10, no2, o3, co, so2, last_update, fetched_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ''', (c["name"], c["state"], rec["station"], c["lat"], c["lon"], rec["aqi"],
              rec["pm25"], rec["pm10"], rec["no2"], rec["o3"], rec["co"], rec["so2"],
              rec["ts"], fetched_at))
        if cur.rowcount > 0:
            inserted += 1

    cur.execute("CREATE TABLE IF NOT EXISTS pipeline_meta (k TEXT PRIMARY KEY, v TEXT)")
    cur.execute("INSERT OR REPLACE INTO pipeline_meta (k, v) VALUES ('last_fetch', ?)",
                (fetched_at,))

    conn.commit()
    conn.close()
    print(f"Inserted {inserted} new readings (skipped duplicates).")


def transform_and_load_reporting():
    conn = sqlite3.connect(DB_NAME)
    hist = pd.read_sql_query("SELECT * FROM aqi_history;", conn)
    if hist.empty:
        conn.close()
        print("No history data to transform.")
        return

    hist["HEALTH_RISK_TIER"] = hist["aqi"].apply(aqi_tier)

    # full history (trends)
    hist.to_csv(os.path.join(BASE_DIR, "aqi_history.csv"), index=False)

    # latest snapshot (newest per city)
    latest = (hist.sort_values("last_update")
                  .groupby("city", as_index=False).last())
    latest_cols = ["city", "state", "station", "latitude", "longitude",
                   "aqi", "pm25", "pm10", "no2", "o3", "co", "so2",
                   "HEALTH_RISK_TIER", "last_update", "fetched_at"]
    latest = latest[[col for col in latest_cols if col in latest.columns]].copy()
    latest.rename(columns={"aqi": "CITY_AQI"}, inplace=True)
    latest.to_sql("reporting_air_quality", conn, if_exists="replace", index=False)
    latest.to_csv(os.path.join(BASE_DIR, "aqi_latest.csv"), index=False)

    # state rollup
    state_df = (latest.groupby("state", as_index=False)
                      .agg(STATE_AQI=("CITY_AQI", "max"),
                           cities=("city", "count")))
    state_df["HEALTH_RISK_TIER"] = state_df["STATE_AQI"].apply(aqi_tier)
    state_df.to_sql("reporting_state_aqi", conn, if_exists="replace", index=False)
    state_df.to_csv(os.path.join(BASE_DIR, "aqi_state.csv"), index=False)

    conn.close()
    print(f"Rollup done -> history rows: {len(hist)}, latest cities: {len(latest)}, states: {len(state_df)}. CSV written.")


if __name__ == "__main__":
    print("=====================================================")
    print(" AQI PIPELINE - single run (scheduler/Actions chalata)")
    print("=====================================================")
    init_database()
    fetch_live_data()
    transform_and_load_reporting()
    print("Done.")