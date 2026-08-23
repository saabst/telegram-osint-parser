#!/usr/bin/env python3
"""Уведомления о новых событиях через Telegram-бота.

Токен берётся у @BotFather (несложно, в отличие от api_id), chat_id
определяется автоматически после того, как пользователь написал боту /start.
Настройки хранятся в config.json: tg_bot_token, tg_chat_id.
"""
import time

import requests

from parser import load_config

MAX_MESSAGE_LEN = 3800     # лимит Telegram — 4096, оставляем запас
MAX_EVENTS_IN_DIGEST = 25  # больше событий — только счётчиком


def _api(method: str, token: str, **payload) -> dict:
    resp = requests.post(f"https://api.telegram.org/bot{token}/{method}",
                         json=payload, timeout=15)
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API: {data.get('description', resp.status_code)}")
    return data


def detect_chat_id(token: str) -> int:
    """Возвращает chat_id последнего диалога с ботом.

    Пользователь должен сначала написать боту что-нибудь (/start).
    Бросает ValueError с понятным текстом, если ничего не нашлось.
    """
    try:
        data = _api("getUpdates", token)
    except RuntimeError as e:
        raise ValueError(f"Бот не отвечает (проверь токен): {e}")
    except Exception as e:
        raise ValueError(f"Сеть недоступна: {e}")

    updates = data.get("result", [])
    for upd in reversed(updates):
        msg = upd.get("message") or upd.get("edited_message") or upd.get("channel_post")
        if msg and "chat" in msg:
            return msg["chat"]["id"]
    raise ValueError("Бот не получил ни одного сообщения. "
                     "Найди своего бота в Telegram, нажми Start и повтори.")


def _format_event(e: dict) -> str:
    date = ""
    try:
        from datetime import datetime
        date = datetime.fromisoformat(e["date"]).strftime("%d.%m %H:%M")
    except Exception:
        pass

    coords = e.get("geo", {}).get("coordinates")
    approx = e.get("geo", {}).get("approximate")
    coord_str = ""
    if coords:
        c = coords[0]
        coord_str = f"📍 {'≈ ' if approx else ''}{c['lat']:.5f}, {c['lon']:.5f}\n"

    loc = e.get("geo", {}).get("location_name") or "—"
    channel = "@" + e["channel_username"] if e.get("channel_username") else e.get("channel", "")
    text = (e.get("full_text") or "").strip().replace("\n", " ")
    if len(text) > 120:
        text = text[:117] + "..."

    return (f"🚨 [{e.get('category', '?')}] {loc} · {date}\n"
            f"{coord_str}"
            f"📡 {channel}\n"
            f"{text}\n"
            f"{e.get('link', '')}")


def format_digest_chunks(events: list[dict]) -> list[str]:
    """Собирает дайджест, режет на куски под лимит сообщения."""
    header = f"🛰 Новые события: {len(events)}\n\n"
    chunks = []
    current = header

    for i, e in enumerate(events):
        if i >= MAX_EVENTS_IN_DIGEST:
            rest = len(events) - MAX_EVENTS_IN_DIGEST
            current += f"\n… и ещё {rest} событий — смотри viewer."
            break
        block = _format_event(e) + "\n\n"
        if len(current) + len(block) > MAX_MESSAGE_LEN:
            chunks.append(current.rstrip())
            current = block
        else:
            current += block

    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def notify_new_events(events: list[dict], log=print) -> bool:
    """Отправляет дайджест новых событий. Тихо пропускает, если не настроено."""
    if not events:
        return False

    cfg = load_config()
    token = cfg.get("tg_bot_token")
    chat_id = cfg.get("tg_chat_id")
    if not token or not chat_id:
        log("📬 Уведомления не настроены (токен бота / chat_id) — пропускаю")
        return False

    sent = 0
    try:
        for chunk in format_digest_chunks(events):
            _api("sendMessage", token, chat_id=chat_id, text=chunk,
                 disable_web_page_preview=True)
            sent += 1
            time.sleep(1)   # вежливость к лимитам Bot API
        log(f"📬 Дайджест отправлен в Telegram ({sent} сообщ.)")
        return True
    except Exception as e:
        log(f"❌ Не удалось отправить уведомление: {e}")
        return False


if __name__ == "__main__":
    # Быстрая проверка: python notify.py
    demo = [{
        "category": "прилёты", "date": "2026-08-22T20:15:00",
        "geo": {"location_name": "запорожье", "approximate": True,
                "coordinates": [{"lat": 47.8388, "lon": 35.1396}]},
        "channel_username": "test", "full_text": "тестовое событие",
        "link": "https://t.me/test/1",
    }]
    for c in format_digest_chunks(demo):
        print(c)
