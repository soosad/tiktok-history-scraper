import asyncio
from datetime import datetime, timezone, timedelta
import json
import os
import random
import re
import subprocess
import time

from telegram import Bot
from telegram.error import TelegramError
from telethon import TelegramClient, functions
from telethon.sessions import StringSession
import yt_dlp
import requests

# === 讀取環境變數 ===
API_ID = os.environ.get("API_ID")
API_HASH = os.environ.get("API_HASH")
SESSION_STRING = os.environ.get("SESSION_STRING")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GENERAL_THREAD_ID = 1

ACCOUNTS_FILE = "account.txt"
OUTPUT_TXT = "all_historyvideos.txt"      
PROCESSED_TXT = "processed_videos.txt"  
COOKIE_FILE = "cookies.txt"
TOPICS_FILE = "topics_map.json"

topics_map = {}
history_video_ids = set()
processed_video_ids = set()

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
            if username and not username.startswith("#"):
                streamers.add(username)
    print(f"📋 從 {filename} 載入了 {len(streamers)} 位主播名單。", flush=True)
    return list(streamers)

def load_topics_map():
    global topics_map
    if os.path.exists(TOPICS_FILE):
        try:
            with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                topics_map = json.load(f)
                print(f"📂 已成功載入 topics_map.json，共 {len(topics_map)} 筆話題對應。", flush=True)
        except Exception as e:
            print(f"⚠️ 載入 topics_map.json 失敗: {e}", flush=True)
            topics_map = {}

def save_topics_map():
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics_map, f, ensure_ascii=False, indent=2)

def save_and_push_topic_immediately(streamer_name, thread_id):
    save_topics_map()
    print(f"💾 【即時儲存】已將 【{streamer_name}】 (ID: {thread_id}) 寫入 topics_map.json", flush=True)
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", TOPICS_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"🤖 Auto-update topic map for {streamer_name}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"🚀 【即時推送】已成功將 topics_map.json 推回 GitHub！", flush=True)
    except Exception as e:
        print(f"⚠️ 【即時推送失敗】: {e}", flush=True)

def load_all_records():
    global history_video_ids, processed_video_ids
    if os.path.exists(OUTPUT_TXT):
        with open(OUTPUT_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    history_video_ids.add(v_id)
        print(f"📂 已載入歷史發送紀錄庫 (all_historyvideos.txt)，共 {len(history_video_ids)} 筆。", flush=True)

    if os.path.exists(PROCESSED_TXT):
        with open(PROCESSED_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    processed_video_ids.add(v_id)
        print(f"📂 已載入已上傳追蹤檔 (processed_videos.txt)，共 {len(processed_video_ids)} 筆已上傳。", flush=True)

def append_to_processed(v_id):
    if v_id not in history_video_ids:
        history_video_ids.add(v_id)
        with open(OUTPUT_TXT, "a", encoding="utf-8") as f:
            f.write(f"{v_id}\n")
            
    if v_id not in processed_video_ids:
        processed_video_ids.add(v_id)
        with open(PROCESSED_TXT, "a", encoding="utf-8") as f:
            f.write(f"{v_id}\n")

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
    return video_ids

async def ensure_topic_exists(bot: Bot, streamer_name: str) -> int:
    """確保該主播在 Telegram 中擁有話題，沒有的話就主動建立"""
    if streamer_name in topics_map:
        return topics_map[streamer_name]

    for _ in range(3):
        try:
            topic = await bot.create_forum_topic(chat_id=int(TELEGRAM_CHAT_ID), name=streamer_name)
            thread_id = topic.message_thread_id
            topics_map[streamer_name] = thread_id
            save_and_push_topic_immediately(streamer_name, thread_id)
            print(f"✨ 成功在新群組建立話題: 【{streamer_name}】 (ID: {thread_id})", flush=True)
            await asyncio.sleep(3.0)
            return thread_id
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                await asyncio.sleep(20)
            else:
                print(f"⚠️ 建立話題失敗 [{streamer_name}]: {e}", flush=True)
                break
    return None

async def download_and_send_video(bot: Bot, thread_id: int, streamer_name: str, video_id: str):
    video_url = f"https://www.tiktok.com/@{streamer_name}/video/{video_id}"
    output_template = f"temp_{video_id}.mp4"
    
    ydl_opts = {
        'outtmpl': output_template,
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
    }
    if os.path.exists(COOKIE_FILE) and os.path.getsize(COOKIE_FILE) > 0:
        ydl_opts['cookiefile'] = COOKIE_FILE

    downloaded_file = None
    video_title = "無標題"
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            if info and 'title' in info:
                video_title = info.get('title', '').strip()
            
        if os.path.exists(output_template):
            downloaded_file = output_template
            
            caption = (
                f"🚨 **TikTok 影片通知**\n"
                f"👤 主播：@{streamer_name}\n"
                f"📝 標題：{video_title}\n"
                f"🔗 連結：{video_url}"
            )
            
            with open(downloaded_file, 'rb') as video_file:
                await bot.send_video(
                    chat_id=int(TELEGRAM_CHAT_ID),
                    message_thread_id=thread_id,
                    video=video_file,
                    caption=caption,
                    parse_mode="Markdown"
                )
            print(f"📤 成功下載並上傳 @{streamer_name} 的影片 (ID: {video_id})", flush=True)
            return True
    except Exception as e:
        print(f"⚠️ 下載或上傳影片失敗 [{streamer_name} - {video_id}]: {e}", flush=True)
    finally:
        if downloaded_file and os.path.exists(downloaded_file):
            try:
                os.remove(downloaded_file)
            except Exception:
                pass
    return False

def git_commit_and_push_records():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", OUTPUT_TXT, PROCESSED_TXT], check=True)
        subprocess.run(["git", "commit", "-m", "🤖 Auto-update: sync video upload records"], check=True)
        subprocess.run(["git", "push"], check=True)
    except Exception:
        pass

async def main():
    if not TELEGRAM_BOT_TOKEN:
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    load_all_records()
    load_topics_map()
    accounts = load_streamers(ACCOUNTS_FILE)

    if not accounts:
        return

    print(f"\n📌 開始檢查並建立 1,317 位主播的話題與影片同步...", flush=True)
    
    for streamer in accounts:
        thread_id = await ensure_topic_exists(bot, streamer)
        if not thread_id:
            continue

        print(f"▶️ 檢查主播: @{streamer} (話題 ID: {thread_id})", flush=True)
        ids = fetch_streamer_video_ids(streamer)
        
        unprocessed_ids = [v_id for v_id in ids if v_id not in processed_video_ids]

        if unprocessed_ids:
            print(f"✨ 發現 @{streamer} 有 {len(unprocessed_ids)} 個未上傳影片，開始下載並上傳...", flush=True)
            for v_id in reversed(unprocessed_ids):
                success = await download_and_send_video(bot, thread_id, streamer, v_id)
                if success:
                    append_to_processed(v_id)
                    git_commit_and_push_records()
                    await asyncio.sleep(3.0)
        else:
            print(f"ℹ️ @{streamer} 目前沒有需要上傳的新影片。\n", flush=True)

        time.sleep(2)

    print(f"🎉 所有主播的群組話題與影片同步流程執行完畢！", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
