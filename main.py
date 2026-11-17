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
GENERAL_THREAD_ID = 1  # 預設 General 話題 ID

ACCOUNTS_FILE = "account.txt"
OUTPUT_TXT = "all_historyvideos.txt"
COOKIE_FILE = "cookies.txt"
TOPICS_FILE = "topics_map.json"

topics_map = {}
existing_video_ids = set()

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
    """當下即時儲存話題對應並推送到 GitHub 倉庫"""
    save_topics_map()
    print(f"💾 【即時儲存】已將 【{streamer_name}】 (ID: {thread_id}) 寫入 topics_map.json", flush=True)
    
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", TOPICS_FILE], check=True)
        subprocess.run(["git", "commit", "-m", f"🤖 Auto-update topic map for {streamer_name}"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"🚀 【即時推送】已成功將 topics_map.json 推回 GitHub 倉庫！", flush=True)
    except Exception as e:
        print(f"⚠️ 【即時推送失敗】（可能是本地無變動或權限問題）: {e}", flush=True)

def load_history():
    global existing_video_ids
    if os.path.exists(OUTPUT_TXT):
        with open(OUTPUT_TXT, "r", encoding="utf-8") as f:
            for line in f:
                v_id = line.strip()
                if v_id:
                    existing_video_ids.add(v_id)
        print(f"📂 已載入歷史發送紀錄，共 {len(existing_video_ids)} 筆。", flush=True)

def save_history():
    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        for vid in existing_video_ids:
            f.write(f"{vid}\n")

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

    return video_ids

async def clean_and_sync_topics(accounts):
    """使用 Telethon 掃描群組所有話題，進行配對與清理重複話題"""
    print("\n🔍 準備透過 Telethon 掃描群組話題...", flush=True)
    
    if not API_ID or not API_HASH or not SESSION_STRING or not TELEGRAM_CHAT_ID:
        print("❌ 缺少 API_ID, API_HASH, SESSION_STRING 或 TELEGRAM_CHAT_ID，無法啟動 Telethon！", flush=True)
        return

    try:
        client = TelegramClient(StringSession(SESSION_STRING), int(API_ID), API_HASH)
        await client.connect()
        
        if not await client.is_user_authorized():
            print("❌ SESSION_STRING 已經失效或未授權！", flush=True)
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
                print(f"⚠️ 無法取得群組話題清單: {e2}", flush=True)
                await client.disconnect()
                return

        title_to_ids = {}
        for tid, title in raw_topics.items():
            if title not in title_to_ids:
                title_to_ids[title] = []
            title_to_ids[title].append(tid)

        for streamer_name in accounts:
            topic_name = streamer_name
            if topic_name in title_to_ids:
                tids = sorted(title_to_ids[topic_name])
                earliest_tid = tids[0]
                topics_map[streamer_name] = earliest_tid
                print(f"🔗 主播 【{streamer_name}】 配對到現有話題 ID: {earliest_tid}", flush=True)

                if len(tids) > 1:
                    for dup_tid in tids[1:]:
                        try:
                            await client(functions.channels.DeleteTopicRequest(
                                channel=entity,
                                topic_id=dup_tid
                            ))
                            print(f"  🗑️ 已刪除重複話題 ID: {dup_tid}", flush=True)
                            await asyncio.sleep(1.0)
                        except Exception as del_err:
                            print(f"  ⚠️ 刪除話題失敗 (ID: {dup_tid}): {del_err}", flush=True)

        save_topics_map()
        await client.disconnect()
        print("✅ 話題掃描與同步完成。\n", flush=True)

    except Exception as e:
        print(f"❌ Telethon 執行時發生例外: {e}", flush=True)

async def ensure_topic_exists(bot: Bot, streamer_name: str) -> int:
    """如果該主播尚未在 topics_map 中，則利用 Bot 建立話題"""
    if streamer_name in topics_map:
        return topics_map[streamer_name]

    topic_name = streamer_name
    for _ in range(3):
        try:
            topic = await bot.create_forum_topic(chat_id=int(TELEGRAM_CHAT_ID), name=topic_name)
            thread_id = topic.message_thread_id
            topics_map[streamer_name] = thread_id
            
            save_and_push_topic_immediately(streamer_name, thread_id)
            print(f"✨ 成功在群組中建立新話題：{topic_name} (ID: {thread_id})", flush=True)
            await asyncio.sleep(3.0)
            return thread_id
        except TelegramError as e:
            if "Flood control exceeded" in str(e):
                await asyncio.sleep(20)
            else:
                print(f"⚠️ 建立話題失敗 [{streamer_name}]: {e}", flush=True)
                break
    return None

async def send_new_video_notification(bot: Bot, thread_id: int, streamer_name: str, video_id: str):
    """透過 Telegram Bot 發送新影片通知與連結到指定話題"""
    video_url = f"https://www.tiktok.com/@{streamer_name}/video/{video_id}"
    message_text = f"🚨 **TikTok 影片通知**\n👤 主播：@{streamer_name}\n🔗 連結：{video_url}"
    
    try:
        await bot.send_message(
            chat_id=int(TELEGRAM_CHAT_ID),
            message_thread_id=thread_id,
            text=message_text,
            disable_web_page_preview=False
        )
        print(f"📤 成功發送影片通知到 @{streamer_name} 的話題 (ID: {thread_id})", flush=True)
        return True
    except Exception as e:
        print(f"⚠️ 發送 Telegram 訊息失敗 [{streamer_name}]: {e}", flush=True)
        return False

def git_commit_and_push_history():
    """將 all_historyvideos.txt 的更新推回 GitHub 倉庫"""
    print(f"🚀 正在將歷史紀錄推送至 GitHub 倉庫...", flush=True)
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "github-actions[bot]@users.noreply.github.io"], check=True)
        subprocess.run(["git", "add", OUTPUT_TXT], check=True)
        subprocess.run(["git", "commit", "-m", "🤖 Auto-update: added video IDs history"], check=True)
        subprocess.run(["git", "push"], check=True)
        print(f"✅ 歷史紀錄推送完成！\n", flush=True)
    except Exception as e:
        print(f"⚠️ 歷史紀錄推送失敗 (可能是無變動): {e}", flush=True)

