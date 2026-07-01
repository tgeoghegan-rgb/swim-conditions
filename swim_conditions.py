"""
Swim conditions notifier — Saint-Malo / Lancieux coast, Brittany

Checks tide + weather + marine conditions for good swim windows around
high tide, and sends a Telegram message if conditions look good.

Run this on a schedule (cron, GitHub Actions, etc.) once or twice a day —
e.g. 7am to check the day's windows.

SETUP REQUIRED:
1. Telegram bot:
   - Message @BotFather on Telegram, run /newbot, copy the token
   - Message your new bot once (anything), then visit:
     https://api.telegram.org/bot<TOKEN>/getUpdates
     to find your chat_id in the response
2. SHOM tide API:
   - Register at https://services.data.shom.fr for API access (free)
   - Or swap in worldtides.info if you prefer (see fetch_tides below)
3. Set the environment variables below (or hardcode for personal use)
"""

import os
import requests
from datetime import datetime, timedelta

# ---- CONFIG ----------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Location: Lancieux uses Saint-Malo as reference tide station
LAT, LON = 48.6167, -2.1333  # Lancieux approx coords
SHOM_STATION = "SAINT-MALO"  # reference port for tide predictions

# Condition thresholds — tune these to taste
TIDE_WINDOW_HOURS = 1.5       # +/- hours around high tide considered "good"
MAX_WIND_KMH = 20
MAX_WAVE_HEIGHT_M = 0.6
MIN_TEMP_C = 14                # air temp, adjust for your comfort
DAYLIGHT_ONLY = True

# ---- TIDE DATA ---------------------------------------------------------

def fetch_tides(date_str):
    """
    Fetch high/low tide times for the reference station.
    Placeholder using worldtides.info — swap for SHOM once you have API access.
    Returns list of dicts: [{"type": "High", "time": datetime, "height": float}, ...]
    """
    # Example using worldtides.info (requires free API key)
    api_key = os.environ.get("WORLDTIDES_KEY", "")
    url = "https://www.worldtides.info/api/v3"
    params = {
        "extremes": "",
        "lat": LAT,
        "lon": LON,
        "date": date_str,
        "days": 1,
        "key": api_key,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    tides = []
    for extreme in data.get("extremes", []):
        tides.append({
            "type": extreme["type"],  # "High" or "Low"
            "time": datetime.fromtimestamp(extreme["dt"]),
            "height": extreme["height"],
        })
    return tides


# ---- WEATHER / MARINE DATA ---------------------------------------------

def fetch_marine_weather():
    """
    Fetch wind, wave height, and air temp forecast from Open-Meteo (free, no key).
    Returns hourly forecast dict keyed by ISO timestamp.
    """
    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m,windspeed_10m",
        "timezone": "Europe/Paris",
        "forecast_days": 2,
    }
    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "wave_height",
        "timezone": "Europe/Paris",
        "forecast_days": 2,
    }

    w = requests.get(weather_url, params=weather_params, timeout=15).json()
    m = requests.get(marine_url, params=marine_params, timeout=15).json()

    forecast = {}
    for i, t in enumerate(w["hourly"]["time"]):
        forecast[t] = {
            "temp_c": w["hourly"]["temperature_2m"][i],
            "wind_kmh": w["hourly"]["windspeed_10m"][i],
        }
    for i, t in enumerate(m["hourly"]["time"]):
        if t in forecast:
            forecast[t]["wave_m"] = m["hourly"]["wave_height"][i]

    return forecast


def nearest_hour_forecast(forecast, target_time):
    """Find the forecast entry closest to target_time."""
    target_str = target_time.strftime("%Y-%m-%dT%H:00")
    return forecast.get(target_str)


# ---- CONDITIONS LOGIC ---------------------------------------------------

def evaluate_window(high_tide_time, forecast):
    """Check conditions in the window around a high tide."""
    hour = nearest_hour_forecast(forecast, high_tide_time)
    if not hour:
        return None

    reasons_bad = []
    if hour["wind_kmh"] > MAX_WIND_KMH:
        reasons_bad.append(f"wind {hour['wind_kmh']:.0f} km/h")
    if hour.get("wave_m", 0) > MAX_WAVE_HEIGHT_M:
        reasons_bad.append(f"waves {hour['wave_m']:.1f}m")
    if hour["temp_c"] < MIN_TEMP_C:
        reasons_bad.append(f"air temp {hour['temp_c']:.0f}°C")

    return {
        "good": len(reasons_bad) == 0,
        "reasons_bad": reasons_bad,
        "details": hour,
    }


# ---- TELEGRAM NOTIFY -----------------------------------------------------

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured — printing instead:\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    resp.raise_for_status()


# ---- MAIN -----------------------------------------------------------------

def main():
    send_telegram('Test message from GitHub Actions')
    today = datetime.now().strftime("%Y-%m-%d")
    tides = fetch_tides(today)
    forecast = fetch_marine_weather()

    highs = [t for t in tides if t["type"] == "High"]
    if not highs:
        send_telegram("Couldn't find tide data for today — check the script.")
        return

    good_windows = []
    for high in highs:
        result = evaluate_window(high["time"], forecast)
        if result and result["good"]:
            good_windows.append(high)

    if good_windows:
        lines = ["🌊 Good swim conditions today (Lancieux/Saint-Malo):"]
        for w in good_windows:
            start = w["time"] - timedelta(hours=TIDE_WINDOW_HOURS)
            end = w["time"] + timedelta(hours=TIDE_WINDOW_HOURS)
            lines.append(f"High tide {w['time'].strftime('%H:%M')} "
                         f"({w['height']:.1f}m) — good window {start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
        send_telegram("\n".join(lines))
    else:
        print("No good windows today — no notification sent.")
        # Uncomment to always get a status message, even on bad days:
        # send_telegram("No good swim windows today (wind/waves/temp not ideal).")


if __name__ == "__main__":
    main()
