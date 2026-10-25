#!/usr/bin/env python3
"""Fetches market data, scores NQ macro bias, writes data.json + history.json."""
import json, datetime as dt, urllib.request
from zoneinfo import ZoneInfo

TICKERS = {"nq": "NQ=F", "es": "ES=F", "rty": "RTY=F", "tnx": "^TNX", "fvx": "^FVX",
           "vix": "^VIX", "dxy": "DX-Y.NYB", "hyg": "HYG", "nvda": "NVDA", "msft": "MSFT",
           "aapl": "AAPL", "amzn": "AMZN", "meta": "META", "googl": "GOOGL"}
MEGA = ["nvda", "msft", "aapl", "amzn", "meta", "googl"]

# Tune everything here: (name, weight)
DRIVERS = {"htf": ("Higher-timeframe trend", 3), "y10": ("10Y yield", 3), "fed": ("Rate expectations (5Y yield)", 2),
           "vix": ("VIX / volatility", 2), "mega": ("Mega-cap leadership", 3), "dxy": ("DXY (US dollar)", 1),
           "brd": ("Risk appetite / breadth", 2), "glx": ("Overnight move", 1)}
T = dict(yld_5d=0.10, fvx_10d=0.12, vix_hi=25, vix_lo=16, vix_spike=0.15, mega_5d=0.01,
         dxy_5d=0.007, glx=0.003, neutral=18, strong=50)

def sma(s, n): return float(s.tail(n).mean())
def chg(s, n): return float(s.iloc[-1] / s.iloc[-1 - n] - 1)
def dif(s, n): return float(s.iloc[-1] - s.iloc[-1 - n])
def sgn(x, hi, lo): return 1 if x > hi else -1 if x < lo else 0

def score_drivers(c):
    out = {}
    def run(k, fn):
        try: out[k] = fn()
        except Exception as e: out[k] = None
    def htf():
        s = c["nq"]; p, a, b = s.iloc[-1], sma(s, 20), sma(s, 50)
        v = 1 if p > a > b else -1 if p < a < b else 0
        return v, f"NQ {p:,.0f} vs 20d {a:,.0f} / 50d {b:,.0f}"
    def y10():
        d = dif(c["tnx"], 5); v = -sgn(d, T["yld_5d"], -T["yld_5d"])
        return v, f"10Y {c['tnx'].iloc[-1]:.2f}% ({d*100:+.0f} bps over 5d)"
    def fed():
        d = dif(c["fvx"], 10); v = -sgn(d, T["fvx_10d"], -T["fvx_10d"])
        return v, f"5Y {c['fvx'].iloc[-1]:.2f}% ({d*100:+.0f} bps over 10d)"
    def vix():
        s = c["vix"]; l, r = s.iloc[-1], chg(s, 5)
        v = -1 if (l > T["vix_hi"] or r > T["vix_spike"]) else 1 if (l < T["vix_lo"] and r <= 0.05) else 0
        return v, f"VIX {l:.1f} ({r*100:+.0f}% over 5d)"
    def mega():
        r = sum(chg(c[k], 5) for k in MEGA) / len(MEGA); v = sgn(r, T["mega_5d"], -T["mega_5d"])
        return v, f"Mega-cap avg {r*100:+.1f}% over 5d"
    def dxy():
        r = chg(c["dxy"], 5); v = -sgn(r, T["dxy_5d"], -T["dxy_5d"])
        return v, f"DXY {c['dxy'].iloc[-1]:.2f} ({r*100:+.1f}% over 5d)"
    def brd():
        a = int(c["rty"].iloc[-1] > sma(c["rty"], 20)); b = int(c["hyg"].iloc[-1] > sma(c["hyg"], 20))
        d = int(chg(c["nq"], 5) > chg(c["es"], 5)); n = a + b + d
        return (1 if n == 3 else -1 if n == 0 else 0), f"{n}/3 risk-on (RTY>20d: {a}, HYG>20d: {b}, NQ>ES 5d: {d})"
    def glx():
        r = chg(c["nq"], 1); v = sgn(r, T["glx"], -T["glx"])
        return v, f"NQ {r*100:+.2f}% vs prior close"
    for k, f in [("htf", htf), ("y10", y10), ("fed", fed), ("vix", vix), ("mega", mega), ("dxy", dxy), ("brd", brd), ("glx", glx)]:
        run(k, f)
    return out

def label(s):
    n, st = T["neutral"], T["strong"]
    return "Strong bullish" if s >= st else "Bullish" if s >= n else "Neutral" if s > -n else "Bearish" if s > -st else "Strong bearish"

def compute(c):
    res = score_drivers(c); tot = wsum = 0; rows = []
    for k, (name, w) in DRIVERS.items():
        r = res.get(k)
        if r: tot += r[0] * w; wsum += w
        rows.append({"id": k, "name": name, "weight": w, "value": r[0] if r else None,
                     "reason": r[1] if r else "data unavailable"})
    score = round(tot / wsum * 100) if wsum else 0
    return {"score": score, "label": label(score), "drivers": rows}

def events():
    try:
        req = urllib.request.Request("https://nfs.faireconomy.media/ff_calendar_thisweek.json", headers={"User-Agent": "Mozilla/5.0"})
        data = json.load(urllib.request.urlopen(req, timeout=20)); ny = ZoneInfo("America/New_York")
        today = dt.datetime.now(ny).date(); out = []
        for e in data:
            if e.get("country") == "USD" and e.get("impact") == "High":
                d = dt.datetime.fromisoformat(e["date"]).astimezone(ny)
                if d.date() == today: out.append(f"{d:%H:%M} ET  {e['title']}")
        return sorted(out)
    except Exception:
        return []

def main():
    import yfinance as yf
    df = yf.download(list(TICKERS.values()), period="6mo", interval="1d", auto_adjust=True, progress=False, group_by="ticker")
    c = {}
    for k, t in TICKERS.items():
        try:
            s = df[t]["Close"].dropna()
            if len(s) > 60: c[k] = s
        except Exception: pass
    r = compute(c); ev = events(); now = dt.datetime.now(dt.timezone.utc)
    r.update({"updated": now.isoformat(timespec="minutes"), "events": ev, "event_risk": bool(ev),
              "price": round(float(c["nq"].iloc[-1]), 2) if "nq" in c else None, "contract": "NQZ2026"})
    json.dump(r, open("data.json", "w"), indent=1)
    try: h = json.load(open("history.json"))
    except Exception: h = {}
    d = dt.datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    h[d] = {"score": r["score"], "label": r["label"], "event_risk": r["event_risk"], "price": r["price"]}
    json.dump(dict(sorted(h.items())[-180:]), open("history.json", "w"), indent=1)
    print(r["label"], r["score"])

if __name__ == "__main__":
    main()
