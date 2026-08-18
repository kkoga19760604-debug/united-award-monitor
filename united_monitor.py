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

# Try importing requests and playwright, handle gracefully if missing
try:
    import requests
except ImportError:
    requests = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

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

    # ★監視対象の月数（今月〜11ヶ月先までの計12ヶ月分）
    "SEARCH_MONTHS_COUNT": 12,

    # ★乗継用ハブ空港
    "HUB_AIRPORTS": ["ITM", "HND", "NGO", "KIX", "FUK", "CTS", "OKA"],

    # ★GoogleスプレッドシートID
    "SPREADSHEET_ID": os.environ.get("SPREADSHEET_ID", "1gL7HdNzZ4-xa629L7GR20XC-0FJCS93rfp9PCAtKAkk"),

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
    # 3文字の英大文字空港コードを検索 (例: "KMJ (熊本)" -> "KMJ")
    match = re.search(r'^[A-Za-z]{3}', s)
    if match:
        return match.group(0).upper()
    
    # カッコ内の3文字コードを検索 (例: "熊本 (KMJ)")
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

    # 1. 外部APIから祝日取得試行
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

    # 2. 内蔵計算によるフォールバック (主要祝日)
    # 固定祝日
    fixed_holidays = [
        (1, 1),   # 元日
        (2, 11),  # 建国記念の日
        (2, 23),  # 天皇誕生日
        (4, 29),  # 昭和の日
        (5, 3),   # 憲法記念日
        (5, 4),   # みどりの日
        (5, 5),   # こどもの日
        (11, 3),  # 文化の日
        (11, 23), # 勤労感謝の日
    ]
    for month, day in fixed_holidays:
        holidays.add(f"{year}-{month:02d}-{day:02d}")

    # ハッピーマンデー (成人の日:1月第2月曜, 海の日:7月第3月曜, 敬老の日:9月第3月曜, スポーツの日:10月第2月曜)
    def happy_monday(m, nth):
        first = datetime(year, m, 1)
        w = first.weekday()
        day = 1 + (7 - w) % 7 + (nth - 1) * 7
        return f"{year}-{m:02d}-{day:02d}"

    holidays.add(happy_monday(1, 2))  # 成人の日
    holidays.add(happy_monday(7, 3))  # 海の日
    holidays.add(happy_monday(9, 3))  # 敬老の日
    holidays.add(happy_monday(10, 2)) # スポーツの日

    # 春分の日・秋分の日概算
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
# 日付条件マッチング関数
# ==========================================
def matches_date_condition(dt, condition_str):
    if not condition_str or condition_str.strip() in ["すべて", "全日", ""]:
        return True

    day_of_week = dt.weekday() # 0:月, 1:火, 2:水, 3:木, 4:金, 5:土, 6:日
    date_str = dt.strftime("%Y-%m-%d")
    is_holiday = is_japanese_holiday(dt)

    conditions = [c.strip() for c in condition_str.split(",")]

    for cond in conditions:
        if cond == date_str:
            return True
        if cond in ["月", "月曜", "月曜日"] and day_of_week == 0:
            return True
        if cond in ["火", "火曜", "火曜日"] and day_of_week == 1:
            return True
        if cond in ["水", "水曜", "水曜日"] and day_of_week == 2:
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
# スプレッドシート取得＆パース (堅牢版)
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
                    # HTMLエラーページでないか確認
                    if "<html" not in text.lower() and len(text) > 10:
                        csv_text = text
                        print(f"✅ スプレッドシート取得成功 (URL: {url[:60]}...)")
                        break
        except Exception as e:
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

    # フォールバック処理: スプレッドシートが取得できない場合はデフォルトの「KMJ -> SDJ」で動作
    if not targets:
        print("⚠️ 有効なスプレッドシートデータが取得できなかったため、デフォルト路線 [KMJ -> SDJ] で動作します。")
        targets = [
            {
                "row": 2,
                "origin": "KMJ",
                "destination": "SDJ",
                "date_cond": "すべて",
                "cabin": "エコノミー",
                "note": "熊本(KMJ) ➡️ 仙台(SDJ) [自動監視]"
            }
        ]

    print(f"✅ 対象監視ルート {len(targets)} 件を読み込みました。")
    for t in targets:
        print(f"   • {t['origin']} ➡️ {t['destination']} (条件: {t['date_cond']})")

    return targets

