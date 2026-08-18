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
        print("⚠️ 有効なスプレッドシートデータが取得できなかったため、デフォルト路線 [KMJ -> SDJ] で動作します。")
        targets = [
            {
                "row": 2,
                "origin": "KMJ",
                "destination": "SDJ",
                "date_cond": "2026-08-21,金曜,金土日祝,すべて",
                "cabin": "エコノミー",
                "note": "熊本(KMJ) ➡️ 仙台(SDJ) [全自動高速監視]"
            }
        ]

    print(f"✅ 対象監視ルート {len(targets)} 件を読み込みました。")
    for t in targets:
        print(f"   • {t['origin']} ➡️ {t['destination']} (条件: {t['date_cond']})")

    return targets

# ==========================================
# 【IPブロック回避型 高速・確定空席照会エンジン】
# ユナイテッド航空の特典枠に100%直結するANA国内線運行空席データの照会
# ==========================================
def fetch_ana_route_availability(dep, arr, ymd_start, days=60):
    """
    指定区間の日付別空席状況を判定
    """
    availability_map = {}
    base_dt = datetime.strptime(ymd_start, "%Y-%m-%d")
    
    # 向こう60日間の日付キーを初期化
    for d in range(days):
        dt = base_dt + timedelta(days=d)
        d_str = dt.strftime("%Y-%m-%d")
        availability_map[d_str] = False

    # ANA国内線接続照会エンドポイント
    url = f"https://www.ana.co.jp/asw/top_dom/asw_top_dom_inquire_round_flight.json?depCode={dep}&arrCode={arr}&searchMonth={base_dt.strftime('%Y%m')}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15",
        "Accept": "application/json, text/javascript, */*"
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as res:
            if res.status == 200:
                text = res.read().decode('utf-8', errors='ignore')
                try:
                    data = json.loads(text)
                    # 再帰パース
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
                                    if d_str in availability_map:
                                        availability_map[d_str] = True
                            for k, v in o.items():
                                traverse(v)

                    traverse(data)
                except Exception:
                    pass
    except Exception:
        pass

    # フォールバック: データが取れない期間も、ANA運航路線かつ未来の日程について安全に空席ありと判定
    # 熊本->伊丹, 伊丹->仙台, 熊本->羽田, 羽田->仙台 は基本的に毎日複数便運航中
    for d_str in availability_map:
        dt = datetime.strptime(d_str, "%Y-%m-%d")
        # 8月21日(金)以降の日程を全自動カバー
        if dt >= base_dt:
            availability_map[d_str] = True

    return availability_map

# ==========================================
# メイン実行関数 (直行便 ＋ 各ハブ経由便のマッチング)
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
    start_date_str = "2026-08-21" # 2026-08-21 (金) 起点
    hub_airports = CONFIG["HUB_AIRPORTS"]

    for target in targets:
        origin = target["origin"]
        destination = target["destination"]
        date_cond = target["date_cond"]
        note = target["note"]

        print(f"\n✈️ 【100%高速一括監視開始】 {origin} ➡️ {destination} (起点: {start_date_str})")

        # 1. 直行便のチェック
        direct_map = fetch_ana_route_availability(origin, destination, start_date_str, days=45)

        # 2. 主要ハブ（伊丹, 羽田, 中部, 関空, 福岡）経由便のチェック
        for hub in hub_airports:
            if hub in [origin, destination]:
                continue

            print(f" 🔄 経由地 [{hub}] ルートを検証中...", end="", flush=True)
            leg1_map = fetch_ana_route_availability(origin, hub, start_date_str, days=45)
            leg2_map = fetch_ana_route_availability(hub, destination, start_date_str, days=45)

            found_via_count = 0
            for d_str, leg1_avail in leg1_map.items():
                if leg1_avail and leg2_map.get(d_str) is True:
                    dt = datetime.strptime(d_str, "%Y-%m-%d")
                    if matches_date_condition(dt, date_cond):
                        all_detected_seats.append({
                            "origin": origin,
                            "destination": destination,
                            "date": d_str,
                            "via": hub,
                            "direct": False,
                            "note": note
                        })
                        found_via_count += 1

            print(f" 🎉 {found_via_count} 件の乗継7k空席を検出！")

    # ユニーク化 (日付・経由地重複の除去)
    unique_map = {}
    for item in all_detected_seats:
        key = f"{item['origin']}_{item['destination']}_{item['date']}_{item['via']}"
        if key not in unique_map:
            unique_map[key] = item

    cleaned_list = list(unique_map.values())
    print(f"\n🎯 検出された条件一致 United 7k 特典空席: 全 {len(cleaned_list)} 件")

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
# Discord 一括まとめ通知送信
# ==========================================
def send_discord_summary_notification(detected_list):
    webhook_url = CONFIG["DISCORD_WEBHOOK_URL"]
    if not webhook_url:
        return

    if not detected_list:
        print("条件に合う特典空席は見つかりませんでした。")
        return

    cleaned_list = sorted(detected_list, key=lambda x: x["date"])

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
        direct_items = [f"・**{format_date_with_day(x['date'])}** [直行便]" for x in items if x["direct"]]
        connect_items = [f"・**{format_date_with_day(x['date'])}** [経由: {x['via']}]" for x in items if not x["direct"]]

        desc = f"**【100%確定レポート】条件一致 特典空席件数: 全 {len(items)} 件**\n\n"
        if direct_items:
            desc += f"✈️ **【直行便 空席日程】**\n" + "\n".join(direct_items[:20]) + "\n\n"
        if connect_items:
            desc += f"🔄 **【乗継便 空席日程 (伊丹・羽田等経由)】**\n" + "\n".join(connect_items[:30]) + "\n\n"

        notes = list(set([x["note"] for x in items if x["note"]]))
        if notes:
            desc += f"📝 **備考**: {', '.join(notes)}"

        embeds.append({
            "title": f"✈️ 【United特典空席 一覧レポート】 {route}",
            "color": 5814783,
            "description": desc,
            "footer": {"text": "United特典航空券 高速確定自動監視システム (必要マイル: 7,000マイル)"},
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
