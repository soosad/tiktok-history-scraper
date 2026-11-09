import os
import re
import time
import sys
import requests
import yt_dlp

ACCOUNTS_FILE = "account.txt"
OUTPUT_TXT = "all_historyvideos.txt"
COOKIE_FILE = "cookies.txt"

def clean_username(line):
    clean = line.strip()
    clean = re.sub(r'^[<>]|[<>]$', '', clean)
    clean = clean.strip()
    if clean.startswith('@'):
        clean = clean[1:]
    return clean.strip()

def load_streamers(filename):
    streamers = set()
    if not os.path.exists(filename):
        print(f"❌ 找不到帳號清單檔案: {filename}", flush=True)
        return []
    
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            username = clean_username(line)
            if username:
                streamers.add(username)
    return list(streamers)

def fetch_via_proxitok(streamer_id):
    """備用 API：當 yt-dlp 失敗時自動切換"""
    video_ids = []
    api_url = f"https://proxitok.pabloferreiro.es/api/user/{streamer_id}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }
    try:
        res = requests.get(api_url, headers=headers, timeout=15)
        if res.status_code == 200:
            data = res.json()
            for item in data.get('items', []):
                v_id = item.get('id')
                if v_id:
                    video_ids.append(str(v_id))
    except Exception:
        pass
    return video_ids

def fetch_streamer_video_ids(streamer_id):
    # 同時嘗試不同的網址結構來避開 secondary ID 限制
    urls_to_try = [
        f"https://www.tiktok.com/@{streamer_id}",
        f"https://m.tiktok.com/h5/share/usr/{streamer_id}.html"
    ]
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,
        'socket_timeout': 30,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7',
        }
    }
    
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        ydl_opts['cookiefile'] = COOKIE_FILE

    video_ids = []
    print(f"正在抓取 @{streamer_id} 的影片 ID...", flush=True)

    for profile_url in urls_to_try:
        if video_ids:
            break
        for attempt in range(2):
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(profile_url, download=False)
                    if info and 'entries' in info:
                        for entry in info['entries']:
                            if entry:
                                v_id = entry.get('id')
                                if not v_id and entry.get('url'):
                                    match = re.search(r'/video/(\d+)', entry.get('url'))
                                    if match:
                                        v_id = match.group(1)
                                if v_id:
                                    video_ids.append(str(v_id))
                if video_ids:
                    break
            except Exception:
                time.sleep(2)

    # 如果 yt-dlp 雙重網址都失敗，啟動備用 API
    if not video_ids:
        video_ids = fetch_via_proxitok(streamer_id)

    if video_ids:
        print(f"✅ 成功取得 @{streamer_id} 共 {len(video_ids)} 個影片 ID。", flush=True)
    else:
        print(f"⚠️ 無法取得 @{streamer_id} 的影片 ID（該帳號可能不存在、無公開影片或被完全封鎖）。", flush=True)

    return video_ids

def main():
    streamers = load_streamers(ACCOUNTS_FILE)
    if not streamers:
        print("⚠️ 沒有載入任何有效的主播帳號。", flush=True)
        return
        
    print(f"載入 {len(streamers)} 位主播帳號，開始處理...\n", flush=True)
    
    all_ids = []
    for streamer in streamers:
        ids = fetch_streamer_video_ids(streamer)
        all_ids.extend(ids)
        time.sleep(2)
    
    all_ids = list(dict.fromkeys(all_ids))
    
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        for vid in all_ids:
            f.write(vid + "\n")
            
    print(f"\n🎉 處理完成！共收集到 {len(all_ids)} 個不重複的影片 ID，已寫入 {OUTPUT_TXT}", flush=True)

if __name__ == "__main__":
    main()
