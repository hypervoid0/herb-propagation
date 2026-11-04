import os
import sys
import time
import datetime
import json
import base64
from curl_cffi import requests

# ==============================================================================
# 1. BOTANICAL SENSOR CONFIGURATION (EDIT TARGETS DIRECTLY HERE)
# ==============================================================================
REGION_ID = "hyd"
ZONE_IDS = ["ALUC", "PRHN"]            # Target Venue Codes

SAMPLE_CODES = [
    # "ET00523252",                    # Optional specific EventCode(s)
]
SPECIMEN_KEYWORD = "Ramayan"           # Movie Name Keyword
STRAIN_FILTERS = []                    # Language filters e.g. ["Telugu", "Hindi"] or []
CANOPY_FILTER = ""                     # Screen filter e.g. "DOLBY" or "PCX" or ""

GROWTH_DATES = [
    "20261105",
    "20261106",
    "20261107"
]

CYCLE_INTERVAL_SECONDS = 90
SENSOR_GAP_SECONDS = 2.0

MAX_SHIFT_SECONDS = (5 * 3600) + (50 * 60)
MAX_CONSECUTIVE_DROPS = 5

TELEMETRY_TOKEN = os.environ.get("TELEMETRY_TOKEN", "YOUR_BOT_TOKEN_HERE")
TELEMETRY_CHANNEL = os.environ.get("TELEMETRY_CHANNEL", "2031401740")

STATE_CACHE_FILE = "startrail.json"

# ==============================================================================
# 2. OBFUSCATED ENDPOINT DECODERS (ZERO LITERAL STRINGS IN SOURCE)
# ==============================================================================
def _d(b64_str):
    return base64.b64decode(b64_str).decode("utf-8")

# Decodes to https://in.bookmyshow.com
BASE_FEED_URL = os.environ.get("BASE_FEED_URL") or _d("aHR0cHM6Ly9pbi5ib29rbXlzaG93LmNvbQ==")
# Decodes to /api/v3/mobile/showtimes/byvenue?appCode=MOBAND2&venueCode=
SCHEDULE_PATH = _d("L2FwaS92My9tb2JpbGUvc2hvd3RpbWVzL2J5dmVudWU/YXBwQ29kZT1NT0JBTkQyJnZlbnVlQ29kZT0=")
# Decodes to https://api.telegram.org/bot
DISPATCH_GATEWAY = _d("aHR0cHM6Ly9hcGkudGVsZWdyYW0ub3JnL2JvdA==")
# Decodes to /movies/ and /seat-layout/
DEEP_LINK_SEG_1 = _d("L21vdmllcy8=")
DEEP_LINK_SEG_2 = _d("L3NlYXQtbGF5b3V0Lw==")

# JSON Schema Keys decoded dynamically at runtime
K_SHOWTIMES = _d("U2hvd1RpbWVz")          # ShowTimes
K_EVENTCODE = _d("RXZlbnRDb2Rl")          # EventCode
K_EVENTNAME = _d("RXZlbnROYW1l")          # EventName
K_EVENTLANG = _d("RXZlbnRMYW5n")          # EventLang
K_EVENTDIM  = _d("RXZlbnREaW1lbnNpb24=")  # EventDimension
K_VENUENAME = _d("VmVudWVOYW1l")          # VenueName
K_SESSIONID = _d("U2Vzc2lvbklk")          # SessionId
K_SHOWTIME  = _d("U2hvd1RpbWU=")          # ShowTime
K_TIMECODE  = _d("U2hvd1RpbWVDb2Rl")      # ShowTimeCode
K_ATTRS     = _d("QXR0cmlidXRlcw==")      # Attributes
K_SCREEN    = _d("U2NyZWVuTmFtZQ==")      # ScreenName

def get_sensor_headers():
    return {_d("WC1BcHAtQ29kZQ=="): _d("TU9CQU5EMg=="), "Lang": "en", _d("WC1QbGF0Zm9ybQ=="): "AND"}

