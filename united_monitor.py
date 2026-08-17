import os
import time
import json
import csv
import io
import hashlib
import requests
import datetime
from playwright.sync_api import sync_playwright

# ★設定
SPREADSHEET_ID = "1gL7HdNzZ4-xa629L7GR20XC-0FJCS93rfp9PCAtKAkk"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1538426702160461846/w_zf0BwnBk6-zFlFycJErKX9zTSKyjmr_cxthPqMi7mAGXU9uRxEu813SFxPzSG3J8bt")
DISCORD_MENTION = "@everyone"
SEARCH_MONTHS_COUNT = 12  # ★今月〜来年7月まで（12ヶ月分）をまとめて全自動監視

def get_spreadsheet_rows():
    """スプレッドシートから有効な監視設定を取得"""
    csv_url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv"
    active_rows = []
    try:
        res = requests.get(csv_url, timeout=15)
        res.encoding = 'utf-8'
        if res.status_code == 200:
            reader = csv.reader(io.StringIO(res.text))
            rows = list(reader)
            for row in rows[1:]:
                if len(row) >= 4 and str(row[0]).strip() == "有効":
                    origin = str(row[1])[:3].upper()
                    destination = str(row[2])[:3].upper()
                    condition = str(row[3]).strip()
                    note = str(row[5]).strip() if len(row) > 5 else ""
                    active_rows.append({
                        "origin": origin,
                        "destination": destination,
                        "condition": condition,
                        "note": note
                    })
    except Exception as e:
        print(f"スプレッドシート読み込み注意: {e}")

    if not active_rows:
        print("スプレッドシートから行を取得できなかったため、デフォルト設定(KMJ -> SDJ)で検索を実行します。")
        active_rows.append({
            "origin": "KMJ",
            "destination": "SDJ",
            "condition": "すべて",
            "note": "熊本➔仙台 監視"
        })

    return active_rows

def search_united_award_fast(page, origin, destination, year_month_str):
    """ユナイテッド航空の公式カレンダーAPIをブラウザ内から超高速直接呼び出し (タイムアウトゼロ化)"""
    date_str = f"{year_month_str[:4]}-{year_month_str[4:]}-01"
    
    fetch_js = """
    async ([orig, dest, dStr]) => {
        try {
            const response = await fetch("https://www.united.com/api/flight/FetchCalendar", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify({
                    "Request": {
                        "Origin": orig,
                        "Destination": dest,
                        "DepartDate": dStr,
                        "PaxCount": 1,
                        "AwardSearch": true,
                        "SelectedCabin": "Economy"
                    }
                })
            });
            if (!response.ok) return null;
            return await response.json();
        } catch (e) {
            return null;
        }
    }
    """
    
    available_dates = []
    try:
        data = page.evaluate(fetch_js, [origin, destination, date_str])
        
        if data and "CalendarDays" in str(data):
            days = data.get("CalendarDays", []) or data.get("CalendarMonths", [{}])[0].get("Days", [])
            for day in days:
                price = day.get("LowestPrice") or day.get("Miles") or day.get("Price") or 0
                day_date = day.get("Date") or day.get("DepartDate")
                if (price == 7000 or price == 7 or day.get("IsLowestFare") == True) and day_date:
                    available_dates.append(str(day_date))

    except Exception as e:
        print(f"API解析エラー ({origin} -> {destination} {year_month_str}): {e}")
    
    return available_dates

def main():
    print(f"=== ユナイテッド航空 特典空席 自動監視システム開始 (来年7月まで12ヶ月全監視モード) ===")
    active_rows = get_spreadsheet_rows()

    now = datetime.datetime.now()
    target_months = []
    for m in range(SEARCH_MONTHS_COUNT):
        month = (now.month - 1 + m) % 12 + 1
        year = now.year + (now.month - 1 + m) // 12
        target_months.append(f"{year}{month:02d}")

    print(f"監視対象月: {target_months[0]} 〜 {target_months[-1]} (計12ヶ月分)")

    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=['--disable-http2', '--no-sandbox', '--disable-setuid-sandbox']
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
        )
        page = context.new_page()

        try:
            page.goto("https://www.united.com/ja/jp", wait_until="commit", timeout=20000)
            time.sleep(3)
        except Exception:
            pass

        for row in active_rows:
            origin = row["origin"]
            dest = row["destination"]
            print(f"\n[照会中] {origin} -> {dest}")

            for ym in target_months:
                dates = search_united_award_fast(page, origin, dest, ym)
                for d in dates:
                    all_results.append({
                        "route": f"{origin} ➡️ {dest}",
                        "date": d,
                        "note": row["note"]
                    })
        
        browser.close()

    if all_results:
        send_discord_summary(all_results)
    else:
        print("条件に合う空席は見つかりませんでした。")

def send_discord_summary(results):
    results_json = json.dumps(results, sort_keys=True)
    current_hash = hashlib.md5(results_json.encode('utf-8')).hexdigest()
    
    hash_file = "last_hash.txt"
    if os.path.exists(hash_file):
        with open(hash_file, "r") as f:
            if f.read().strip() == current_hash:
                print("前回の通知内容と変化がないためDiscord送信をスキップしました。")
                return

    description = f"**条件一致 空席件数: 全 {len(results)} 件**\n\n"
    for item in results:
        description += f"・**{item['date']}** ({item['route']})\n"

    embed = {
        "title": "✈️ 【ユナイテッド航空 7k特典空席 一覧レポート】",
        "color": 5814783,
        "description": description,
        "footer": {"text": "United特典航空券 高速監視システム (来年7月まで12ヶ月全監視)"},
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    payload = {
        "username": "United特典空席 監視Bot",
        "content": DISCORD_MENTION,
        "embeds": [embed]
    }

    res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if res.status_code == 204 or res.status_code == 200:
        print("🎉 Discordまとめ通知の送信に成功しました！")
        with open(hash_file, "w") as f:
            f.write(current_hash)
    else:
        print(f"Discord送信エラー: {res.status_code}")

if __name__ == "__main__":
    main()
