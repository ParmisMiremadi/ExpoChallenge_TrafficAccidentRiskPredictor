"""Live news ticker feed for the RoadGuard AI dashboard.

Blends two sources into short, one-line ticker items:

  1. National Weather Service active alerts (free, keyless) -- always on. These
     are the driving-relevant weather warnings (floods, storms, winter, wind).
  2. Jina AI Reader + Google Gemini (optional, needs your own keys in .env):
     reads a traffic/highway news page and summarizes it into a few short lines.

Results are cached for a few minutes so the ticker doesn't hammer the sources,
and every layer fails soft: if a source is down, the others still render, and
if all fail there is a small built-in fallback so the bar is never empty.
"""

import json
import os
import threading
import time
import urllib.parse
import urllib.request

# --------------------------------------------------------------------------- #
# Minimal .env loader (no dependency)                                          #
# --------------------------------------------------------------------------- #
def _load_env():
    path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


_load_env()

JINA_API_KEY = os.environ.get("JINA_API_KEY", "").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
NEWS_URL = os.environ.get("NEWS_URL", "").strip()

USER_AGENT = "RoadGuardAI/1.0 (traffic-risk demo)"
# Jina's edge (Cloudflare) blocks the default urllib signature, so send a
# browser-like User-Agent for that request.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
CACHE_TTL = 300  # seconds

_cache = {"items": None, "ts": 0, "updated": None}
_lock = threading.Lock()

FALLBACK = [
    {"category": "Info", "text": "Live feed unavailable — showing sample items. Drive to conditions.", "url": ""},
    {"category": "Weather", "text": "Check local forecasts before travel in adverse weather.", "url": ""},
]


# --------------------------------------------------------------------------- #
# Sources                                                                      #
# --------------------------------------------------------------------------- #
def fetch_nws(limit=12):
    """Driving-relevant severe/immediate weather alerts, nationwide."""
    url = "https://api.weather.gov/alerts/active?urgency=Immediate&severity=Severe,Extreme"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/geo+json"})
    items = []
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
    except Exception:
        return items
    seen = set()
    for f in data.get("features", []):
        p = f.get("properties", {})
        event = p.get("event", "")
        area = (p.get("areaDesc") or "").split(";")[0].strip()
        key = (event, area)
        if not event or key in seen:
            continue
        seen.add(key)
        items.append({
            "category": "Weather",
            "text": f"{event} — {area}" if area else event,
            "url": p.get("id", ""),
        })
        if len(items) >= limit:
            break
    return items


def _jina_read(target_url):
    req = urllib.request.Request(
        "https://r.jina.ai/" + target_url,
        headers={
            "Authorization": f"Bearer {JINA_API_KEY}",
            "X-Return-Format": "text",
            "User-Agent": BROWSER_UA,
        },
    )
    # One retry: Jina's Cloudflare edge occasionally rejects a cold request.
    last = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", "ignore")[:12000]
        except Exception as e:
            last = e
            time.sleep(1.5)
    raise last


def _gemini_summarize(text):
    prompt = (
        "From the news content below, extract up to 6 SHORT one-line ticker items "
        "about current or recent US traffic, road accidents, highway closures, or "
        "weather affecting driving. Return ONLY a JSON array of objects with keys "
        '"category" (one of Traffic, Accident, Weather, Warning) and "text" '
        "(<= 90 characters, no leading dash). No markdown, no commentary.\n\n"
        f"--- NEWS CONTENT ---\n{text}"
    )
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    parsed = json.loads(raw)
    out = []
    for it in parsed[:6]:
        txt = str(it.get("text", "")).strip()
        if txt:
            out.append({"category": str(it.get("category", "News")).strip() or "News", "text": txt, "url": ""})
    return out


def fetch_llm_news():
    """Optional Jina + Gemini traffic-news layer; empty if keys/URL not set."""
    if not (JINA_API_KEY and GEMINI_API_KEY and NEWS_URL):
        return []
    try:
        return _gemini_summarize(_jina_read(NEWS_URL))
    except Exception:
        return []


# --------------------------------------------------------------------------- #
# Public API (cached)                                                          #
# --------------------------------------------------------------------------- #
def get_news(force=False):
    now = time.time()
    with _lock:
        fresh = _cache["items"] is not None and (now - _cache["ts"]) < CACHE_TTL
        if fresh and not force:
            return {"items": _cache["items"], "updated": _cache["updated"]}

    items = fetch_llm_news() + fetch_nws()
    if not items:
        items = FALLBACK
    updated = time.strftime("%Y-%m-%dT%H:%M")

    with _lock:
        _cache.update(items=items, ts=now, updated=updated)
    return {"items": items, "updated": updated}
