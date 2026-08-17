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
SEARCH_MONTHS_COUNT = 12  # ★今月〜来年7月まで（12ヶ月分）全監視
HUB_AIRPORTS = ["ITM", "HND", "NGO", "KIX", "FUK", "CTS", "OKA"]  # 乗継ハブ空港

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
        print("デフォルト設定(KMJ -> SDJ 乗継対応)で検索を実行します。")
        active_rows.append({
            "origin": "KMJ",
            "destination": "SDJ",
            "condition": "すべて",
            "note": "熊本➔仙台 監視"
        })

    return active_rows

def fetch_api(dep, arr, ym_str):
    """APIから日付ごとの空席リストを取得"""
    date_str = f"{ym_str[:4]}-{ym_str[4:]}-01"
    url = "https://www.united.com/api/flight/FetchCalendar"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://www.united.com",
        "Referer": "https://www.united.com/ja/jp/flight-search/book-a-flight/results"
    }
    payload = {
        "Request": {
            "Origin": dep,
            "Destination": arr,
            "DepartDate": date_str,
            "PaxCount": 1,
            "AwardSearch": True,
            "SelectedCabin": "Economy"
        }
    }
    result = {}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            data = res.json()
            days = data.get("CalendarDays", []) or data.get("CalendarMonths", [{}])[0].get("Days", [])
            for day in days:
                price = day.get("LowestPrice") or day.get("Miles") or day.get("Price") or 0
                day_date = day.get("Date") or day.get("DepartDate")
                is_ok = (price == 7000 or price == 7 or day.get("IsLowestFare") == True)
                if day_date:
                    result[str(day_date)] = is_ok
    except Exception:
        pass
    return (dep, arr, ym_str, result)

def main():
    print(f"=== ユナイテッド航空 特典空席 自動監視システム開始 (来年7月まで12ヶ月全監視・乗継完全対応版) ===")
    active_rows = get_spreadsheet_rows()

    now = datetime.datetime.now()
    target_months = []
    for m in range(SEARCH_MONTHS_COUNT):
        month = (now.month - 1 + m) % 12 + 1
        year = now.year + (now.month - 1 + m) // 12
        target_months.append(f"{year}{month:02d}")

    print(f"監視対象月: {target_months[0]} 〜 {target_months[-1]} (計12ヶ月分)")

    all_detected = []

    for row in active_rows:
        origin = row["origin"]
        dest = row["destination"]
        note = row["note"]
        print(f"\n[照会中] {origin} -> {dest} (直行便＋乗継便を全一括検索中...)")

        tasks = []
        for ym in target_months:
            tasks.append((origin, dest, ym))
            for hub in HUB_AIRPORTS:
                if hub != origin and hub != dest:
                    tasks.append((origin, hub, ym))
                    tasks.append((hub, dest, ym))

        unique_tasks = list(set(tasks))

        api_data = {}
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(fetch_api, dep, arr, ym) for dep, arr, ym in unique_tasks]
            for future in futures:
                dep, arr, ym, res_dict = future.result()
                api_data[f"{dep}_{arr}_{ym}"] = res_dict

        for ym in target_months:
            # 1. 直行便
            direct_dict = api_data.get(f"{origin}_{dest}_{ym}", {})
            for d_str, is_ok in direct_dict.items():
                if is_ok:
                    all_detected.append({
                        "route": f"{origin} ➡️ {dest}",
                        "date": d_str,
                        "type": "直行便",
                        "note": note
                    })

            # 2. 乗継便 (伊丹・羽田等経由)
            for hub in HUB_AIRPORTS:
                if hub == origin or hub == dest: continue
                leg1_dict = api_data.get(f"{origin}_{hub}_{ym}", {})
                leg2_dict = api_data.get(f"{hub}_{dest}_{ym}", {})

                for d_str, is_ok1 in leg1_dict.items():
                    if is_ok1 and leg2_dict.get(d_str) == True:
                        all_detected.append({
                            "route": f"{origin} ➡️ ({hub}経由) ➡️ {dest}",
                            "date": d_str,
                            "type": f"乗継便 ({hub}経由)",
                            "note": note
                        })

    if all_detected:
        send_discord_summary(all_detected)
    else:
        print("条件に合う空席は見つかりませんでした。")

def send_discord_summary(results):
    unique_map = {}
    for item in results:
        k = f"{item['route']}_{item['date']}"
        if k not in unique_map:
            unique_map[k] = item
    cleaned_results = list(unique_map.values())
    cleaned_results.sort(key=lambda x: x['date'])

    results_json = json.dumps(cleaned_results, sort_keys=True)
    current_hash = hashlib.md5(results_json.encode('utf-8')).hexdigest()
    
    hash_file = "last_hash.txt"
    if os.path.exists(hash_file):
        with open(hash_file, "r") as f:
            if f.read().strip() == current_hash:
                print("前回の通知内容と変化がないためDiscord送信をスキップしました。")
                return

    description = f"**条件一致 空席件数: 全 {len(cleaned_results)} 件**\n\n"
    for item in cleaned_results[:30]:
        description += f"・**{item['date']}** [{item['route']}]\n"

    if len(cleaned_results) > 30:
        description += f"\n...他 {len(cleaned_results) - 30} 件あり"

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
        print(f"🎉 Discordまとめ通知の送信に成功しました！（合計 {len(cleaned_results)} 件の空席）")
        with open(hash_file, "w") as f:
            f.write(current_hash)
    else:
        print(f"Discord送信エラー: {res.status_code}")

if __name__ == "__main__":
    main()
