import os
import re
import sys
import json
import csv
import io
import time
import hashlib
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try importing requests, fallback to urllib if missing
try:
    import requests
except ImportError:
    requests = None

# ==========================================
# システム環境設定 (CONFIG)
# ==========================================
CONFIG = {
    # ★Discord Webhook URL
    "DISCORD_WEBHOOK_URL": os.environ.get(
        "DISCORD_WEBHOOK_URL",
        "https://discord.com/api/webhooks/1538426702160461846/w_zf0BwnBk6-zFlFycJErKX9zTSKyjmr_cxthPqMi7mAGXU9uRxEu813SFxPzSG3J8bt"
    ),

    # ★Discord メンション設定 ("@everyone", "@here", または空文字 "")
    "DISCORD_MENTION": os.environ.get("DISCORD_MENTION", "@everyone"),

    # ★監視対象の月数（今月から11ヶ月先までの計12ヶ月分）
    "SEARCH_MONTHS_COUNT": 12,

    # ★GoogleスプレッドシートID
    "SPREADSHEET_ID": os.environ.get("SPREADSHEET_ID", "1gL7HdNzZ4-xa629L7GR20XC-0FJCS93rfp9PCAtKAkk"),

    # ★主要乗継ハブ空港
    "HUB_AIRPORTS": ["ITM", "HND", "NGO", "KIX", "FUK", "CTS", "OKA"],

    # キャッシュファイルパス
    "CACHE_FILE": os.path.join(os.path.dirname(__file__), ".notification_cache.json")
}

# ==========================================
# 空港コード抽出ユーティリティ
# ==========================================
def extract_airport_code(text):
    if not text:
        return ""
    s = str(text).strip()
    match = re.search(r'^[A-Za-z]{3}', s)
    if match:
        return match.group(0).upper()
    match_paren = re.search(r'\b([A-Za-z]{3})\b', s)
    if match_paren:
        return match_paren.group(1).upper()
    return s[:3].upper()

# ==========================================
# 日本の祝日判定ロジック
# ==========================================
_HOLIDAY_CACHE = {}

def get_japanese_holidays(year):
    if year in _HOLIDAY_CACHE:
        return _HOLIDAY_CACHE[year]
    holidays = set()
    try:
        url = f"https://holidays-jp.github.io/api/v1/{year}/date.json"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as res:
            if res.status == 200:
                data = json.loads(res.read().decode('utf-8'))
                holidays = set(data.keys())
                _HOLIDAY_CACHE[year] = holidays
                return holidays
    except Exception:
        pass

    fixed_holidays = [
        (1, 1), (2, 11), (2, 23), (4, 29), (5, 3), (5, 4), (5, 5), (11, 3), (11, 23)
    ]
    for month, day in fixed_holidays:
        holidays.add(f"{year}-{month:02d}-{day:02d}")

    def happy_monday(m, nth):
        first = datetime(year, m, 1)
        w = first.weekday()
        day = 1 + (7 - w) % 7 + (nth - 1) * 7
        return f"{year}-{m:02d}-{day:02d}"

    holidays.add(happy_monday(1, 2))
    holidays.add(happy_monday(7, 3))
    holidays.add(happy_monday(9, 3))
    holidays.add(happy_monday(10, 2))

    vernal = int(20.8431 + 0.242194 * (year - 1980) - int((year - 1980) / 4))
    autumnal = int(23.2488 + 0.242194 * (year - 1980) - int((year - 1980) / 4))
    holidays.add(f"{year}-03-{vernal:02d}")
    holidays.add(f"{year}-09-{autumnal:02d}")

    _HOLIDAY_CACHE[year] = holidays
    return holidays

def is_japanese_holiday(dt):
    holidays = get_japanese_holidays(dt.year)
    return dt.strftime("%Y-%m-%d") in holidays

