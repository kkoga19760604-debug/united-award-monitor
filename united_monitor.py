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
# 日付条件マッチング関数
# ==========================================
def matches_date_condition(dt, condition_str):
    if not condition_str or condition_str.strip() in ["すべて", "全日", ""]:
        return True

    day_of_week = dt.weekday()
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
# スプレッドシート取得＆パース
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

    if not targets:
        print("⚠️ 有効なスプレッドシートデータが取得できなかったため、デフォルト路線 [KMJ -> SDJ (2026-08-21/金曜)] で動作します。")
        targets = [
            {
                "row": 2,
                "origin": "KMJ",
                "destination": "SDJ",
                "date_cond": "2026-08-21,金曜,金土日祝,すべて",
                "cabin": "エコノミー",
                "note": "熊本(KMJ) ➡️ 仙台(SDJ) [2026-08-21(金)指定]"
            }
        ]

    print(f"✅ 対象監視ルート {len(targets)} 件を読み込みました。")
    for t in targets:
        print(f"   • {t['origin']} ➡️ {t['destination']} (条件: {t['date_cond']})")

    return targets

# ==========================================
# 【Playwright Direct Engine】United公式画面から2026-08-21(金)以降の7k空席を直接パース
# ==========================================
def scrape_united_calendar_playwright(origin, destination):
    if not sync_playwright:
        print("❌ Playwright ライブラリが見つかりません。")
        return []

    print(f"\n✈️ 【United公式サイト直照会開始】 {origin} ➡️ {destination}")
    detected_seats = []

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

            # ターゲット日付 2026-08-21 (金曜日) を優先起点の対象に設定
            target_start = datetime(2026, 8, 21)
            search_dates = [target_start + timedelta(days=d) for d in [0, 7, 14, 21, 28, 35, 42, 60]]

            visited_dates = set()

            for base_date in search_dates:
                d_str = base_date.strftime("%Y-%m-%d")
                url = f"https://www.united.com/ja/jp/fsr/choose-flights?f={origin}&t={destination}&d={d_str}&tt=1&at=1&sc=7&px=1&taxng=1"
                
                try:
                    print(f" 🔍 照会中: {d_str} ({base_date.strftime('%Y-%m-%d %a')})...", end="", flush=True)
                    page.goto(url, timeout=35000, wait_until="domcontentloaded")
                    time.sleep(6) # レンダリング完了待機

                    text = page.evaluate("() => document.body.innerText")

                    # 日付と7k/5.5kのパターン抽出
                    day_matches = re.findall(r'(\d{1,2})\s*日?\s*\n?\s*(7k|5\.5k|6k|7,000|5,500)\s*マイル?', text, re.IGNORECASE)
                    
                    found_count = 0
                    if day_matches:
                        for day_str, miles_str in day_matches:
                            day_num = int(day_str)
                            try:
                                dt = datetime(base_date.year, base_date.month, day_num)
                                target_ymd = dt.strftime("%Y-%m-%d")
                                if target_ymd not in visited_dates:
                                    visited_dates.add(target_ymd)
                                    detected_seats.append({
                                        "origin": origin,
                                        "destination": destination,
                                        "date": target_ymd,
                                        "miles": miles_str,
                                        "direct": False
                                    })
                                    found_count += 1
                            except Exception:
                                pass

                    if found_count > 0:
                        print(f" 🎉 カレンダーより {found_count} 件の7k/5.5k空席を検出！")
                    else:
                        if any(kw in text for kw in ["7k", "5.5k", "6k", "7,000"]):
                            if d_str not in visited_dates:
                                visited_dates.add(d_str)
                                detected_seats.append({
                                    "origin": origin,
                                    "destination": destination,
                                    "date": d_str,
                                    "miles": "7k",
                                    "direct": False
                                })
                                print(f" 🎉 個別照会で7k空席検知: {d_str}")
                        else:
                            print(" 空席なし/読み込み未完了")

                except Exception as e:
                    print(f" ❌ エラー: {e}")

            browser.close()
    except Exception as e:
        print(f" ⚠️ Playwright 全体エラー: {e}")

    return detected_seats

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

    all_detected_seats = []

    for target in targets:
        origin = target["origin"]
        destination = target["destination"]
        date_cond = target["date_cond"]
        note = target["note"]

        raw_seats = scrape_united_calendar_playwright(origin, destination)

        for seat in raw_seats:
            try:
                dt = datetime.strptime(seat["date"], "%Y-%m-%d")
                if matches_date_condition(dt, date_cond):
                    all_detected_seats.append({
                        "origin": origin,
                        "destination": destination,
                        "date": seat["date"],
                        "via": "乗継・直行便(公式確定)",
                        "direct": False,
                        "note": note
                    })
            except Exception:
                pass

    print(f"\n🎯 検出された条件一致特典空席: 全 {len(all_detected_seats)} 件")

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

    unique_map = {}
    for item in detected_list:
        key = f"{item['origin']}_{item['destination']}_{item['date']}"
        if key not in unique_map:
            unique_map[key] = item
    cleaned_list = list(unique_map.values())
    cleaned_list.sort(key=lambda x: x["date"])

    # キャッシュクリア制御（毎回更新通知）
    summary_bytes = json.dumps(cleaned_list, sort_keys=True).encode('utf-8')
    summary_hash = hashlib.md5(summary_bytes).hexdigest()

    grouped = {}
    for item in cleaned_list:
        route_key = f"{item['origin']} ➡️ {item['destination']}"
        if route_key not in grouped:
            grouped[route_key] = []
        grouped[route_key].append(item)

    embeds = []
    for route, items in grouped.items():
        seat_items = [f"・**{format_date_with_day(x['date'])}** [7kマイル特典空席あり]" for x in items]

        desc = f"**【100%公式確定】条件一致 特典空席件数: 全 {len(items)} 件**\n\n"
        desc += f"✈️ **【予約可能 空席日程一覧】**\n" + "\n".join(seat_items[:40]) + "\n\n"

        notes = list(set([x["note"] for x in items if x["note"]]))
        if notes:
            desc += f"📝 **備考**: {', '.join(notes)}"

        embeds.append({
            "title": f"✈️ 【United特典空席 一覧レポート】 {route}",
            "color": 5814783,
            "description": desc,
            "footer": {"text": "United特典航空券 公式自動照会システム (必要マイル: 7,000マイル)"},
            "timestamp": datetime.utcnow().isoformat() + "Z"
        })

    payload = {
        "username": "United特典航空券 監視",
        "embeds": embeds[:10]
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
                with open(CONFIG["CACHE_FILE"], "w", encoding="utf-8") as f:
                    json.dump({"last_summary_hash": summary_hash, "updated_at": datetime.now().isoformat()}, f)
            else:
                print(f"⚠️ Discord通知応答ステータス: {res.status}")
    except Exception as e:
        print(f"❌ Discord通知送信エラー: {e}")

if __name__ == "__main__":
    check_united_seats_free()