async def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ 找不到 TELEGRAM_BOT_TOKEN", flush=True)
        return

    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    load_history()
    load_topics_map()
    accounts = load_streamers(ACCOUNTS_FILE)

    if not accounts:
        print("⚠️ 沒有載入任何有效的主播帳號。", flush=True)
        return

    # 階段一：同步與建立話題，並確保歷史資料與話題完整對應
    print("📌 【階段一】開始初始化話題與確保歷史對應...", flush=True)
    await clean_and_sync_topics(accounts)

    for streamer_name in accounts:
        await ensure_topic_exists(bot, streamer_name)

    # 階段二：常態即時監控與新影片推送
    print(f"\n📌 【階段二】開始進入常態監控，檢查 1317 位主播的最新影片...", flush=True)
    has_new_videos = False

    for streamer in accounts:
        thread_id = topics_map.get(streamer)
        if not thread_id:
            print(f"⚠️ 略過 @{streamer}：找不到對應的 Telegram 話題 ID。", flush=True)
            continue

        print(f"==============================", flush=True)
        print(f"▶️ 檢查主播: @{streamer}", flush=True)
        print(f"==============================", flush=True)

        ids = fetch_streamer_video_ids(streamer)
        new_ids = [v_id for v_id in ids if v_id not in existing_video_ids]

        if new_ids:
            print(f"✨ 發現 @{streamer} 的新影片 ID 共 {len(new_ids)} 個！", flush=True)
            for v_id in reversed(new_ids):
                sent_ok = await send_new_video_notification(bot, thread_id, streamer, v_id)
                if sent_ok:
                    existing_video_ids.add(v_id)
                    has_new_videos = True
                    save_history()
                    await asyncio.sleep(3.0)
        else:
            print(f"ℹ️ @{streamer} 沒有產生新的影片。\n", flush=True)

        time.sleep(2)

    if has_new_videos:
        save_history()
        git_commit_and_push_history()

    print(f"🎉 所有主播處理完畢！目前總共累積 {len(existing_video_ids)} 個不重複的影片 ID。", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
