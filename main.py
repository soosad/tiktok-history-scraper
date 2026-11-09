import os
import re
import yt_dlp

# ==================== 設定區域 ====================
ACCOUNTS_FILE = "account.txt"           # 你的主播清單檔名（若你的檔案叫 accounts.txt 請自行調整）
OUTPUT_TXT = "all_historyvideos.txt"    # 最終輸出的影片 ID 清單
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

def fetch_streamer_video_ids(streamer_id):
    """取得指定主播的所有歷史影片 ID"""
    profile_url = f"https://www.tiktok.com/@{streamer_id}"
    
    ydl_opts = {
        'extract_flat': True,  # 快速提取，不下載影片
        'quiet': True,
        'no_warnings': True,
    }
    
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    video_ids = []
    print(f"正在取得主播 @{streamer_id} 的歷史影片 ID...")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(profile_url, download=False)
            if 'entries' in info:
                for entry in info['entries']:
                    if entry:
                        # 嘗試直接拿 ID，若無則從網址解析
                        v_id = entry.get('id')
                        if not v_id and entry.get('url'):
                            match = re.search(r'/video/(\d+)', entry.get('url'))
                            if match:
                                v_id = match.group(1)
                        if v_id:
                            video_ids.append(str(v_id))
                            
        print(f"✅ 成功取得 @{streamer_id} 共 {len(video_ids)} 個影片 ID。")
    except Exception as e:
        print(f"⚠️ 無法取得 @{streamer_id}: {e}")

    return video_ids

def main():
    streamers = load_streamers(ACCOUNTS_FILE)
    if not streamers:
        print("⚠️ 沒有載入任何有效的主播帳號，請確認檔案內容。")
        return
        
    print(f"總共載入 {len(streamers)} 位不重複的主播帳號。\n")
    
    all_ids = []
    for streamer in streamers:
        ids = fetch_streamer_video_ids(streamer)
        all_ids.extend(ids)
    
    # 移除重複的 ID
    all_ids = list(dict.fromkeys(all_ids))
    
    # 寫入文字檔
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        for vid in all_ids:
            f.write(vid + "\n")
            
    print(f"\n🎉 全部處理完成！總共收集到 {len(all_ids)} 個不重複的影片 ID，已儲存至 {OUTPUT_TXT}")

if __name__ == "__main__":
    main()
