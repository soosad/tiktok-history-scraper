import os
import re
import yt_dlp

# ==================== 設定區域 ====================
ACCOUNTS_FILE = "accounts.txt"          # 存放主播帳號的文字檔
OUTPUT_TXT = "all_historyvideos.txt"    # 最終輸出的歷史影片清單
COOKIE_FILE = "cookies.txt"             # 登入 Cookie 檔案
# ==================================================

def clean_username(line):
    """清理帳號字串，去除尖角號、@、前後空白等雜訊"""
    clean = line.strip()
    clean = re.sub(r'^[<>]|[<>]$', '', clean)
    clean = clean.strip()
    if clean.startswith('@'):
        clean = clean[1:]
    return clean.strip()

def load_streamers(filename):
    """從檔案中讀取並解析所有不重複的主播帳號"""
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

def fetch_streamer_videos(streamer_id):
    """取得指定主播的所有歷史影片網址與 ID"""
    profile_url = f"https://www.tiktok.com/@{streamer_id}"
    
    ydl_opts = {
        'extract_flat': True,  # 快速提取中繼資料，不下載實際影片檔案
        'quiet': True,
        'no_warnings': True,
    }
    
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    video_urls = []
    print(f"正在掃描主播 @{streamer_id} 的所有歷史影片...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        v_url = entry.get('url') or f"https://www.tiktok.com/@{streamer_id}/video/{entry.get('id')}"
                        if v_url:
                            video_urls.append(v_url)
                            
        print(f"✅ 成功取得 @{streamer_id} 共 {len(video_urls)} 部影片。")
    except Exception as e:
        print(f"⚠️ 無法取得 @{streamer_id} 的影片: {e}")

    return video_urls

def main():
    streamers = load_streamers(ACCOUNTS_FILE)
    if not streamers:
        print("⚠️ 沒有載入任何有效的主播帳號，請確認 accounts.txt 內容。")
        return
        
    print(f"總共載入 {len(streamers)} 位不重複的主播帳號。\n")
    
    all_videos = []
    
    for streamer in streamers:
        urls = fetch_streamer_videos(streamer)
        all_videos.extend(urls)
    
    # 移除重複網址
    all_videos = list(dict.fromkeys(all_videos))
    
    # 寫入文字檔
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        for url in all_videos:
            f.write(url + "\n")
            
    print(f"\n🎉 全部處理完成！總共收集到 {len(all_videos)} 部影片，已儲存至 {OUTPUT_TXT}")

if __name__ == "__main__":
    main()