# ==========================================
# 【万能パースエンジン】JSON構造を問わず空席全抽出
# ==========================================
def parse_availability_universal(obj, ym_str):
    results = []
    if not obj:
        return results

    def format_date(val):
        if not val:
            return None
        s = str(val).strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
            return s
        if re.match(r'^\d{8}$', s):
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        if re.match(r'^\d{1,2}$', s) and 1 <= int(s) <= 31:
            day_padded = s.zfill(2)
            return f"{ym_str[:4]}-{ym_str[4:6]}-{day_padded}"
        return None

    def check_status(status_val, item_obj):
        if isinstance(item_obj, dict):
            if item_obj.get("vacant") is True or item_obj.get("available") is True or item_obj.get("isVacant") is True:
                return True
        s = str(status_val).upper().strip()
        if any(keyword in s for keyword in ["OK", "LOW", "○", "△", "AVAILABLE", "TRUE", "7K", "5.5K", "空席あり", "予約可"]):
            return True
        return False

    def traverse(o):
        if not o:
            return
        if isinstance(o, list):
            for item in o:
                traverse(item)
        elif isinstance(o, dict):
            date_val = o.get("date") or o.get("flightDate") or o.get("ymd") or o.get("day") or o.get("depDate")
            status_val = o.get("status") or o.get("vacantStatus") or o.get("availability") or o.get("seatStatus") or o.get("vacant")
            
            if date_val is not None and status_val is not None:
                d_str = format_date(date_val)
                if d_str:
                    results.append({"date": d_str, "available": check_status(status_val, o)})

            for k, v in o.items():
                d_str_key = format_date(k)
                if d_str_key and isinstance(v, (dict, list, str, bool, int)):
                    results.append({"date": d_str_key, "available": check_status(v, v if isinstance(v, dict) else o)})
                else:
                    traverse(v)

    traverse(obj)

    # 日付ごとのユニーク化（1つでもavailable=Trueがあれば優先）
    unique_map = {}
    for r in results:
        d = r["date"]
        if d not in unique_map or r["available"]:
            unique_map[d] = r

    return list(unique_map.values())

# ==========================================
# 通信・照会処理
# ==========================================
def fetch_route_data(dep, arr, ym_str):
    url = f"https://www.ana.co.jp/asw/top_dom/asw_top_dom_inquire_round_flight.json?depCode={dep}&arrCode={arr}&searchMonth={ym_str}"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "application/json, text/javascript, */*"
    }
    
    try:
        if requests:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200 and res.text:
                try:
                    data = res.json()
                    return parse_availability_universal(data, ym_str)
                except Exception:
                    pass
        else:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as res:
                if res.status == 200:
                    text = res.read().decode('utf-8', errors='ignore')
                    data = json.loads(text)
                    return parse_availability_universal(data, ym_str)
    except Exception:
        pass

    return []

# ==========================================
# Playwright ブラウザ補完検索 (ブロック回避設定付き)
# ==========================================
def check_united_with_playwright(origin, destination, dates_to_check):
    if not sync_playwright or not dates_to_check:
        return []

    found_seats = []
    print(f" 🌐 Playwright による United 公式補完照会開始 ({origin} -> {destination}, {len(dates_to_check)} 日分)")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-http2',
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox'
                ]
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800},
                extra_http_headers={
                    'Accept-Language': 'ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7',
                    'Sec-Ch-Ua': '"Chromium";v="122", "Google Chrome";v="122"',
                    'Sec-Ch-Ua-Mobile': '?0',
                    'Sec-Ch-Ua-Platform': '"macOS"'
                }
            )
            page = context.new_page()

            for dt in dates_to_check[:10]: # 安全のため最大10日分に制限
                date_str = dt.strftime("%Y-%m-%d")
                url = f"https://www.united.com/ja/jp/fsr/choose-flights?f={origin}&t={destination}&d={date_str}&tt=1&at=1&sc=7&px=1&taxng=1"
                
                try:
                    res = page.goto(url, timeout=25000, wait_until="domcontentloaded")
                    time.sleep(3)
                    content = page.content()
                    text = page.evaluate("() => document.body.innerText")

                    if any(kw in content or kw in text for kw in ["7k", "5.5k", "6k", "7,000", "5,500"]):
                        found_seats.append(date_str)
                        print(f"   🎉 United公式で空席検知: {date_str}")
                except Exception as e:
                    print(f"   ⚠️ {date_str} 照会タイムアウト/スキップ")
                    
            browser.close()
    except Exception as e:
        print(f" ⚠️ Playwright 実行エラー: {e}")

    return found_seats

