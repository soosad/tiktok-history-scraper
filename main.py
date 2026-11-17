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
OUTPUT_TXT = "all_historyvideos.txt"      # 原始龐大歷史紀錄檔
PROCESSED_TXT = "processed_videos.txt"  # 新增：用來嚴格防範重複上傳的追蹤檔
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
    # 載入歷史庫 all_historyvideos.txt
    if os.path.exists(OUTPUT_TXT):
        with open(OUTPUT_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    history_video_ids.add(v_id)
        print(f"📂 已載入歷史發送紀錄庫 (all_historyvideos.txt)，共 {len(history_video_ids)} 筆。", flush=True)

    # 載入防重複追蹤檔 processed_videos.txt
    if os.path.exists(PROCESSED_TXT):
        with open(PROCESSED_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    processed_video_ids.add(v_id)
        print(f"📂 已載入已上傳追蹤檔 (processed_videos.txt)，共 {len(processed_video_ids)} 筆。", flush=True)
    else:
        # 如果還沒有這個新檔案，初次啟動時可以把歷史庫先同步進來，或者保留空白由程式逐步補發
        print(f"ℹ️ 尚未發現 processed_videos.txt，將建立新檔案進行上傳追蹤。", flush=True)

def append_to_history(v_id):
    """將新影片 ID 同時寫入歷史庫與追蹤檔"""
    if v_id not in history_video_ids:
        history_video_ids.add(v_id)
        with open(OUTPUT_TXT, "a", encoding="utf-8") as f:
            f.write(f"{v_id}\n")
            
    if v_id not in processed_video_ids:
        processed_video_ids.add(v_id)
        with open(PROCESSED_TXT, "a", encoding="utf-8") as f:
            f.write(f"{v_id}\n")

def fetch_via_proxitok(streamer_id):
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

    return video_ids

async def clean_and_sync_topics(accounts):
    print("\n🔍 準備透過 Telethon 掃描群組話題...", flush=True)
    if not API_ID or not API_HASH or not SESSION_STRING or not TELEGRAM_CHAT_ID:
        print("❌ 缺少必要 Telegram 憑證，無法啟動 Telethon！", flush=True)
        return

    try:
        client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            print("❌ SESSION_STRING 已失效！", flush=True)
            await client.disconnect()
            return

        chat_id_int = int(TELEGRAM_CHAT_ID)
        entity = await client.get_entity(chat_id_int)
        
        raw_topics = {}
        try:
            from telethon.tl.functions.messages import GetForumTopicsRequest
            result = await client(GetForumTopicsRequest(
                peer=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
            ))
            for topic in result.topics:
                raw_topics[topic.id] = topic.title
        except Exception:
            try:
                from telethon.tl.functions.channels import GetForumTopicsRequest
                result = await client(GetForumTopicsRequest(
                    channel=entity, offset_date=0, offset_id=0, offset_topic=0, limit=100
                ))
                for topic in result.topics:
                    raw_topics[topic.id] = topic.title
            except Exception as e2:
                print(f"⚠️ 無法取得群組話題: {e2}", flush=True)
                await client.disconnect()
                return

        title_to_ids = {}
        for tid, title in raw_topics.items():
            if title not in title_to_ids:
                title_to_ids[title] = []
            title_to_ids[title].append(tid)

        for streamer_name in accounts:
            if streamer_name in title_to_ids:
                tids = sorted(title_to_ids[streamer_name])
                topics_map[streamer_name] = tids[0]
                print(f"🔗 主播 【{streamer_name}】 配對到話題 ID: {tids[0]}", flush=True)

                if len(tids) > 1:
                    for dup_tid in tids[1:]:
                        try:
                            await client(functions.channels.DeleteTopicRequest(
                                channel=entity, topic_id=dup_tid
                            ))
                            print(f"  🗑️ 已刪除重複話題 ID: {dup_tid}", flush=True)
                            await asyncio.sleep(1.0)
                        except Exception:
                            pass

        save_topics_map()
        await client.disconnect()
        print("✅ 話題掃描與同步完成。\n", flush=True)
    except Exception as e:
        print(f"❌ Telethon 執行例外: {e}", flush=True)

async def ensure_topic_exists(bot: Bot, streamer_name: str) -> int:
    if streamer_name in topics_map:
        return topics_map[streamer_name]

    for _ in range(3):
        try:
            topic = await bot.create_forum_topic(chat_id=int(TELEGRAM_CHAT_ID), name=streamer_name)
            thread_id = topic.message_thread_id
            topics_map[streamer_name] = thread_id
            save_and_push_topic_immediately(streamer_name, thread_id)
            print(f"✨ 成功建立新話題：{streamer_name} (ID: {thread_id})", flush=True)
            await asyncio.sleep(3.0)
            return thread_id
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                await asyncio.sleep(20)
            else:
                break
    return None

async def send_video_notification(bot: Bot, thread_id: int, streamer_name: str, video_id: str):
    video_url = f"https://www.tiktok.com/@{streamer_name}/video/{video_id}"
    message_text = f"🚨 **TikTok 影片通知**\n👤 主播：@{streamer_name}\n🔗 連結：{video_url}"
    try:
        await bot.send_message(
            chat_id=int(TELEGRAM_CHAT_ID),
            message_thread_id=thread_id,
            text=message_text,
            disable_web_page_preview=False
        )
        print(f"📤 成功發送影片通知到 @{streamer_name} 話題 (ID: {thread_id})", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ 發送失敗 [{streamer_name}]: {e}", flush=True)
        return False

def git_commit_and_push_records():
    print(f"🚀 正在將歷史紀錄與追蹤檔推送至 GitHub...", flush=True)
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", OUTPUT_TXT, PROCESSED_TXT], check=True)
        subprocess.run(["git", "commit", "-m", "🤖 Auto-update: sync history and processed video records"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"✅ 紀錄推送完成！\n", flush=True)
    except Exception as e:
        print(f"⚠️ 紀錄推送略過（無變動或權限問題）: {e}", flush=True)

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ 找不到 TELEGRAM_BOT_TOKEN", flush=True)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    load_all_records()
    load_topics_map()
    accounts = load_streamers(ACCOUNTS_FILE)

    if not accounts:
        print("⚠️ 沒有載入任何主播帳號。", flush=True)
        return

    # 1. 話題同步與建立
    print("📌 【階段一】檢查與建立所有主播話題...", flush=True)
    await clean_and_sync_topics(accounts)
    for streamer in accounts:
        await ensure_topic_exists(bot, streamer)

    # 2. 歷史影片補發階段（針對 all_historyvideos.txt 裡尚未在 processed_videos.txt 中的歷史項目）
    print("\n📌 【階段二】檢查歷史影片並補發至對應話題...", flush=True)
    # 註：此處若歷史檔案達 16 萬筆，若要全部發送會花費大量時間與 Telegram 頻率限制。
    # 通常我們會確保比對 `processed_videos.txt`，只補發還沒上傳過的歷史。
    # 這裡會掃描每位主播的最新抓取結果，並與歷史庫做比對。

    has_updates = False

    # 3. 常態監控與新影片推送
    print(f"\n📌 【階段三】進入常態監控，檢查 1317 位主播的最新影片...", flush=True)
    for streamer in accounts:
        thread_id = topics_map.get(streamer)
        if not thread_id:
            continue

        print(f"==============================", flush=True)
        print(f"▶️ 檢查主播: @{streamer}", flush=True)
        print(f"==============================", flush=True)

        ids = fetch_streamer_video_ids(streamer)
        # 比對「還沒被追蹤檔記錄過」的影片
        new_ids = [v_id for v_id in ids if v_id not in processed_video_ids]

        if new_ids:
            print(f"✨ 發現 @{streamer} 的新/未發送影片共 {len(new_ids)} 個！", flush=True)
            for v_id in reversed(new_ids):
                sent_ok = await send_video_notification(bot, thread_id, streamer, v_id)
                if sent_ok:
                    append_to_history(v_id)
                    has_updates = True
                    await asyncio.sleep(3.0)
        else:
            print(f"ℹ️ @{streamer} 目前沒有新影片。\n", flush=True)

        time.sleep(2)

    if has_updates:
        git_commit_and_push_records()

    print(f"🎉 所有流程執行完畢！", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
