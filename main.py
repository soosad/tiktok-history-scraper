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

    if not video_ids:
        video_ids = fetch_via_proxitok(streamer_id)

    if video_ids:
        print(f"✅ 成功取得 @{streamer_id} 共 {len(video_ids)} 個影片 ID。", flush=True)
    else:
        print(f"⚠️ 無法取得 @{streamer_id} 的影片 ID（該帳號可能不存在、無公開影片或被完全封鎖）。", flush=True)

    return video_ids

def git_commit_and_push(streamer_id):
    """將當前更新立即推回 GitHub 倉庫"""
    print(f"🚀 正在將 @{streamer_id} 的更新推送至 GitHub 倉庫...", flush=True)
    os.system('git config --global user.name "github-actions[bot]"')
    os.system('git config --global user.email "github-actions[bot]@users.noreply.github.com"')
    os.system(f'git add {OUTPUT_TXT}')
    os.system(f'git commit -m "Auto-update: added new videos for @{streamer_id}"')
    os.system('git push')
    print(f"✅ @{streamer_id} 推送完成！\n", flush=True)

def main():
    streamers = load_streamers(ACCOUNTS_FILE)
    if not streamers:
        print("⚠️ 沒有載入任何有效的主播帳號。", flush=True)
        return
        
    print(f"載入 {len(streamers)} 位主播帳號，開始逐一處理...\n", flush=True)
    
    # 1. 載入現有的歷史紀錄 (如果檔案存在)，用來做重複比對
    existing_ids = set()
    if os.path.exists(OUTPUT_TXT):
        with open(OUTPUT_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    existing_ids.add(v_id)
        print(f"📂 已載入歷史紀錄，目前共有 {len(existing_ids)} 個已知影片 ID。\n", flush=True)

    # 2. 逐一迴圈處理每位主播
    for streamer in streamers:
        print(f"==============================", flush=True)
        print(f"▶️ 開始處理主播: @{streamer}", flush=True)
        print(f"==============================", flush=True)
        
        # 取得該主播目前的影片 ID
        ids = fetch_streamer_video_ids(streamer)
        
        # 3. 比對歷史紀錄，過濾掉已經存在的不重複新 ID
        new_ids = [v_id for v_id in ids if v_id not in existing_ids]
        
        if new_ids:
            print(f"✨ 發現 @{streamer} 的全新影片 ID 共 {len(new_ids)} 個！", flush=True)
            
            # 加入全域歷史集合
            existing_ids.update(new_ids)
            
            # 立即將完整的歷史清單寫回檔案
            with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
                for vid in existing_ids:
                    f.write(vid + "\n")
            
            # 立即執行 Git 提交並推回倉庫
            git_commit_and_push(streamer)
        else:
            print(f"ℹ️ @{streamer} 沒有產生新的影片 ID（皆已存在）。\n", flush=True)
        
        # 主播與主播之間的緩衝休息，避免過於頻繁
        time.sleep(3)

    print(f"🎉 所有主播處理完畢！目前總共累積 {len(existing_ids)} 個不重複的影片 ID。", flush=True)

if __name__ == "__main__":
    main()
