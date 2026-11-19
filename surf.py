"""
Surf Central Coast — surf forecasts from Ventura to San Luis Obispo.

Fetches swell at each spot (CDIP MOP model), tides (NOAA), weather, wind and
water temperature (Open-Meteo) and offshore buoys (NDBC), scores every spot
hour by hour and writes web/data.js for the page.

Usage:  python surf.py
No library to install (Python 3.9+).
"""
import csv
import io
import json
import math
import socket
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "config" / "spots.json"
MOP_CACHE = ROOT / "config" / "mop_points.csv"
OUT = ROOT / "web" / "data.js"

TZ_NAME = "America/Los_Angeles"
BIAS = 1.2   # the MOP model underestimates by ~20% in the Santa Barbara Channel (UCSB study at Campus Point)
DAYS = 3     # days shown
M2FT = 3.281

# Every CDIP MOP point in California (ID, back-beach and model positions, shore normal)
MOP_LIST_URL = "https://zenodo.org/records/6946105/files/CDIP_Transects.csv?download=1"
MOP_URL = "https://thredds.cdip.ucsd.edu/thredds/dodsC/cdip/model/MOP_alongshore/{}_forecast.nc.ascii?waveTime,waveHs,waveTp,waveDp"

TIDE_STATIONS = {  # NOAA
    "9411340": {"name": "Santa Barbara", "lat": 34.408, "lon": -119.685},
    "9412110": {"name": "Port San Luis", "lat": 35.169, "lon": -120.754},
}
BUOYS = {  # NDBC
    "46053": {"name": "East Santa Barbara", "lat": 34.241, "lon": -119.839},
    "46054": {"name": "West Santa Barbara", "lat": 34.265, "lon": -120.477},
    "46011": {"name": "Santa Maria", "lat": 34.956, "lon": -121.019},
}

try:
    from zoneinfo import ZoneInfo
    TZ = ZoneInfo(TZ_NAME)
except Exception:  # Windows without the tz database: use the offset given by Open-Meteo
    TZ = None


# ----------------------------------------------------------------- network
def short_error(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"the site returned error {e.code}"
    if isinstance(e, (socket.timeout, TimeoutError)) or "timed out" in str(e):
        return "the site took too long to answer"
    if isinstance(e, urllib.error.URLError):
        return "could not connect (internet or site down)"
    return str(e)[:120]


def get(url, timeout=25, tries=2):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "surf-central-coast/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                break
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1 + i)
    raise RuntimeError(short_error(last))


# ----------------------------------------------------------------- geo helpers
def dist_km(lat1, lon1, lat2, lon2):
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return 6371 * math.hypot(x, y)


def nearest_key(table, lat, lon):
    return min(table, key=lambda k: dist_km(lat, lon, table[k]["lat"], table[k]["lon"]))


def load_mop_points():
    """CDIP site list, downloaded once and cached in config/mop_points.csv."""
    if not MOP_CACHE.exists():
        print("Downloading the list of CDIP model points (first run only)…")
        text = get(MOP_LIST_URL, timeout=90, tries=3)
        MOP_CACHE.write_text(text, encoding="utf-8")
    pts = {}
    for row in csv.DictReader(io.StringIO(MOP_CACHE.read_text(encoding="utf-8"))):
        try:
            pts[row["ID"]] = {"id": row["ID"], "lat": float(row["Lat_BackBeach"]), "lon": float(row["Lon_BackBeach"]),
                              "normal": float(row["ShoreNormal"]), "flag": row.get("Flag", "1")}
        except (KeyError, ValueError):
            continue
    return pts


def neighbors(mop_id, n=3):
    """B0418 -> [B0417, B0419, B0416, B0420, ...] (same number width)."""
    prefix = mop_id.rstrip("0123456789")
    digits = mop_id[len(prefix):]
    v, w = int(digits), len(digits)
    out = []
    for d in range(1, n + 1):
        for s in (-d, d):
            if v + s > 0:
                out.append(f"{prefix}{v + s:0{w}d}")
    return out


