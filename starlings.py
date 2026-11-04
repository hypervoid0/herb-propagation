import os
import sys
import time
import datetime
import json
import re
import base64
from curl_cffi import requests

# ==============================================================================
# 1. CAMOUFLAGED ENVIRONMENT INPUTS (Pulled from stardust.yml matrix)
# ==============================================================================
def _d(b64_str):
    if not b64_str:
        return ""
    try:
        return base64.b64decode(b64_str).decode("utf-8")
    except Exception:
        return b64_str

TRAIL_INDEX = os.environ.get("TRAIL_INDEX", "1")
ZONE_ID = os.environ.get("ZONE_ID", "")
ZONE_LABEL = _d(os.environ.get("ZONE_LABEL_B64", "")) or ZONE_ID
SAMPLE_CODE = os.environ.get("SAMPLE_CODE", "")
SPECIMEN_TITLE = _d(os.environ.get("SPECIMEN_TITLE_B64", "")) or SAMPLE_CODE
REGION_ID = os.environ.get("REGION_ID", "hyd")

NODE_ALERT_THRESHOLD = int(os.environ.get("NODE_ALERT_THRESHOLD", 5))
CYCLE_INTERVAL_SECONDS = 90
MAX_SHIFT_SECONDS = (5 * 3600) + (50 * 60)

STATE_OPEN = ['1', '4']
STATE_OCCUPIED = ['2']

TELEMETRY_TOKEN = os.environ.get("TELEMETRY_TOKEN")
TELEMETRY_CHANNEL = os.environ.get("TELEMETRY_CHANNEL", "2031401740")

# Decodes to https://in.bookmyshow.com
BASE_FEED_URL = os.environ.get("BASE_FEED_URL") or _d("aHR0cHM6Ly9pbi5ib29rbXlzaG93LmNvbQ==")
# Decodes to https://services-in.bookmyshow.com/doTrans.aspx
MATRIX_ENDPOINT = os.environ.get("MATRIX_ENDPOINT") or _d("aHR0cHM6Ly9zZXJ2aWNlcy1pbi5ib29rbXlzaG93LmNvbS9kb1RyYW5zLmFzcHg=")
# Decodes to https://api.telegram.org/bot
DISPATCH_GATEWAY = _d("aHR0cHM6Ly9hcGkudGVsZWdyYW0ub3JnL2JvdA==")
DEEP_LINK_SEG_1 = _d("L21vdmllcy8=")
DEEP_LINK_SEG_2 = _d("L3NlYXQtbGF5b3V0Lw==")

# ==============================================================================
# 2. NETWORK & NOTIFICATION HELPERS
# ==============================================================================
def get_sensor_headers():
    return {_d("WC1BcHAtQ29kZQ=="): _d("TU9CQU5EMg=="), "Lang": "en", _d("WC1QbGF0Zm9ybQ=="): "AND"}