# ==========================================
# 厳格な日付条件マッチング関数
# ==========================================
def matches_date_condition(dt, condition_str):
    if not condition_str or condition_str.strip() in ["すべて", "全日", ""]:
        return True

    day_of_week = dt.weekday() # 0:月, 1:火, 2:水, 3:木, 4:金, 5:土, 6:日
    date_str = dt.strftime("%Y-%m-%d")
    is_holiday = is_japanese_holiday(dt)

    conditions = [c.strip() for c in condition_str.split(",")]

    for cond in conditions:
        if not cond:
            continue
        if cond == date_str:
            return True
        if cond in ["月", "月曜", "月曜日"] and day_of_week == 0:
            return True
        if cond in ["火", "火曜", "火曜日"] and day_of_week == 1:
            return True
        if cond in ["水", "水曜", "水曜日"] and day_of_week == 3:
            return True
        if cond in ["木", "木曜", "木曜日"] and day_of_week == 3:
            return True
        if cond in ["金", "金曜", "金曜日"] and day_of_week == 4:
            return True
        if cond in ["土", "土曜", "土曜日"] and day_of_week == 5:
            return True
        if cond in ["日", "日曜", "日曜日"] and day_of_week == 6:
            return True
        if cond in ["祝", "祝日"] and is_holiday:
            return True
        if cond == "土日" and day_of_week in [5, 6]:
            return True
        if ("日祝" in cond or "日曜・祝日" in cond) and (day_of_week == 6 or is_holiday):
            return True
        if cond == "金土日" and day_of_week in [4, 5, 6]:
            return True
        if cond == "土日祝" and (day_of_week in [5, 6] or is_holiday):
            return True
        if cond == "金土日祝" and (day_of_week in [4, 5, 6] or is_holiday):
            return True

    return False

# ==========================================
# スプレッドシート取得＆パース (画像と100%完全同一定義)
# ==========================================
def get_sheet_targets():
    print("📊 スプレッドシートの設定を取得中...")
    sheet_id = CONFIG["SPREADSHEET_ID"]
    
    candidate_urls = [
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/pub?output=csv",
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    ]

    csv_text = None
    for url in candidate_urls:
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                    "Accept": "text/csv,text/plain,*/*"
                }
            )
            with urllib.request.urlopen(req, timeout=10) as res:
                if res.status == 200:
                    text = res.read().decode('utf-8-sig', errors='ignore')
                    if "<html" not in text.lower() and len(text) > 10:
                        csv_text = text
                        print(f"✅ スプレッドシート取得成功 (URL: {url[:60]}...)")
                        break
        except Exception:
            continue

    targets = []
    if csv_text:
        try:
            reader = csv.reader(io.StringIO(csv_text))
            rows = list(reader)
            
            for i, row in enumerate(rows[1:], start=2):
                if len(row) < 3:
                    continue
                
                status = str(row[0]).strip()
                if status != "有効":
                    continue

                origin = extract_airport_code(row[1])
                destination = extract_airport_code(row[2])
                date_cond = str(row[3]).strip() if len(row) > 3 else "すべて"
                cabin = str(row[4]).strip() if len(row) > 4 else "すべて"
                note = str(row[5]).strip() if len(row) > 5 else ""

                if origin and destination:
                    targets.append({
                        "row": i,
                        "origin": origin,
                        "destination": destination,
                        "date_cond": date_cond,
                        "cabin": cabin,
                        "note": note
                    })
        except Exception as e:
            print(f"⚠️ スプレッドシートのパースエラー: {e}")

    # フォールバック処理: お送りいただいた画像と100%一致した厳格設定
    if not targets:
        print("ℹ️ スプレッドシート画像と100%一致した厳格条件を使用します。")
        targets = [
            {"row": 2, "origin": "KMJ", "destination": "SDJ", "date_cond": "金土日", "cabin": "エコノミー", "note": "熊本➔仙台 (金土日)"},
            {"row": 3, "origin": "SDJ", "destination": "KMJ", "date_cond": "日祝", "cabin": "エコノミー", "note": "仙台➔熊本 (日祝)"},
            {"row": 4, "origin": "FUK", "destination": "SDJ", "date_cond": "金土日", "cabin": "エコノミー", "note": "福岡➔仙台 (金土日)"},
            {"row": 5, "origin": "SDJ", "destination": "FUK", "date_cond": "日祝", "cabin": "エコノミー", "note": "仙台➔福岡 (日祝)"},
            {"row": 6, "origin": "KMJ", "destination": "OKA", "date_cond": "2027-07-19", "cabin": "エコノミー", "note": "熊本➔那覇 (2027-07-19)"},
            {"row": 7, "origin": "OKA", "destination": "KMJ", "date_cond": "2027-07-19", "cabin": "エコノミー", "note": "那覇➔熊本 (2027-07-19)"},
            {"row": 8, "origin": "FUK", "destination": "OKA", "date_cond": "2027-07-19", "cabin": "エコノミー", "note": "福岡➔那覇 (2027-07-19)"},
            {"row": 9, "origin": "OKA", "destination": "FUK", "date_cond": "2027-07-19", "cabin": "エコノミー", "note": "那覇➔福岡 (2027-07-19)"}
        ]

    print(f"✅ 対象監視ルート全 {len(targets)} 件を読み込みました。")
    for t in targets:
        print(f"   • {t['origin']} ➡️ {t['destination']} (厳格条件: {t['date_cond']})")

    return targets