def resolve_spots(spots):
    """Picks the CDIP point, shore orientation, tide station and buoy of each spot."""
    try:
        pts = load_mop_points()
    except Exception as e:  # noqa: BLE001
        print(f"  FAILED  CDIP point list -> {e}")
        pts = {}
    for s in spots:
        p = pts.get(s.get("mop", "")) if s.get("mop") else None
        if p is None and pts and "lat" in s:
            cands = [q for q in pts.values() if abs(q["lat"] - s["lat"]) < 0.1 and abs(q["lon"] - s["lon"]) < 0.12] or list(pts.values())
            p = min(cands, key=lambda q: dist_km(s["lat"], s["lon"], q["lat"], q["lon"]))
        if p:
            s.setdefault("mop", p["id"])
            if s.get("mop") == p["id"]:
                s.setdefault("normal", round(p["normal"]))
                s["mopDist"] = round(dist_km(s["lat"], s["lon"], p["lat"], p["lon"]), 2)
        s.setdefault("normal", 225)
        s["station"] = nearest_key(TIDE_STATIONS, s["lat"], s["lon"])
        s["buoy"] = nearest_key(BUOYS, s["lat"], s["lon"])
    return spots


def fetch_all(spots):
    """Downloads every source. One source down never blocks the others."""
    tz_day = (datetime.now(timezone.utc) - timedelta(hours=8, days=1)).strftime("%Y%m%d")

    def noaa(station, interval):
        return ("https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=predictions&application=surf_central_coast"
                f"&station={station}&datum=MLLW&units=english&time_zone=gmt&format=json&range=120&begin_date={tz_day}&interval={interval}")
    lats = ",".join(f"{s['lat']:.3f}" for s in spots)
    lons = ",".join(f"{s['lon']:.3f}" for s in spots)
    jobs = {
        "met": ("https://api.open-meteo.com/v1/forecast?"
                f"latitude={lats}&longitude={lons}"
                "&hourly=temperature_2m,weather_code,cloud_cover,precipitation_probability,is_day,"
                "wind_speed_10m,wind_direction_10m,wind_gusts_10m&daily=sunrise,sunset"
                "&wind_speed_unit=mph&timezone=America%2FLos_Angeles&timeformat=unixtime&past_days=1&forecast_days=4"),
        "marine": ("https://marine-api.open-meteo.com/v1/marine?"
                   f"latitude={lats}&longitude={lons}&hourly=sea_surface_temperature"
                   "&timezone=America%2FLos_Angeles&timeformat=unixtime&past_days=1&forecast_days=4"),
    }
    for st in TIDE_STATIONS:
        jobs[f"tides:{st}"] = noaa(st, "h")
        jobs[f"hilo:{st}"] = noaa(st, "hilo")
    for b in BUOYS:
        jobs[f"buoy:{b}"] = f"https://www.ndbc.noaa.gov/data/realtime2/{b}.txt"

    raw, errors = {}, {}

    def run_job(item):
        name, url = item
        try:
            text = get(url)
            raw[name] = text if name.startswith("buoy:") else json.loads(text)
            print(f"  ok      {name}")
        except Exception as e:  # noqa: BLE001
            errors[name] = str(e)
            print(f"  FAILED  {name} -> {e}")

    def run_spot(s):
        name = "cdip:" + s["key"]
        if not s.get("mop"):
            errors[name] = "no CDIP model point found for this spot"
            print(f"  FAILED  {name} -> no point")
            return
        tried = [s["mop"]] + neighbors(s["mop"])
        last = None
        for mid in tried:
            try:
                raw[name] = get(MOP_URL.format(mid), tries=2 if mid == s["mop"] else 1)
                if mid != s["mop"]:
                    s["mopUsed"] = mid
                print(f"  ok      {name} ({mid})")
                return
            except Exception as e:  # noqa: BLE001
                last = e
                if "connect" in str(e) or "too long" in str(e):
                    break  # network problem, neighbours won't help
        errors[name] = str(last)
        print(f"  FAILED  {name} -> {last}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(run_job, jobs.items()))
        list(ex.map(run_spot, spots))
    raw["_errors"] = errors
    return raw


# ----------------------------------------------------------------- helpers
def r1(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return math.floor(v * 10 + 0.5) / 10


def rnd(v):
    return None if v is None else int(math.floor(v + 0.5))


def clamp(v, a, b):
    return max(a, min(b, v))


def ang_diff(a, b):
    d = abs(((a - b) % 360 + 360) % 360)
    return 360 - d if d > 180 else d


def parse_opendap(text, names):
    """OPeNDAP text answer (.ascii) -> {name: [values]}"""
    lines = text.split("-" * 10)[-1].split("\n")
    out = {}
    for n in names:
        vals = []
        for i, l in enumerate(lines):
            if l.startswith(n + "["):
                for l2 in lines[i + 1:]:
                    if not l2.strip():
                        break
                    vals += [float(v) for v in l2.replace(",", " ").split()]
                break
        out[n] = vals
    return out


def interp(series, t):
    if not series:
        return None
    if t <= series[0][0]:
        return series[0][1]
    for i in range(1, len(series)):
        if t <= series[i][0]:
            (t0, a), (t1, b) = series[i - 1], series[i]
            if a is None or b is None:
                return a if a is not None else b
            return a + (b - a) * (t - t0) / (t1 - t0)
    return series[-1][1]


def nearest(arr, t, key=lambda x: x["t"]):
    return min(arr, key=lambda x: abs(key(x) - t)) if arr else None


def as_list(x, n):
    """Open-Meteo returns an object for 1 location and a list for several."""
    if isinstance(x, list):
        return x
    return [x] * n if x else [{}] * n


def parse_buoy(text):
    if not text:
        return None
    lines = text.split("\n")
    head = lines[0].replace("#", "").split()
    for l in lines[2:]:
        row = dict(zip(head, l.split()))
        if row.get("WVHT") and row["WVHT"] != "MM":
            num = lambda k: None if row.get(k) in (None, "MM") else float(row[k])  # noqa: E731
            out = {"t": datetime(int(row["YY"]), int(row["MM"]), int(row["DD"]), int(row["hh"]), int(row["mm"]), tzinfo=timezone.utc).timestamp() * 1000,
                   "ft": r1(float(row["WVHT"]) * M2FT), "period": num("DPD"), "dir": num("MWD"),
                   "water": r1(num("WTMP")) if num("WTMP") is not None else None}
            for k in ("period", "dir"):
                if out[k] is not None and out[k] == int(out[k]):
                    out[k] = int(out[k])
            return out
    return None


# ----------------------------------------------------------------- rules
def size_score(ft, size):
    mn, lo, hi, mx = size
    if ft < mn:
        return 0
    if ft < lo:
        return 4 * (ft - mn) / (lo - mn)
    if ft <= hi:
        return 4
    if ft <= mx:
        return 4 - 2 * (ft - hi) / (mx - hi)
    return 1


def period_score(tp):
    if tp is None:
        return 0
    return 2 if tp >= 14 else 1.5 if tp >= 11 else 1 if tp >= 8 else 0


def tide_score(v, win):
    mn, mx = win
    if v is None:
        return 1
    if mn <= v <= mx:
        return 2
    d = mn - v if v < mn else v - mx
    return 1 if d <= 0.7 else 0


WIND_FACTOR = {"offshore": 1, "side-off": 0.5, "sideshore": 0, "side-on": -0.5, "onshore": -1}


def wind_info(w, normal):
    """Wind direction relative to the beach (normal = direction the beach faces)."""
    if not w or w.get("dir") is None:
        return {"type": "?", "angle": None, "score": 1, "factor": 0}
    angle = rnd(ang_diff(w["dir"], (normal + 180) % 360))  # 0 = straight offshore, 180 = straight onshore
    typ = ("offshore" if angle < 30 else "side-off" if angle < 70 else "sideshore" if angle <= 110
           else "side-on" if angle <= 150 else "onshore")
    f, sp = WIND_FACTOR[typ], w["speed"]
    if sp < 4:
        score = 2
    elif f == 1:  # straight offshore: holds up the faces until it gets really strong
        score = 2 if sp < 12 else 1.5 if sp < 18 else 0.8 if sp < 25 else 0.3
    elif f > 0:  # side-off: the cross component starts to texture the face sooner
        score = 2 if sp < 8 else 1.5 if sp < 12 else 0.8 if sp < 16 else 0.3
    elif f == 0:
        score = 1.2 if sp < 8 else 0.5 if sp < 14 else 0
    else:
        score = 0.9 if sp < 6 else 0.4 if sp < 10 else 0
    return {"type": typ, "angle": angle, "score": score, "factor": f}


def surface(w, wi):
    if not w:
        return "?"
    sp = w["speed"]
    if sp < 4:
        return "glassy"
    if wi["factor"] == 1:
        return "clean" if sp < 18 else "strong offshore"
    if wi["factor"] > 0:
        return "clean" if sp < 10 else "light texture" if sp < 16 else "choppy"
    if wi["factor"] == 0:
        return "light texture" if sp < 8 else "choppy"
    return "bumpy" if sp < 8 else "blown out"


def shape(tp, wi, wspeed, tide, win):
    """Hollow ↔ mushy: period, wind, tide vs. the spot's window."""
    tmn, tmx = win
    tp_f = 0 if tp is None else clamp((tp - 8) / 8, 0, 1)
    wind_f = 0.3 if wspeed < 4 else wi["factor"] * (0.6 if wspeed > 20 and wi["factor"] > 0 else 1)
    mid, half = (tmn + tmx) / 2, max(0.5, (tmx - tmn) / 2)
    tide_f = 0 if tide is None else clamp((mid - tide) / half, -1.2, 1.2)
    v = 1.4 * (tp_f - 0.4) + 0.8 * wind_f + 0.6 * tide_f
    label = "hollow" if v > 0.9 else "well shaped" if v > 0.3 else "a bit soft" if v > -0.3 else "mushy"
    return {"v": r1(v), "label": label}


# ----------------------------------------------------------------- analysis
def compute(raw, spots, now_ms=None):
    now = now_ms if now_ms is not None else time.time() * 1000
    errors = raw.get("_errors", {})
    n = len(spots)
    mets = as_list(raw.get("met"), n)
    marines = as_list(raw.get("marine"), n)
    offset = (mets[0] or {}).get("utc_offset_seconds", -8 * 3600)

    def to_local(ms):
        dt = datetime.fromtimestamp(ms / 1000, timezone.utc)
        return dt.astimezone(TZ) if TZ else dt + timedelta(seconds=offset)
    local_date = lambda ms: to_local(ms).strftime("%Y-%m-%d")  # noqa: E731
    local_hour = lambda ms: to_local(ms).hour  # noqa: E731
    ts = lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000  # noqa: E731

    tides = {st: [(ts(p["t"]), float(p["v"])) for p in (raw.get(f"tides:{st}") or {}).get("predictions", [])] for st in TIDE_STATIONS}
    hilos = {st: [{"t": ts(p["t"]), "v": float(p["v"]), "type": p["type"]} for p in (raw.get(f"hilo:{st}") or {}).get("predictions", [])] for st in TIDE_STATIONS}
    buoys = {b: parse_buoy(raw.get(f"buoy:{b}")) for b in BUOYS}

    def weather_of(met):
        H = met.get("hourly", {}) if met else {}
        g = lambda k, i: (H.get(k) or [None] * (i + 1))[i]  # noqa: E731
        w = [{"t": t * 1000, "speed": g("wind_speed_10m", i), "dir": g("wind_direction_10m", i), "gust": g("wind_gusts_10m", i),
              "air": g("temperature_2m", i), "code": g("weather_code", i), "rain": g("precipitation_probability", i), "isDay": g("is_day", i)}
             for i, t in enumerate(H.get("time", []))]
        return [x for x in w if x["speed"] is not None]

    def sun_of(met):
        D_ = (met or {}).get("daily", {})
        return [{"date": local_date(t * 1000 + 12 * 3600e3), "rise": D_["sunrise"][i] * 1000, "set": D_["sunset"][i] * 1000}
                for i, t in enumerate(D_.get("time", []))]

    def sst_of(mar):
        M = (mar or {}).get("hourly", {})
        return [(t * 1000, v) for t, v in zip(M.get("time", []), M.get("sea_surface_temperature", [])) if v is not None]

    start = math.floor(now / 3600e3) * 3600e3
    hours_list = [start + i * 3600e3 for i in range(DAYS * 24 + 6)]
    day_keys = []
    for t in hours_list:
        d = local_date(t)
        if d not in day_keys:
            day_keys.append(d)
    day_keys = day_keys[:DAYS]

    result = []
    for idx, s in enumerate(spots):
        weather, sun, sst = weather_of(mets[idx]), sun_of(mets[idx]), sst_of(marines[idx])
        tide_series = tides.get(s["station"], [])
        base = {**s, "water": r1(interp(sst, now))}

        def daylight(t, sun=sun):
            d = next((x for x in sun if x["date"] == local_date(t)), None)
            if d:
                return d["rise"] - 30 * 60e3 <= t <= d["set"]
            return 6 <= local_hour(t) <= 17

        text = raw.get("cdip:" + s["key"])
        p = parse_opendap(text, ["waveTime", "waveHs", "waveTp", "waveDp"]) if text else {}
        if not (p.get("waveTime") and p.get("waveHs")):
            err = "CDIP forecast unavailable: " + errors.get("cdip:" + s["key"], f"no data for point {s.get('mop')}")
            result.append({**base, "ok": False, "error": err, "hours": [], "days": []})
            continue

        def clean(arr, mx):
            return [(t * 1000, v) for t, v in zip(p["waveTime"], arr) if v is not None and 0 <= v <= mx]
        hs, tp, dp = clean(p["waveHs"], 25), clean(p["waveTp"], 30), clean(p["waveDp"], 360)

        hours = []
        for t in hours_list:
            if local_date(t) not in day_keys:
                continue
            hm = interp(hs, t)
            ft = None if hm is None else hm * M2FT * BIAS
            T = interp(tp, t)
            tide = interp(tide_series, t)
            w = nearest(weather, t)
            wi = wind_info(w, s["normal"])
            sc = {"size": 0 if ft is None else r1(size_score(ft, s["size"])), "period": period_score(T),
                  "tide": tide_score(tide, s["tide"]), "wind": r1(wi["score"])}
            score = sc["size"] + sc["period"] + sc["tide"] + sc["wind"]
            if ft is None or ft < s["size"][0]:
                score = min(score, 2)
            sh = shape(T, wi, w["speed"] if w else 0, tide, s["tide"])
            dpi = nearest(dp, t, key=lambda x: x[0])
            hours.append({
                "t": t, "day": local_date(t), "h": local_hour(t), "light": daylight(t),
                "ft": r1(ft), "lo": r1(ft * 0.75) if ft is not None else None, "hi": r1(ft * 1.25) if ft is not None else None,
                "swell": r1(hm * M2FT) if hm is not None else None, "tp": r1(T), "dp": rnd(dpi[1]) if dpi else None,
                "tide": r1(tide),
                "wind": rnd(w["speed"]) if w else None, "gust": rnd(w["gust"]) if w and w["gust"] is not None else None,
                "wdir": w["dir"] if w else None, "wtype": wi["type"], "wangle": wi["angle"],
                "surface": surface(w, wi), "shape": sh["label"], "shapeV": sh["v"],
                "air": r1(w["air"]) if w and w["air"] is not None else None, "code": w["code"] if w else None,
                "rain": w["rain"] if w else None, "isDay": w["isDay"] if w else 1,
                "sst": r1(interp(sst, t)), "sc": sc, "score": r1(clamp(score, 0, 10)),
            })

        days = []
        for d in day_keys:
            hrs = [x for x in hours if x["day"] == d and x["light"]]
            if not hrs:
                days.append({"date": d, "best": 0})
                continue
            bi = max(range(len(hrs)), key=lambda i: (hrs[i]["score"], -i))
            best = hrs[bi]["score"]
            a = z = bi
            while a > 0 and hrs[a - 1]["score"] >= best - 1 and hrs[a - 1]["t"] == hrs[a]["t"] - 3600e3:
                a -= 1
            while z < len(hrs) - 1 and hrs[z + 1]["score"] >= best - 1 and hrs[z + 1]["t"] == hrs[z]["t"] + 3600e3:
                z += 1
            days.append({"date": d, "best": best, "from": hrs[a]["t"], "to": hrs[z]["t"] + 3600e3, "at": hrs[bi],
                         "maxHi": max(x["hi"] or 0 for x in hrs)})
        result.append({**base, "ok": True, "hours": hours, "days": days})

    # weather summary for the home page: reference point = Isla Vista (Sands) if present
    ref = next((i for i, s in enumerate(spots) if s["key"] == "sands"), 0)
    rw = weather_of(mets[ref]) if spots else []
    day_weather = []
    for d in day_keys:
        hrs = [w for w in rw if local_date(w["t"]) == d]
        dh = [w for w in hrs if w["isDay"]]
        codes = sorted([w["code"] for w in dh if w["code"] is not None], reverse=True)
        day_weather.append({"date": d, "code": codes[len(codes) // 3] if codes else None,
                            "min": r1(min(w["air"] for w in hrs)) if hrs else None,
                            "max": r1(max(w["air"] for w in hrs)) if hrs else None,
                            "rain": max(w["rain"] or 0 for w in dh) if dh else None})
    wn = nearest(rw, now)
    ref_water = result[ref]["water"] if result else None
    return {
        "generated": now,
        "now": {"air": r1(wn["air"]), "code": wn["code"], "isDay": wn["isDay"], "wind": rnd(wn["speed"]), "wdir": wn["dir"]} if wn else None,
        "water": ref_water,
        "stations": {st: {**meta,
                          "tides": [{"t": t, "v": v} for t, v in tides[st] if local_date(t) in day_keys],
                          "hilo": [x for x in hilos[st] if local_date(x["t"]) in day_keys],
                          "now": r1(interp(tides[st], now))} for st, meta in TIDE_STATIONS.items()},
        "buoys": {b: {**meta, "data": buoys[b]} for b, meta in BUOYS.items()},
        "dayWeather": day_weather, "days": day_keys, "spots": result, "bias": BIAS,
        "errors": errors,
    }


def write_js(data, path=OUT):
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("window.SURF_DATA = " + js + ";\n", encoding="utf-8")


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    spots = json.loads(CONFIG.read_text(encoding="utf-8"))["spots"]
    resolve_spots(spots)
    print(f"Fetching data for {len(spots)} spots…")
    raw = fetch_all(spots)
    data = compute(raw, spots)
    if not any(s["ok"] for s in data["spots"]):
        # keep the previous web/data.js (and, online, the previous published site)
        print("\nNo forecast at all (network problem?): web/data.js left unchanged.")
        sys.exit(1)
    write_js(data)
    ok_spots = [s for s in data["spots"] if s["ok"]]
    # After dark there are no daylight hours left today: show the next day instead.
    today = next((d for d in data["days"] if any("from" in x for s in ok_spots for x in s["days"] if x["date"] == d)),
                 data["days"][0] if data["days"] else None)
    label = "today" if data["days"] and today == data["days"][0] else datetime.strptime(today, "%Y-%m-%d").strftime("%A %b %d") if today else "today"
    print(f"\nPage updated: {OUT}\n\nBest spots {label}:")
    best = sorted([s for s in data["spots"] if s["ok"]], key=lambda s: -next((d["best"] for d in s["days"] if d["date"] == today), 0))
    for s in best[:8]:
        d = next((d for d in s["days"] if d["date"] == today), {})
        print(f"  {s['name']:<18} {d.get('best', 0):>4}/10   ({s.get('mopUsed', s.get('mop'))})")
    bad = [s["name"] for s in data["spots"] if not s["ok"]]
    if bad:
        print(f"\nNo forecast for: {', '.join(bad)}")
    if raw["_errors"]:
        print(f"{len(raw['_errors'])} source(s) failed, the page still works without them.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
