import os
import re
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
        print(f"❌ 找不到帳號清單檔案: {filename}")
        return []
    
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            username = clean_username(line)
            if username:
                streamers.add(username)
    return list(streamers)

def fetch_via_proxitok(streamer_id):
    """備用方案：透過公共 API / RSS 解析影片 ID"""
    print(f"🔄 嘗試透過備用 API 抓取 @{streamer_id}...")
    video_ids = []
    # 使用開放的 ProxiTok 實例 API
    api_url = f"https://proxitok.pabloferreiro.es/api/user/{streamer_id}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
    
    try:
        res = requests.get(api_url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get('items', [])
            for item in items:
                v_id = item.get('id')
                if v_id:
                    video_ids.append(str(v_id))
    except Exception as e:
        print(f"⚠️ 備用 API 抓取失敗 (@{streamer_id}): {e}")
        
    return video_ids

def fetch_streamer_video_ids(streamer_id):
    profile_url = f"https://www.tiktok.com/@{streamer_id}"
    
    ydl_opts = {
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
    }
    
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        ydl_opts['cookiefile'] = COOKIE_FILE

    video_ids = []
    print(f"正在抓取 @{streamer_id} 的影片 ID...")

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
    except Exception as e:
        print(f"⚠️ yt-dlp 解析失敗 (@{streamer_id}): {e}")

    # 如果 yt-dlp 被擋掉沒抓到任何 ID，自動切換至備用 API
    if not video_ids:
        video_ids = fetch_via_proxitok(streamer_id)

    if video_ids:
        print(f"✅ 成功取得 @{streamer_id} 共 {len(video_ids)} 個影片 ID。")
    else:
        print(f"❌ 無法取得 @{streamer_id} 的影片 ID。")

    return video_ids

def main():
    streamers = load_streamers(ACCOUNTS_FILE)
    if not streamers:
        print("⚠️ 沒有載入任何有效的主播帳號。")
        return
        
    print(f"載入 {len(streamers)} 位主播帳號，開始處理...\n")
    
    all_ids = []
    for streamer in streamers:
        ids = fetch_streamer_video_ids(streamer)
        all_ids.extend(ids)
    
    all_ids = list(dict.fromkeys(all_ids))
    
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        for vid in all_ids:
            f.write(vid + "\n")
            
    print(f"\n🎉 全部處理完成！共收集到 {len(all_ids)} 個不重複的影片 ID，已寫入 {OUTPUT_TXT}")

if __name__ == "__main__":
    main()