# ==========================================
# メイン空席確認処理
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

    # 今月から指定月数（12ヶ月分）の yyyyMM を生成
    now = datetime.now()
    month_count = CONFIG["SEARCH_MONTHS_COUNT"] or 12
    target_months = []
    for m in range(month_count):
        # 年月繰り上がり考慮
        year = now.year + (now.month - 1 + m) // 12
        month = (now.month - 1 + m) % 12 + 1
        target_months.append(f"{year}{month:02d}")

    print(f"\n[監視開始] 対象期間: {target_months[0]} 〜 {target_months[-1]} ({len(target_months)}ヶ月分)")

    hub_airports = CONFIG["HUB_AIRPORTS"]
    request_keys_map = {}

    # 全APIリクエストキーの事前作成
    for row in targets:
        for ym in target_months:
            # 直行便
            k_direct = f"{row['origin']}_{row['destination']}_{ym}"
            request_keys_map[k_direct] = {"dep": row["origin"], "arr": row["destination"], "ym": ym}

            # 乗継便
            for hub in hub_airports:
                if hub != row["origin"] and hub != row["destination"]:
                    k_leg1 = f"{row['origin']}_{hub}_{ym}"
                    k_leg2 = f"{hub}_{row['destination']}_{ym}"
                    request_keys_map[k_leg1] = {"dep": row["origin"], "arr": hub, "ym": ym}
                    request_keys_map[k_leg2] = {"dep": hub, "arr": row["destination"], "ym": ym}

    request_keys = list(request_keys_map.keys())
    print(f"⚡ 全 {len(request_keys)} リクエストを並列高速取得中...")

    api_cache = {}
    # 並列通信実行 (ThreadPoolExecutor)
    with ThreadPoolExecutor(max_workers=15) as executor:
        future_to_key = {
            executor.submit(
                fetch_route_data,
                request_keys_map[k]["dep"],
                request_keys_map[k]["arr"],
                request_keys_map[k]["ym"]
            ): k for k in request_keys
        }

        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                data = future.result()
                api_cache[key] = data
            except Exception:
                api_cache[key] = []

    print("✅ 全通信データ読み込み完了！ マッチング判定中...")

    all_detected_seats = []

    for row in targets:
        route_detected = []
        for ym in target_months:
            # 1. 直行便
            direct_key = f"{row['origin']}_{row['destination']}_{ym}"
            direct_data = api_cache.get(direct_key, [])
            for item in direct_data:
                if not item["available"]:
                    continue
                try:
                    target_dt = datetime.strptime(item["date"], "%Y-%m-%d")
                    # 今日の日付以降のみを対象
                    if target_dt.date() >= now.date() and matches_date_condition(target_dt, row["date_cond"]):
                        all_detected_seats.append({
                            "origin": row["origin"],
                            "destination": row["destination"],
                            "date": item["date"],
                            "via": None,
                            "direct": True,
                            "note": row["note"]
                        })
                except Exception:
                    pass

            # 2. 乗継便 (各ハブ経由)
            for hub in hub_airports:
                if hub in [row["origin"], row["destination"]]:
                    continue
                leg1_key = f"{row['origin']}_{hub}_{ym}"
                leg2_key = f"{hub}_{row['destination']}_{ym}"

                leg1_data = api_cache.get(leg1_key, [])
                leg2_data = api_cache.get(leg2_key, [])

                if leg1_data and leg2_data:
                    # 日付マップ化
                    leg2_dates = {item["date"]: item["available"] for item in leg2_data}

                    for leg1 in leg1_data:
                        if not leg1["available"]:
                            continue
                        d_str = leg1["date"]
                        if leg2_dates.get(d_str) is True:
                            try:
                                target_dt = datetime.strptime(d_str, "%Y-%m-%d")
                                if target_dt.date() >= now.date() and matches_date_condition(target_dt, row["date_cond"]):
                                    all_detected_seats.append({
                                        "origin": row["origin"],
                                        "destination": row["destination"],
                                        "date": d_str,
                                        "via": hub,
                                        "direct": False,
                                        "note": row["note"]
                                    })
                            except Exception:
                                pass

    print(f"🎯 検出された条件一致特典空席: 全 {len(all_detected_seats)} 件")

    # Discordまとめ通知の送信
    send_discord_summary_notification(all_detected_seats)
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
# Discord 一括まとめ通知送信
# ==========================================
def send_discord_summary_notification(detected_list):
    webhook_url = CONFIG["DISCORD_WEBHOOK_URL"]
    if not webhook_url:
        return

    if not detected_list:
        print("条件に合う特典空席は見つかりませんでした。")
        return

    # 重複排除 (Origin, Destination, Date, Via)
    unique_map = {}
    for item in detected_list:
        key = f"{item['origin']}_{item['destination']}_{item['date']}_{item['via'] or 'DIRECT'}"
        if key not in unique_map:
            unique_map[key] = item
    cleaned_list = list(unique_map.values())
    cleaned_list.sort(key=lambda x: x["date"])

    # 通知内容のMD5ハッシュ作成による重複チェック
    summary_bytes = json.dumps(cleaned_list, sort_keys=True).encode('utf-8')
    summary_hash = hashlib.md5(summary_bytes).hexdigest()

    last_hash = ""
    if os.path.exists(CONFIG["CACHE_FILE"]):
        try:
            with open(CONFIG["CACHE_FILE"], "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                last_hash = cache_data.get("last_summary_hash", "")
        except Exception:
            pass

    if last_hash == summary_hash:
        print("ℹ️ 前回通知内容と変化がないため、Discord通知をスキップします。")
        return

    # 路線ごとにグループ化
    grouped = {}
    for item in cleaned_list:
        route_key = f"{item['origin']} ➡️ {item['destination']}"
        if route_key not in grouped:
            grouped[route_key] = []
        grouped[route_key].append(item)

    embeds = []
    for route, items in grouped.items():
        direct_items = [f"・**{format_date_with_day(x['date'])}** [直行便]" for x in items if x["direct"]]
        connect_items = [f"・**{format_date_with_day(x['date'])}** [経由: {x['via']}]" for x in items if not x["direct"]]

        desc = f"**条件一致 空席件数: 全 {len(items)} 件**\n\n"
        if direct_items:
            desc += f"✈️ **【直行便 空席日程】**\n" + "\n".join(direct_items[:30]) + "\n\n"
        if connect_items:
            desc += f"🔄 **【乗継便 空席日程】**\n" + "\n".join(connect_items[:40]) + "\n\n"

        notes = list(set([x["note"] for x in items if x["note"]]))
        if notes:
            desc += f"📝 **備考**: {', '.join(notes)}"

        embeds.append({
            "title": f"✈️ 【United特典空席 一覧レポート】 {route}",
            "color": 5814783,
            "description": desc,
            "footer": {"text": "United特典航空券 高速一括監視システム (必要マイル目安: 5,500〜7,000マイル)"},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    payload = {
        "username": "United特典航空券 監視",
        "embeds": embeds[:10] # Discord制限 10 Embeds
    }

    mention = CONFIG.get("DISCORD_MENTION", "").strip()
    if mention:
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
                print(f"🎉 Discordまとめ一括通知完了！（検出件数: {len(cleaned_list)} 件）")
                # キャッシュの更新
                with open(CONFIG["CACHE_FILE"], "w", encoding="utf-8") as f:
                    json.dump({"last_summary_hash": summary_hash, "updated_at": datetime.now().isoformat()}, f)
            else:
                print(f"⚠️ Discord通知応答ステータス: {res.status}")
    except Exception as e:
        print(f"❌ Discord通知送信エラー: {e}")

# ==========================================
# エントリーポイント
# ==========================================
if __name__ == "__main__":
    check_united_seats_free()