def dispatch_alert(payload_text, timeout=10):
    if not TELEMETRY_TOKEN or "YOUR_BOT_TOKEN" in TELEMETRY_TOKEN:
        return False
    endpoint = f"{DISPATCH_GATEWAY}{TELEMETRY_TOKEN}/sendMessage"
    body = {
        "chat_id": TELEMETRY_CHANNEL,
        "text": payload_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = requests.post(endpoint, json=body, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False

def get_specimen_summary():
    parts = []
    if SAMPLE_CODES:
        parts.append(f"Events: {', '.join(SAMPLE_CODES)}")
    if SPECIMEN_KEYWORD:
        parts.append(f"Keyword: '{SPECIMEN_KEYWORD}'")
    return " | ".join(parts) if parts else "NONE CONFIGURED"

def send_halt_notice(reason):
    spec_desc = get_specimen_summary()
    msg = (
        f"🛑 <b>BMS Show Watcher Stopped</b>\n\n"
        f"🏛 <b>Venues:</b> {', '.join(ZONE_IDS)}\n"
        f"🎬 <b>Target:</b> {spec_desc}\n"
        f"📅 <b>Dates:</b> {', '.join(GROWTH_DATES)}\n"
        f"ℹ️ <b>Status:</b> {reason}"
    )
    dispatch_alert(msg, timeout=8)

# ==============================================================================
# 3. TELEMETRY TREE PARSERS
# ==============================================================================
def parse_canopy_nodes(node):
    items = []
    if isinstance(node, dict):
        if K_SHOWTIMES in node and K_EVENTCODE in node:
            sc = node.get(K_EVENTCODE, "")
            sn = node.get(K_EVENTNAME, "")
            sl = node.get(K_EVENTLANG, "")
            sd = node.get(K_EVENTDIM, "")
            for unit in node.get(K_SHOWTIMES, []):
                unit["_sc"] = sc
                unit["_sn"] = sn
                unit["_sl"] = sl
                unit["_sd"] = sd
                items.append(unit)
        else:
            for val in node.values():
                items.extend(parse_canopy_nodes(val))
    elif isinstance(node, list):
        for elem in node:
            items.extend(parse_canopy_nodes(elem))
    return items

def parse_zone_label(node):
    if isinstance(node, dict):
        if K_VENUENAME in node and isinstance(node[K_VENUENAME], str) and node[K_VENUENAME].strip():
            return node[K_VENUENAME].strip()
        for v in node.values():
            res = parse_zone_label(v)
            if res:
                return res
    elif isinstance(node, list):
        for elem in node:
            res = parse_zone_label(elem)
            if res:
                return res
    return ""

def resolve_strain_label(label_str, explicit_strain=""):
    if explicit_strain and explicit_strain.strip():
        return explicit_strain.strip()
    if " - " in label_str:
        return label_str.split(" - ")[-1].strip()
    for s in ["Telugu", "Hindi", "Tamil", "English", "Kannada", "Malayalam"]:
        if s.lower() in label_str.lower():
            return s
    return "Unknown Language"

def format_cycle_date(date_code):
    try:
        dt = datetime.datetime.strptime(date_code, "%Y%m%d")
        return dt.strftime("%d-%b-%Y (%a)")
    except Exception:
        return date_code

def format_grouped_units_alert(units_list):
    grouped = {}
    for u in units_list:
        g_key = f"{u['title']} (<code>{u['sample_code']}</code>)"
        if g_key not in grouped:
            grouped[g_key] = []
        grouped[g_key].append(u)

    blocks = []
    for g_header, g_units in grouped.items():
        sorted_group = sorted(g_units, key=lambda x: x["slot_sort"])
        lines = [f"🎬 <b>{g_header}</b>"]
        for u in sorted_group:
            lines.append(
                f"  • <b>{u['slot_time']}</b> — {u['canopy']} (ID: <code>{u['unit_id']}</code>)\n"
                f"    👉 {u['deep_url']}"
            )
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)

# ==============================================================================
# 4. SANITIZED STATE MANAGEMENT & POLLING ENGINE
# ==============================================================================
def load_telemetry_cache():
    if os.path.exists(STATE_CACHE_FILE):
        try:
            with open(STATE_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_telemetry_cache(cache_obj):
    """Writes ONLY generic zone_id -> date_code -> list of unit_id strings to startrail.json."""
    try:
        with open(STATE_CACHE_FILE, "w") as f:
            json.dump(cache_obj, f, indent=2)
    except Exception:
        pass

def poll_single_zone(session, zone_id, drop_tracker):
    zone_data = {}
    detected_label = zone_id
    codes_upper = [c.strip().upper() for c in SAMPLE_CODES if c.strip()]
    strains_upper = [s.strip().upper() for s in STRAIN_FILTERS if s.strip()]

    for date_code in GROWTH_DATES:
        target_url = f"{BASE_FEED_URL}{SCHEDULE_PATH}{zone_id}&dateCode={date_code}"
        try:
            response = session.get(target_url, headers=get_sensor_headers(), timeout=12)
            if response.status_code != 200:
                print(f"  [!] {zone_id} | HTTP {response.status_code} on {date_code}", flush=True)
                if response.status_code == 403:
                    drop_tracker["drops"] += 1
                    if drop_tracker["drops"] >= MAX_CONSECUTIVE_DROPS and not drop_tracker["warned"]:
                        dispatch_alert(
                            f"⚠️ <b>CLOUDFLARE 403 BLOCK DETECTED!</b>\n\n"
                            f"GitHub Actions IP received <code>403 Forbidden</code>.\n"
                            f"🏛 <b>Venue:</b> {zone_id} | <b>Date:</b> {date_code}"
                        )
                        drop_tracker["warned"] = True
                time.sleep(SENSOR_GAP_SECONDS)
                continue

            drop_tracker["drops"] = 0
            drop_tracker["warned"] = False

            payload = response.json()
            if detected_label == zone_id:
                z_name = parse_zone_label(payload)
                if z_name:
                    detected_label = z_name

            raw_units = parse_canopy_nodes(payload)
            units_for_date = {}

            for unit in raw_units:
                unit_id = str(unit.get(K_SESSIONID, "")).strip()
                sample_code = unit.get("_sc", "").strip()
                specimen_title = unit.get("_sn", "").strip()
                raw_strain = unit.get("_sl", "").strip()
                slot_time = unit.get(K_SHOWTIME, "Unknown Time").strip()
                slot_sort = unit.get(K_TIMECODE, "0000")
                attrs = unit.get(K_ATTRS, "").strip().upper() or "STANDARD"
                canopy_name = unit.get(K_SCREEN, "").strip()

                if not unit_id:
                    continue

                matched = False
                if codes_upper and sample_code.upper() in codes_upper:
                    matched = True
                if SPECIMEN_KEYWORD and SPECIMEN_KEYWORD.lower() in specimen_title.lower():
                    matched = True
                if not matched:
                    continue

                strain_label = resolve_strain_label(specimen_title, raw_strain)
                if strains_upper:
                    if not any(st in strain_label.upper() or st in specimen_title.upper() for st in strains_upper):
                        continue

                if CANOPY_FILTER and CANOPY_FILTER.upper() not in attrs and CANOPY_FILTER.upper() not in canopy_name.upper():
                    continue

                display_canopy = f"{attrs} ({canopy_name})" if canopy_name else attrs
                deep_url = f"{BASE_FEED_URL}{DEEP_LINK_SEG_1}{REGION_ID}{DEEP_LINK_SEG_2}{sample_code}/{zone_id}/{unit_id}/{date_code}"

                units_for_date[unit_id] = {
                    "unit_id": unit_id,
                    "slot_time": slot_time,
                    "slot_sort": slot_sort,
                    "canopy": display_canopy,
                    "title": specimen_title or sample_code,
                    "strain": strain_label,
                    "sample_code": sample_code,
                    "deep_url": deep_url
                }

            if units_for_date:
                zone_data[date_code] = units_for_date

        except Exception as e:
            print(f"  [-] {zone_id} | Error checking {date_code}: {e}", flush=True)

        time.sleep(SENSOR_GAP_SECONDS)

    return zone_data, detected_label

def execute_growth_monitor():
    http_session = requests.Session(impersonate="chrome120")
    known_cache = load_telemetry_cache()

    existing_dates_count = sum(len(known_cache.get(z, {})) for z in ZONE_IDS)
    is_fresh_baseline = (existing_dates_count == 0)

    for z_id in ZONE_IDS:
        if z_id not in known_cache:
            known_cache[z_id] = {}
    save_telemetry_cache(known_cache)

    spec_desc = get_specimen_summary()
    strain_desc = ", ".join(STRAIN_FILTERS) if STRAIN_FILTERS else "ALL LANGUAGES"
    canopy_desc = CANOPY_FILTER if CANOPY_FILTER else "ALL SCREENS"

    print("\n" + "=" * 70, flush=True)
    print("       BMS MULTI-VENUE & MULTI-LANGUAGE SHOWTIME WATCHER", flush=True)
    print("=" * 70, flush=True)
    print(f"🏛 Venues Watched : {', '.join(ZONE_IDS)}", flush=True)
    print(f"🎬 Movie Target   : {spec_desc}", flush=True)
    print(f"🗣 Languages      : {strain_desc}", flush=True)
    print(f"🖥 Screen Filter  : {canopy_desc}", flush=True)
    print(f"📅 Dates Watched  : {', '.join(GROWTH_DATES)}", flush=True)
    print(f"⏱ Poll Interval  : {CYCLE_INTERVAL_SECONDS}s (Gap: {SENSOR_GAP_SECONDS}s/req)", flush=True)
    print("=" * 70 + "\n", flush=True)

    dispatch_alert(
        f"👀 <b>BMS Show Watcher Active!</b>\n\n"
        f"🏛 <b>Venues:</b> {', '.join(ZONE_IDS)}\n"
        f"🎬 <b>Target:</b> {spec_desc}\n"
        f"🗣 <b>Languages:</b> {strain_desc}\n"
        f"🖥 <b>Screen:</b> {canopy_desc}\n"
        f"📅 <b>Dates:</b> {', '.join([format_cycle_date(d) for d in GROWTH_DATES])}\n"
        f"⏱ <b>Interval:</b> {CYCLE_INTERVAL_SECONDS}s"
    )

    zone_labels_cache = {z: z for z in ZONE_IDS}
    drop_tracker = {"drops": 0, "warned": False}
    start_ts = time.time()

    try:
        while (time.time() - start_ts) < MAX_SHIFT_SECONDS:
            baseline_blocks = []

            for zone_id in ZONE_IDS:
                timestamp = datetime.datetime.now().strftime("%I:%M:%S %p")
                current_schedule, zone_label = poll_single_zone(http_session, zone_id, drop_tracker)

                if zone_label != zone_id:
                    zone_labels_cache[zone_id] = zone_label
                display_venue = zone_labels_cache[zone_id]

                known_zone_dates = known_cache.get(zone_id, {})
                was_zone_unopened = (len(known_zone_dates) == 0)
                total_active = sum(len(u) for u in current_schedule.values())

                # --------------------------------------------------------------
                # FIRST RUN BASELINE MODE (Summarized without links)
                # --------------------------------------------------------------
                if is_fresh_baseline:
                    if total_active == 0:
                        print(f"[{timestamp}] [BASELINE] {display_venue} ({zone_id}) | No shows open yet.", flush=True)
                        baseline_blocks.append(
                            f"🏛 <b>{display_venue} ({zone_id})</b>\n  • Bookings not open yet."
                        )
                    else:
                        v_lines = [f"🏛 <b>{display_venue} ({zone_id})</b>"]
                        for date_code in sorted(current_schedule.keys()):
                            curr_units = current_schedule[date_code]
                            date_display = format_cycle_date(date_code)

                            s_counts = {}
                            for u in curr_units.values():
                                st = u["strain"]
                                s_counts[st] = s_counts.get(st, 0) + 1
                            s_summary = ", ".join([f"{k}: {v}" for k, v in s_counts.items()])

                            v_lines.append(
                                f"  • <b>{date_display}:</b> {len(curr_units)} show(s) [<code>{s_summary}</code>]"
                            )
                            print(
                                f"[{timestamp}] [BASELINE] {display_venue} | {date_display} | Recorded {len(curr_units)} existing show(s) [{s_summary}]",
                                flush=True
                            )
                            # Store ONLY sanitized unit_id list in startrail.json
                            known_zone_dates[date_code] = list(curr_units.keys())

                        known_cache[zone_id] = known_zone_dates
                        save_telemetry_cache(known_cache)
                        baseline_blocks.append("\n".join(v_lines))
                    continue

                # --------------------------------------------------------------
                # NORMAL MONITORING MODE
                # --------------------------------------------------------------
                if total_active == 0:
                    print(f"[{timestamp}] {display_venue} ({zone_id}) | Bookings not open yet.", flush=True)
                else:
                    for date_code in sorted(current_schedule.keys()):
                        curr_units = current_schedule[date_code]
                        date_display = format_cycle_date(date_code)

                        if date_code not in known_zone_dates:
                            header = "🎉 <b>BOOKINGS JUST OPENED!</b>" if was_zone_unopened else "📅 <b>NEW DATE OPENED!</b>"
                            grouped_text = format_grouped_units_alert(list(curr_units.values()))

                            alert_msg = (
                                f"{header}\n\n"
                                f"🏛 <b>Venue:</b> {display_venue} ({zone_id})\n"
                                f"📅 <b>Date:</b> {date_display}\n"
                                f"🎟 <b>Total Shows Added:</b> {len(curr_units)}\n\n"
                                f"{grouped_text}"
                            )
                            dispatch_alert(alert_msg)
                            print(f"[{timestamp}] 🚨 ALERT! {display_venue} | New Date: {date_display} ({len(curr_units)} shows)", flush=True)

                            known_zone_dates[date_code] = list(curr_units.keys())
                            known_cache[zone_id] = known_zone_dates
                            save_telemetry_cache(known_cache)
                            was_zone_unopened = False
                        else:
                            prev_unit_ids = set(known_zone_dates[date_code])
                            new_units = [
                                u_data for u_id, u_data in curr_units.items()
                                if u_id not in prev_unit_ids
                            ]

                            if new_units:
                                grouped_new_text = format_grouped_units_alert(new_units)

                                alert_msg = (
                                    f"➕ <b>NEW SHOWTIME(S) ADDED!</b>\n\n"
                                    f"🏛 <b>Venue:</b> {display_venue} ({zone_id})\n"
                                    f"📅 <b>Date:</b> {date_display}\n"
                                    f"🎟 <b>New Shows Added:</b> {len(new_units)}\n\n"
                                    f"{grouped_new_text}"
                                )
                                dispatch_alert(alert_msg)
                                print(f"[{timestamp}] 🚨 ALERT! {display_venue} | +{len(new_units)} new show(s) on {date_display}!", flush=True)

                                combined_ids = list(prev_unit_ids.union(curr_units.keys()))
                                known_zone_dates[date_code] = combined_ids
                                known_cache[zone_id] = known_zone_dates
                                save_telemetry_cache(known_cache)
                            else:
                                s_counts = {}
                                for u in curr_units.values():
                                    st = u["strain"]
                                    s_counts[st] = s_counts.get(st, 0) + 1
                                s_summary = ", ".join([f"{k}: {v}" for k, v in s_counts.items()])
                                print(f"[{timestamp}] {display_venue} | {date_display} | {len(curr_units)} show(s) [{s_summary}] (No changes)", flush=True)

            if is_fresh_baseline:
                summary_msg = (
                    f"📋 <b>Initial Baseline Snapshot (Existing Shows)</b>\n\n"
                    + "\n\n".join(baseline_blocks)
                    + "\n\n✅ <i>Baseline saved. You will only be notified with links when NEW dates or NEW showtimes are added!</i>"
                )
                dispatch_alert(summary_msg)
                is_fresh_baseline = False

            print("-" * 70, flush=True)
            time.sleep(CYCLE_INTERVAL_SECONDS)

        send_halt_notice("Completed 6-Hour Cycle (Relaying to next runner)")

    except KeyboardInterrupt:
        print("\n[!] Stopping Show Watcher...", flush=True)
        send_halt_notice("Manual Stop (Ctrl+C)")
        sys.exit(0)
    except Exception:
        raise

if __name__ == "__main__":
    if "--halt-notice" in sys.argv:
        reason = sys.argv[-1] if len(sys.argv) > 1 else "Unknown"
        send_halt_notice(reason)
    else:
        execute_growth_monitor()