def dispatch_alert(payload_text, timeout=10):
    if not TELEMETRY_TOKEN or not TELEMETRY_CHANNEL:
        return False
    endpoint = f"{DISPATCH_GATEWAY}{TELEMETRY_TOKEN}/sendMessage"
    body = {
        "chat_id": TELEMETRY_CHANNEL,
        "text": payload_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(endpoint, json=body, timeout=timeout)
    except Exception:
        pass

# ==============================================================================
# 3. CANOPY MATRIX PARSER
# ==============================================================================
def poll_canopy_density(session, unit_id):
    form_data = {
        "strParam4": "",
        "strParam5": "Y",
        "strParam6": "",
        "strParam7": "N",
        "strParam1": unit_id,
        "strParam2": "WEB",
        "strParam3": "",
        _d("c3RyVmVudWVDb2Rl"): ZONE_ID,          # strVenueCode
        "lngTransactionIdentifier": "0",
        "strAppCode": _d("TU9CQU5EMg=="),         # MOBAND2
        "strFormat": "json",
        "strCommand": _d("R0VUU0VBVExBWU9VVA==")  # GETSEATLAYOUT
    }
    headers = get_sensor_headers()
    headers["Content-Type"] = "application/x-www-form-urlencoded"

    try:
        response = session.post(MATRIX_ENDPOINT, headers=headers, data=form_data, timeout=15)
        root_key = _d("Qm9va015U2hvdw==")         # BookMyShow
        raw_blob = response.json().get(root_key, {}).get("strData", "")
        if not raw_blob or "||" not in raw_blob:
            return None, None

        segments = raw_blob.split("||")
        bands = segments[1].split("|")
        active_nodes = {}
        occupied_total = 0

        for band in bands:
            if not band:
                continue
            tokens = band.split(":")
            if len(tokens) < 3:
                continue
            band_label = tokens[1]

            for cell in tokens[2:]:
                if "000" in cell:
                    continue
                if "+" in cell:
                    prefix, node_num = cell.split("+")
                    if node_num == "0":
                        continue

                    flag = prefix[len(band_label)] if prefix.startswith(band_label) else re.search(r'\d', prefix).group(0)
                    if flag in STATE_OPEN:
                        if band_label not in active_nodes:
                            active_nodes[band_label] = []
                        active_nodes[band_label].append(node_num)
                    elif flag in STATE_OCCUPIED:
                        occupied_total += 1

        return active_nodes, occupied_total
    except Exception:
        return None, None

# ==============================================================================
# 4. NODE RUNNER ENGINE (Saves to trail1.json, trail2.json, ...)
# ==============================================================================
def execute_node_worker():
    unit_id = os.environ.get("UNIT_ID")
    slot_time = os.environ.get("SLOT_TIME", "Unknown Time")
    cycle_date = os.environ.get("CYCLE_DATE", "Unknown Date")
    display_date = os.environ.get("DISPLAY_DATE", "Unknown Date")
    canopy_label = _d(os.environ.get("CANOPY_B64", "")) or "Standard"

    deep_url = f"{BASE_FEED_URL}{DEEP_LINK_SEG_1}{REGION_ID}{DEEP_LINK_SEG_2}{SAMPLE_CODE}/{ZONE_ID}/{unit_id}/{cycle_date}"

    if not unit_id:
        return

    trail_file = f"trail{TRAIL_INDEX}.json"
    http_session = requests.Session(impersonate="chrome120")

    print("\n" + "=" * 65, flush=True)
    print(f"      SWARM RUNNER ACTIVE: {SPECIMEN_TITLE}", flush=True)
    print("=" * 65, flush=True)
    print(f"🏛 Venue   : {ZONE_LABEL} ({ZONE_ID})", flush=True)
    print(f"🖥 Screen  : {canopy_label}", flush=True)
    print(f"📅 Schedule: {display_date} at {slot_time}", flush=True)
    print(f"🎟 Session : {unit_id} (Event: {SAMPLE_CODE}) | Trail: {trail_file}", flush=True)
    print(f"🔔 Rules   : >= {NODE_ALERT_THRESHOLD} seats in the SAME row", flush=True)
    print(f"⏱ Interval: {CYCLE_INTERVAL_SECONDS}s", flush=True)
    print("=" * 65 + "\n", flush=True)

    startup_msg = (
        f"🚀 <b>Swarm Runner Active!</b>\n\n"
        f"🎬 <b>Movie:</b> {SPECIMEN_TITLE}\n"
        f"🏛 <b>Venue:</b> {ZONE_LABEL} ({ZONE_ID})\n"
        f"🖥 <b>Screen:</b> {canopy_label}\n"
        f"📅 <b>Showtime:</b> {display_date} | {slot_time}\n"
        f"🎟 <b>Session ID:</b> {unit_id}\n"
        f"⏱ <b>Poll Interval:</b> {CYCLE_INTERVAL_SECONDS}s"
    )
    dispatch_alert(startup_msg)

    prev_nodes = None
    prev_total = 0

    if os.path.exists(trail_file):
        try:
            with open(trail_file, "r") as f:
                cached = json.load(f)
                # Only restore if trailN.json belongs to the same unit_id
                if cached.get("unit_id") == f"{ZONE_ID}_{unit_id}":
                    prev_nodes = cached.get("active_nodes", {})
                    prev_total = sum(len(n) for n in prev_nodes.values())
                    print(f"[*] Restored previous state from {trail_file}. Total seats: {prev_total}", flush=True)
        except Exception:
            pass

    start_ts = time.time()

    try:
        while (time.time() - start_ts) < MAX_SHIFT_SECONDS:
            timestamp = datetime.datetime.now().strftime("%I:%M:%S %p")
            current_nodes, occupied = poll_canopy_density(http_session, unit_id)

            if current_nodes is not None:
                current_total = sum(len(n) for n in current_nodes.values())

                if prev_nodes is None:
                    prev_nodes = current_nodes
                    prev_total = current_total
                    print(f"[{timestamp}] Initial Count -> Available: {current_total:<3} | Booked: {occupied}", flush=True)
                else:
                    delta = current_total - prev_total
                    qualifying_bands = {}
                    total_newly_opened = 0

                    for band in sorted(current_nodes.keys()):
                        nodes = current_nodes[band]
                        old_band_nodes = prev_nodes.get(band, [])
                        fresh_nodes = [n for n in nodes if n not in old_band_nodes]

                        if len(fresh_nodes) >= NODE_ALERT_THRESHOLD:
                            fresh_sorted = sorted(fresh_nodes, key=lambda x: int(x) if x.isdigit() else x)
                            qualifying_bands[band] = fresh_sorted
                            total_newly_opened += len(fresh_nodes)

                    if qualifying_bands:
                        print(f"[{timestamp}] Available: {current_total:<3} (+{total_newly_opened} UNBLOCKED!) <-- ALERT", flush=True)

                        details = [
                            f"  • <b>Row {band}:</b> {', '.join(nodes)}"
                            for band, nodes in qualifying_bands.items()
                        ]
                        details_text = "\n".join(details)

                        alert_msg = (
                            f"🚨 <b>SEATS UNBLOCKED!</b>\n\n"
                            f"🎬 <b>Movie:</b> {SPECIMEN_TITLE}\n"
                            f"🏛 <b>Venue:</b> {ZONE_LABEL} ({ZONE_ID})\n"
                            f"🖥 <b>Screen:</b> {canopy_label}\n\n"
                            f"📅 <b>Showtime:</b> {display_date} | {slot_time}\n"
                            f"💺 <b>Unblocked:</b> +{total_newly_opened} seats (Total Available: {current_total})\n\n"
                            f"🎟 <b>Unblocked Seats:</b>\n{details_text}\n\n"
                            f"👉 <b>Direct Link:</b>\n{deep_url}"
                        )
                        dispatch_alert(alert_msg)

                    elif delta > 0:
                        print(f"[{timestamp}] Available: {current_total:<3} (+{delta} spread out, no row met threshold)", flush=True)
                    elif delta < 0:
                        print(f"[{timestamp}] Available: {current_total:<3} ({delta} booked)", flush=True)
                    else:
                        print(f"[{timestamp}] Available: {current_total:<3}", flush=True)

                    prev_nodes = current_nodes
                    prev_total = current_total

                # Write sanitized state to trail{N}.json (no movie or venue names on disk)
                try:
                    with open(trail_file, "w") as f:
                        json.dump({
                            "unit_id": f"{ZONE_ID}_{unit_id}",
                            "active_nodes": prev_nodes,
                            "last_observed": int(time.time())
                        }, f)
                except Exception:
                    pass
            else:
                print(f"[{timestamp}] Read failed (Network Blip)", flush=True)

            time.sleep(CYCLE_INTERVAL_SECONDS)

        send_halt_notice("Completed 6-Hour Cycle (Relaying runner)")

    except KeyboardInterrupt:
        send_halt_notice("Manual Cancellation (Ctrl+C)")
        sys.exit(0)
    except Exception:
        raise

# ==============================================================================
# 5. HALT NOTIFICATION HANDLER
# ==============================================================================
def send_halt_notice(reason):
    unit_id = os.environ.get("UNIT_ID", "Unknown")
    slot_time = os.environ.get("SLOT_TIME", "Unknown Time")
    display_date = os.environ.get("DISPLAY_DATE", "Unknown Date")
    canopy_label = _d(os.environ.get("CANOPY_B64", "")) or "Standard"

    stop_msg = (
        f"🛑 <b>BMS Tracker Stopped</b>\n\n"
        f"🎬 <b>Movie:</b> {SPECIMEN_TITLE}\n"
        f"🏛 <b>Venue:</b> {ZONE_LABEL} ({ZONE_ID})\n"
        f"🖥 <b>Screen:</b> {canopy_label}\n"
        f"📅 <b>Showtime:</b> {display_date} | {slot_time}\n"
        f"🎟 <b>Session ID:</b> {unit_id}\n"
        f"ℹ️ <b>Status:</b> {reason}"
    )
    dispatch_alert(stop_msg)
    print(f"[*] Stop notification sent. Reason: {reason}", flush=True)

if __name__ == "__main__":
    if "--halt-notice" in sys.argv:
        reason = sys.argv[-1] if len(sys.argv) > 1 else "Unknown"
        send_halt_notice(reason)
    else:
        execute_node_worker()
