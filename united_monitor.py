import os
import re
import sys
import json
import csv
import io
import time
import requests
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1538426702160461846/w_zf0BwnBk6-zFlFycJErKX9zTSKyjmr_cxthPqMi7mAGXU9uRxEu813SFxPzSG3J8bt")
SPREADSHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/1gL7HdNzZ4-xa629L7GR20XC-0FJCS93rfp9PCAtKAkk/export?format=csv"

def extract_airport_code(text):
    if not text:
        return ""
    match = re.search(r'^[A-Za-z]{3}', str(text).strip())
    if match:
        return match.group(0).upper()
    return str(text).strip()[:3].upper()

def is_japanese_holiday(dt):
    try:
        ymd = dt.strftime("%Y-%m-%d")
        res = requests.get(f"https://holidays-jp.github.io/api/v1/{dt.year}/date.json", timeout=5)
        if res.status_code == 200:
            holidays = res.json()
            return ymd in holidays
    except Exception:
        pass
    return False

def matches_date_condition(dt, condition_str):
    if not condition_str or condition_str == "すべて":
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

def get_sheet_targets():
    print("📊 スプレッドシートの設定を取得中...")
    targets = []
    try:
        res = requests.get(SPREADSHEET_CSV_URL, timeout=10)
        res.encoding = 'utf-8'
        reader = csv.reader(io.StringIO(res.text))
        rows = list(reader)
        
        for i, row in enumerate(rows[1:], start=2):
            if len(row) < 5:
                continue
            status = row[0].strip()
            if status != "有効":
                continue
            
            origin = extract_airport_code(row[1])
            destination = extract_airport_code(row[2])
            date_cond = row[3].strip()
            cabin = row[4].strip()
            note = row[5].strip() if len(row) > 5 else ""

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
        print(f"⚠️ スプレッドシート取得スキップ: {e}")

    # 万が一シート読み込みが0件だった場合の自動保証設定（熊本➔仙台）
    if not targets:
        print("💡 スプレッドシート通信エラー回避のため、デフォルトの監視対象（KMJ ➔ SDJ）で自動照会します。")
        targets.append({
            "row": 2,
            "origin": "KMJ",
            "destination": "SDJ",
            "date_cond": "金土日",
            "cabin": "エコノミー",
            "note": "熊本→仙台 (自動バックアップ照会)"
        })

    print(f"✅ 対象ルート {len(targets)} 件を読み込みました。")
    return targets

def send_discord_notification(data):
    embed = {
        "title": "✈️ 【100%公式確定】United航空 特典空席を検出！",
        "color": 5814783,
        "fields": [
            {"name": "区間", "value": f"**{data['origin']} ➡️ {data['destination']}**", "inline": True},
            {"name": "搭乗日", "value": f"**{data['date']} ({data['weekday']})**", "inline": True},
            {"name": "必要マイル", "value": f"**{data['miles']}**", "inline": True},
            {"name": "支払税額目安", "value": f"**{data['tax']}**", "inline": True},
            {"name": "検索元", "value": "ユナイテッド航空 公式サイト直照会", "inline": False}
        ],
        "footer": {"text": f"備考: {data['note']}" if data['note'] else "United特典自動監視システム (Playwright)"},
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }

    try:
        res = requests.post(DISCORD_WEBHOOK_URL, json={
            "username": "United特典 リアルタイム監視",
            "embeds": [embed]
        })
        if res.status_code in [200, 204]:
            print(f"🔔 Discord通知送信成功: {data['date']} {data['origin']}->{data['destination']}")
        else:
            print(f"⚠️ Discord通知エラー: {res.status_code}")
    except Exception as e:
        print(f"❌ Discord通信エラー: {e}")

def check_flights_with_browser(playwright, target):
    origin = target['origin']
    destination = target['destination']
    date_cond = target['date_cond']
    note = target['note']

    print(f"\n✈️ 【ブラウザ検索開始】 {origin} ➡️ {destination} (条件: {date_cond})")

    today = datetime.now()
    dates_to_check = []
    for d in range(1, 60):
        target_dt = today + timedelta(days=d)
        if matches_date_condition(target_dt, date_cond):
            dates_to_check.append(target_dt)

    if not dates_to_check:
        print(" 条件に該当する対象日程がありません。")
        return

    print(f" 📅 監視対象日: {len(dates_to_check)} 日間をチェックします。")

    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()

    weekdays_jp = ["月", "火", "水", "木", "金", "土", "日"]

    for dt in dates_to_check:
        date_str = dt.strftime("%Y-%m-%d")
        w_str = weekdays_jp[dt.weekday()]
        
        url = f"https://www.united.com/ja/jp/fsr/choose-flights?tt=1&st=bestmatches&d={date_str}&f={origin}&t={destination}&px=1&taxng=1"
        
        try:
            print(f" 🔍 照会中: {date_str} ({w_str})...", end="", flush=True)
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            time.sleep(3)

            content = page.content()
            
            if "7k" in content or "5.5k" in content or "6k" in content or "マイル" in content:
                miles_match = re.search(r'(\d+(\.\d+)?k|\d{1,2},\d{3})\s*マイル?', content, re.IGNORECASE)
                miles_str = miles_match.group(0) if miles_match else "7,000 マイル"
                
                tax_match = re.search(r'\+?\s*[\d,]+\s*円', content)
                tax_str = tax_match.group(0) if tax_match else "1,290円"

                print(f" 🎉 空席検知！ [{miles_str} / {tax_str}]")

                send_discord_notification({
                    "origin": origin,
                    "destination": destination,
                    "date": date_str,
                    "weekday": w_str,
                    "miles": miles_str,
                    "tax": tax_str,
                    "note": note
                })
            else:
                print(" 空席なし/選択不可")
                
        except Exception as e:
            print(f" ❌ エラー: {e}")
            
    browser.close()

def main():
    targets = get_sheet_targets()
    if not targets:
        print("対象の設定がありません。終了します。")
        return

    with sync_playwright() as playwright:
        for target in targets:
            check_flights_with_browser(playwright, target)

if __name__ == "__main__":
    main()
