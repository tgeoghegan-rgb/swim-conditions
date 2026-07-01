"""
Swim conditions notifier — Saint-Malo / Lancieux coast, Brittany

Sends a Telegram report twice a day (morning + afternoon) with:
  - High and low tide times/heights
  - Temperature, wind, wave height, and weather description
  - A soft "good swim window" suggestion near high tide (informational only —
    the report always sends regardless of conditions)

SETUP REQUIRED:
1. Telegram bot token + chat_id (already done)
2. WorldTides API key (already done — remember the secret name must be
   WORLDTIDES_KEY exactly, matching the workflow file)
3. Env vars: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID, WORLDTIDES_KEY
"""

import os
import requests
from datetime import datetime, timedelta

# ---- CONFIG ----------------------------------------------------------

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
WORLDTIDES_KEY = os.environ.get("WORLDTIDES_KEY", "")

LAT, LON = 48.6167, -2.1333  # Lancieux approx coords

# Thresholds used only for the soft "good window" suggestion — no longer
# used to decide whether to send a message at all.
TIDE_WINDOW_HOURS = 1.5
MAX_WIND_KMH = 20
MAX_WAVE_HEIGHT_M = 0.6
MIN_TEMP_C = 14

# Open-Meteo weather codes -> plain text
WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


# ---- TIDE DATA ---------------------------------------------------------

def fetch_tides(date_str):
    """Fetch high/low tide times for the area via worldtides.info."""
    url = "https://www.worldtides.info/api/v3"
    params = {
        "extremes": "",
        "lat": LAT,
        "lon": LON,
        "date": date_str,
        "days": 2,  # grab 2 days so late-day reports can show the next morning's tide too
        "key": WORLDTIDES_KEY,
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
    return sorted(tides, key=lambda t: t["time"])


# ---- WEATHER / MARINE DATA ---------------------------------------------

def fetch_marine_weather():
    """Fetch wind, wave height, weather code, and air temp forecast (Open-Meteo, free, no key)."""
    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": LAT,
        "longitude": LON,
        "hourly": "temperature_2m,windspeed_10m,weathercode",
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
            "weather_code": w["hourly"]["weathercode"][i],
        }
    for i, t in enumerate(m["hourly"]["time"]):
        if t in forecast:
            forecast[t]["wave_m"] = m["hourly"]["wave_height"][i]

    return forecast


def nearest_hour_forecast(forecast, target_time):
    target_str = target_time.strftime("%Y-%m-%dT%H:00")
    return forecast.get(target_str)


def weather_text(code):
    return WEATHER_CODES.get(code, f"Code {code}")


# ---- SOFT GOOD-WINDOW SUGGESTION -----------------------------------------

def good_window_note(high_tide_time, forecast):
    """Returns a suggestion string near a high tide, or None if no data."""
    hour = nearest_hour_forecast(forecast, high_tide_time)
    if not hour:
        return None

    calm = (
        hour["wind_kmh"] <= MAX_WIND_KMH
        and hour.get("wave_m", 0) <= MAX_WAVE_HEIGHT_M
        and hour["temp_c"] >= MIN_TEMP_C
    )
    if calm:
        start = high_tide_time - timedelta(hours=TIDE_WINDOW_HOURS)
        end = high_tide_time + timedelta(hours=TIDE_WINDOW_HOURS)
        return f"{start.strftime('%H:%M')}–{end.strftime('%H:%M')}"
    return None


# ---- TELEGRAM NOTIFY -----------------------------------------------------

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured — printing instead:\n", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message})
    if not resp.ok:
        print(resp.text)
    resp.raise_for_status()


# ---- REPORT BUILDING -------------------------------------------------------

def build_report(label, tides, forecast, reference_time):
    """
    Build a report covering the tides closest to reference_time (usually 'now'):
    the nearest high and nearest low, plus the next high after that.
    """
    upcoming = [t for t in tides if t["time"] >= reference_time - timedelta(hours=2)]
    if not upcoming:
        return f"🌊 Lancieux/Saint-Malo — {label}\n\nNo tide data available."

    # Take the next 3 tide events from now
    next_tides = upcoming[:3]

    lines = [f"🌊 Lancieux/Saint-Malo — {label}\n"]
    for t in next_tides:
        lines.append(f"{t['type']} tide: {t['time'].strftime('%H:%M')} ({t['height']:.1f}m)")

    # Weather snapshot at the nearest upcoming tide
    mid_point = next_tides[0]["time"]
    hour = nearest_hour_forecast(forecast, mid_point)
    if hour:
        lines.append("")
        lines.append(f"Conditions around {mid_point.strftime('%H:%M')}:")
        lines.append(
            f"🌡️ {hour['temp_c']:.0f}°C · 💨 Wind {hour['wind_kmh']:.0f} km/h · "
            f"🌊 Waves {hour.get('wave_m', 0):.1f}m · {weather_text(hour['weather_code'])}"
        )

    # Soft suggestions for high tides in this report
    notes = []
    for t in next_tides:
        if t["type"] == "High":
            window = good_window_note(t["time"], forecast)
            if window:
                notes.append(window)
    if notes:
        lines.append("")
        lines.append(f"Good swim windows (near high tide, calm-ish): {', '.join(notes)}")

    return "\n".join(lines)


# ---- MAIN -----------------------------------------------------------------

def main():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    tides = fetch_tides(today)
    forecast = fetch_marine_weather()

    label = "Morning report" if now.hour < 12 else "Afternoon report"
    report = build_report(label, tides, forecast, now)

    send_telegram(report)
    print(report)


if __name__ == "__main__":
    main()
