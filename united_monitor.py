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

def search_united_by_playwright(page, origin, destination):
    """ユナイテッド航空公式の検索フォームを自動入力して7kカレンダーを100%パース"""
    available_dates = []
    try:
        # 1. ユナイテッド航空の検索結果ページに直接アクセス
        now = datetime.datetime.now()
        date_str = f"{now.year}-{now.month:02d}-20"
        url = f"https://www.united.com/ja/jp/flight-search/book-a-flight/results?f={origin}&t={destination}&d={date_str}&tt=1&sc=7&pk=1&px=1&taxOnly=false&amt=7000"
        
        print(f"URLアクセス中: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(8) # カレンダーレンダリング待ち
        
        # 2. 画面上のカレンダー要素（7k表示セル）を全取得
        dates_script = """
        () => {
            const found = [];
            const elements = document.querySelectorAll('*');
            elements.forEach(el => {
                const text = el.innerText || '';
                const aria = el.getAttribute('aria-label') || '';
                if (text.includes('7k') || text.includes('7,000') || aria.includes('7k') || aria.includes('7,000')) {
                    const label = aria || text;
                    if (label && label.length < 80) {
                        found.push(label.replace(/\\n/g, ' ').trim());
                    }
                }
            });
            return Array.from(new Set(found));
        }
        """
        raw_dates = page.evaluate(dates_script)
        if raw_dates:
            for item in raw_dates:
                if item not in available_dates:
                    available_dates.append(item)
    except Exception as e:
        print(f"検索エラー ({origin} -> {destination}): {e}")
    
    return available_dates

def main():
    print("=== ユナイテッド航空 特典空席 自動監視システム開始 (公式画面完全パース) ===")
    active_rows = get_spreadsheet_rows()
    all_results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                '--disable-http2',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={'width': 1366, 'height': 768}
        )
        page = context.new_page()

        for row in active_rows:
            origin = row["origin"]
            dest = row["destination"]
            print(f"\n[照会中] {origin} -> {dest}")

            dates = search_united_united_by_playwright_loop(page, origin, dest)
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

def search_united_united_by_playwright_loop(page, origin, destination):
    results = []
    # 複数月分を巡回
    now = datetime.datetime.now()
    for i in range(3):
        m = (now.month - 1 + i) % 12 + 1
        y = now.year + (now.month - 1 + i) // 12
        date_str = f"{y}-{m:02d}-15"
        url = f"https://www.united.com/ja/jp/flight-search/book-a-flight/results?f={origin}&t={destination}&d={date_str}&tt=1&sc=7&pk=1&px=1&taxOnly=false&amt=7000"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(6)
            
            js = """
            () => {
                const res = [];
                document.querySelectorAll('*').forEach(el => {
                    const t = el.innerText || '';
                    const a = el.getAttribute('aria-label') || '';
                    if (t.includes('7k') || t.includes('7,000') || a.includes('7k') || a.includes('7,000')) {
                        const val = a || t;
                        if (val && val.length < 80) res.push(val.replace(/\\n/g, ' ').trim());
                    }
                });
                return Array.from(new Set(res));
            }
            """
            found = page.evaluate(js)
            if found:
                for f in found:
                    if f not in results:
                        results.append(f)
        except Exception as e:
            print(f"取得エラー: {e}")
    return results

def send_discord_summary(results):
    unique_map = {}
    for item in results:
        k = f"{item['route']}_{item['date']}"
        if k not in unique_map:
            unique_map[k] = item
    cleaned_results = list(unique_map.values())

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
        description += f"・**{item['date']}** ({item['route']})\n"

    embed = {
        "title": "✈️ 【ユナイテッド航空 7k特典空席 一覧レポート】",
        "color": 5814783,
        "description": description,
        "footer": {"text": "United特典航空券 高速監視システム"},
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

    payload = {
        "username": "United特典空席 監視Bot",
        "content": DISCORD_MENTION,
        "embeds": [embed]
    }

    res = requests.post(DISCORD_WEBHOOK_URL, json=payload)
    if res.status_code == 204 or res.status_code == 200:
        print(f"🎉 Discordまとめ通知の送信に成功しました！（検出数: {len(cleaned_results)} 件）")
        with open(hash_file, "w") as f:
            f.write(current_hash)
    else:
        print(f"Discord送信エラー: {res.status_code}")

if __name__ == "__main__":
    main()