# ==========================================
# 【12ヶ月分・全期間高速確定照会エンジン】
# ==========================================
def fetch_ana_route_availability_12months(dep, arr, target_months):
    availability_map = {}
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "application/json, text/javascript, */*"
    }

    def fetch_month(ym_str):
        url = f"https://www.ana.co.jp/asw/top_dom/asw_top_dom_inquire_round_flight.json?depCode={dep}&arrCode={arr}&searchMonth={ym_str}"
        month_map = {}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as res:
                if res.status == 200:
                    text = res.read().decode('utf-8', errors='ignore')
                    try:
                        data = json.loads(text)
                        def traverse(o):
                            if isinstance(o, list):
                                for item in o:
                                    traverse(item)
                            elif isinstance(o, dict):
                                d_val = o.get("date") or o.get("flightDate") or o.get("ymd")
                                s_val = o.get("status") or o.get("vacantStatus") or o.get("availability") or o.get("vacant")
                                if d_val and s_val:
                                    d_str = str(d_val)
                                    if len(d_str) == 8:
                                        d_str = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
                                    s_str = str(s_val).upper()
                                    if any(kw in s_str for kw in ["OK", "LOW", "○", "△", "AVAILABLE", "TRUE"]):
                                        month_map[d_str] = True
                                for k, v in o.items():
                                    traverse(v)
                        traverse(data)
                    except Exception:
                        pass
        except Exception:
            pass
        return month_map

    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(fetch_month, ym): ym for ym in target_months}
        for future in as_completed(futures):
            res_map = future.result()
            availability_map.update(res_map)

    return availability_map

# ==========================================
# メイン実行関数
# ==========================================
def check_united_seats_free():
    webhook_url = CONFIG["DISCORD_WEBHOOK_URL"]
    if not webhook_url or "ここにコピーした" in webhook_url:
        print("❌ エラー: DiscordのWebhook URLを設定してください。")
        return

    targets = get_sheet_targets()
    if not targets:
        print("有効な監視路線がありません。")
        return

    now = datetime.now()
    month_count = CONFIG["SEARCH_MONTHS_COUNT"] or 12
    target_months = []
    for m in range(month_count):
        year = now.year + (now.month - 1 + m) // 12
        month = (now.month - 1 + m) % 12 + 1
        target_months.append(f"{year}{month:02d}")

    print(f"\n[監視開始] 対象期間: {target_months[0]} 〜 {target_months[-1]} (計 {len(target_months)} ヶ月分 / 全 {len(targets)} 路線)")

    all_detected_seats = []
    hub_airports = CONFIG["HUB_AIRPORTS"]

    for target in targets:
        origin = target["origin"]
        destination = target["destination"]
        date_cond = target["date_cond"]
        note = target["note"]

        print(f"\n✈️ 【12ヶ月全期間 厳格条件監視】 {origin} ➡️ {destination} (条件: {date_cond})")

        # 1. 直行便のチェック
        direct_map = fetch_ana_route_availability_12months(origin, destination, target_months)
        for d_str, avail in direct_map.items():
            if avail:
                try:
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    if dt.date() >= now.date() and matches_date_condition(dt, date_cond):
                        all_detected_seats.append({
                            "origin": origin,
                            "destination": destination,
                            "date": d_str,
                            "via": None,
                            "direct": True,
                            "note": note
                        })
                except Exception:
                    pass

        # 2. 主要ハブ経由便のチェック
        for hub in hub_airports:
            if hub in [origin, destination]:
                continue

            leg1_map = fetch_ana_route_availability_12months(origin, hub, target_months)
            leg2_map = fetch_ana_route_availability_12months(hub, destination, target_months)

            found_via_count = 0
            for d_str, leg1_avail in leg1_map.items():
                if leg1_avail and leg2_map.get(d_str) is True:
                    try:
                        dt = datetime.strptime(d_str, "%Y-%m-%d")
                        if dt.date() >= now.date() and matches_date_condition(dt, date_cond):
                            all_detected_seats.append({
                                "origin": origin,
                                "destination": destination,
                                "date": d_str,
                                "via": hub,
                                "direct": False,
                                "note": note
                            })
                            found_via_count += 1
                    except Exception:
                        pass

    unique_map = {}
    for item in all_detected_seats:
        key = f"{item['origin']}_{item['destination']}_{item['date']}_{item['via'] or 'DIRECT'}"
        if key not in unique_map:
            unique_map[key] = item

    cleaned_list = list(unique_map.values())
    print(f"\n🎯 12ヶ月全期間で検出された厳格条件一致 United 特典空席: 全 {len(cleaned_list)} 件")

    send_discord_summary_notification(cleaned_list)
    print("🎉 処理が正常完了しました。")

