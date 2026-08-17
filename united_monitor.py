import os
import time
import json
import csv
import io
import hashlib
import requests
import datetime
from concurrent.futures import ThreadPoolExecutor

# ★設定
SPREADSHEET_ID = "1gL7HdNzZ4-xa629L7GR20XC-0FJCS93rfp9PCAtKAkk"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/1538426702160461846/w_zf0BwnBk6-zFlFycJErKX9zTSKyjmr_cxthPqMi7mAGXU9uRxEu813SFxPzSG3J8bt")
DISCORD_MENTION = "@everyone"
SEARCH_MONTHS_COUNT = 12  # 今月〜来年7月まで（12ヶ月分）を全自動監視

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

def search_united_award_direct(origin, destination, year_month_str):
    """ユナイテッド航空公式APIへダイレクト通信"""
    date_str = f"{year_month_str[:4]}-{year_month_str[4:]}-01"
    url = "https://www.united.com/api/flight/FetchCalendar"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
        "Content-Type": "application/json",
        "Origin": "https://www.united.com",
        "Referer": "https://www.united.com/ja/jp/flight-search/book-a-flight/results"
    }
    
    payload = {
        "Request": {
            "Origin": origin,
            "Destination": destination,
            "DepartDate": date_str,
            "PaxCount": 1,
            "AwardSearch": True,
            "SelectedCabin": "Economy"
        }
    }
    
    available_dates = []
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            days = data.get("CalendarDays", []) or data.get("CalendarMonths", [{}])[0].get("Days", [])
            for day in days:
                price = day.get("LowestPrice") or day.get("Miles") or day.get("Price") or 0
                day_date = day.get("Date") or day.get("DepartDate")
                if (price == 7000 or price == 7 or day.get("IsLowestFare") == True) and day_date:
                    available_dates.append(str(day_date))
    except Exception as e:
        pass
    
    return available_dates

def main():
    print(f"=== ユナイテッド航空 特展空席 自動監視システム開始 (来年7月まで12ヶ月全監視・並列一括モード) ===")
    active_rows = get_spreadsheet_rows()

    now = datetime.datetime.now()
    target_months = []
    for m in range(SEARCH_MONTHS_COUNT):
        month = (now.month - 1 + m) % 12 + 1
        year = now.year + (now.month - 1 + m) // 12
        target_months.append(f"{year}{month:02d}")

    print(f"監視対象月: {target_months[0]} 〜 {target_months[-1]} (計12ヶ月分)")

    all_results = []

    for row in active_rows:
        origin = row["origin"]
        dest = row["destination"]
        print(f"\n[照会中] {origin} -> {dest} (12ヶ月分一斉並列通信中...)")

        # 12ヶ月分を一斉に同時並列通信（これが秒速完了の要）
        with ThreadPoolExecutor(max_workers=12) as executor:
            futures = [executor.submit(search_united_award_direct, origin, dest, ym) for ym in target_months]
            for future in futures:
                dates = future.result()
                for d in dates:
                    all_results.append({
                        "route": f"{origin} ➡️ {dest}",
                        "date": d,
                        "note": row["note"]
                    })

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