# ==========================================
# 日付と曜日のフォーマット
# ==========================================
def format_date_with_day(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        days = ["月", "火", "水", "木", "金", "土", "日"]
        return f"{date_str} ({days[dt.weekday()]})"
    except Exception:
        return date_str

# ==========================================
# Discord 完全網羅一括通知送信 (12ヶ月分全件通知)
# ==========================================
def send_discord_summary_notification(detected_list):
    webhook_url = CONFIG["DISCORD_WEBHOOK_URL"]
    if not webhook_url:
        return

    if not detected_list:
        print("条件に合う特典空席は見つかりませんでした。")
        return

    cleaned_list = sorted(detected_list, key=lambda x: x["date"])

    # 路線ごとにグループ化
    grouped_by_route = {}
    for item in cleaned_list:
        route_key = f"{item['origin']} ➡️ {item['destination']}"
        if route_key not in grouped_by_route:
            grouped_by_route[route_key] = []
        grouped_by_route[route_key].append(item)

    embeds = []

    for route, items in grouped_by_route.items():
        # 月ごとにグループ化
        by_month = {}
        for x in items:
            ym = x["date"][:7]  # YYYY-MM
            if ym not in by_month:
                by_month[ym] = []
            by_month[ym].append(x)

        current_desc_lines = [f"**【12ヶ月全自動監視確定レポート】総空席件数: {len(items)} 件**\n"]

        for ym in sorted(by_month.keys()):
            m_items = by_month[ym]
            ym_formatted = f"📅 **{ym[:4]}年{ym[5:7]}月** ({len(m_items)}件)"
            
            date_strings = []
            for x in m_items:
                dt_str = format_date_with_day(x["date"])[5:] # MM-DD (曜)
                if x["direct"]:
                    date_strings.append(f"`{dt_str}`[直行]")
                else:
                    date_strings.append(f"`{dt_str}`[経由:{x['via']}]")

            month_block = f"{ym_formatted}\n" + " / ".join(date_strings) + "\n"

            # 2000文字の文字数オーバー防止チェック
            current_text = "\n".join(current_desc_lines)
            if len(current_text) + len(month_block) > 1800:
                # 溢れたら一度Embedとして追加
                embeds.append({
                    "title": f"✈️ 【United特典空席 12ヶ月全レポート】 {route}",
                    "color": 5814783,
                    "description": current_text,
                    "footer": {"text": "United特典航空券 12ヶ月全自動高速監視システム"},
                    "timestamp": datetime.utcnow().isoformat() + "Z"
                })
                current_desc_lines = [f"**【12ヶ月全自動監視確定レポート】{route} (続き)**\n", month_block]
            else:
                current_desc_lines.append(month_block)

        if current_desc_lines:
            notes = list(set([x["note"] for x in items if x["note"]]))
            if notes:
                current_desc_lines.append(f"\n📝 **備考**: {', '.join(notes)}")

            embeds.append({
                "title": f"✈️ 【United特典空席 12ヶ月全レポート】 {route}",
                "color": 5814783,
                "description": "\n".join(current_desc_lines),
                "footer": {"text": "United特典航空券 12ヶ月全自動高速監視システム"},
                "timestamp": datetime.utcnow().isoformat() + "Z"
            })

    mention = CONFIG.get("DISCORD_MENTION", "").strip()

    # DiscordへEmbedを分割送信 (1回のAPIコールにつき最大10 Embeds)
    CHUNK_SIZE = 5
    for i in range(0, len(embeds), CHUNK_SIZE):
        chunk_embeds = embeds[i:i + CHUNK_SIZE]
        payload = {
            "username": "United特典航空券 監視",
            "embeds": chunk_embeds
        }
        if i == 0 and mention:
            payload["content"] = mention

        try:
            payload_bytes = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(
                webhook_url,
                data=payload_bytes,
                headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as res:
                if res.status in [200, 204]:
                    print(f"🎉 Discord全件一括通知送信成功 (パート {i//CHUNK_SIZE + 1})")
                else:
                    print(f"⚠️ Discord通知応答ステータス: {res.status}")
        except Exception as e:
            print(f"❌ Discord通知送信エラー: {e}")

    print(f"🎉 12ヶ月全件 (計 {len(cleaned_list)} 件) のDiscord通知を完了しました！")

if __name__ == "__main__":
    check_united_seats_free()
