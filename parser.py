#!/usr/bin/env python3
"""Telegram OSINT парсер с дедупликацией."""
import os
import re
import json
import argparse
from datetime import datetime
from pathlib import Path

import asyncio
import time

import dateparser
from rich.console import Console
from rich.table import Table

console = Console()

# ============ КОНФИГУРАЦИЯ ============
CONFIG_FILE = "config.json"
SOURCES_FILE = "sources.json"
OUTPUT_DIR = "events"
INDEX_FILE = "events_index.json"

TRIGGER_WORDS = ["прилёт", "прилет", "удар", "ракета", "шахед", "искандер",
                 "калибр", "взрыв", "дрон", "бпла", "перехват", "сбит"]

MISSILE_TYPES = ["шахед", "shahed", "искандер", "калибр", "х-101", "x-101",
                 "х-47", "x-47", "х-59", "x-59", "х-22", "x-22", "s-300",
                 "с-300", "s-400", "с-400", "patriot", "томагавк", "атакмс"]

COUNTRIES = ["украина", "россия", "беларусь", "польша", "молдова", "грузия"]

CITIES = ["киев", "харьков", "одесса", "львов", "днепр", "запорожье", "херсон",
          "москва", "санкт-петербург", "белгород", "курск", "воронеж", "ростов",
          "минск", "гомель", "варшава", "кишинёв",
          "донецк", "луганск", "мариуполь", "симферополь", "севастополь",
          "николаев", "полтава", "сумы", "чернигов",
          "донбасс", "крым"]

# Приблизительные центры городов и регионов. Используются, когда в посте
# нет явных координат, но упомянут населённый пункт — событие привязывается
# к центру и помечается флагом approximate.
REGION_CENTERS = {
    "киев": (50.4501, 30.5234),
    "харьков": (49.9935, 36.2304),
    "одесса": (46.4775, 30.7326),
    "львов": (49.8397, 24.0297),
    "днепр": (48.4647, 35.0462),
    "запорожье": (47.8388, 35.1396),
    "херсон": (46.6354, 32.6114),
    "москва": (55.7558, 37.6173),
    "санкт-петербург": (59.9311, 30.3609),
    "белгород": (50.5977, 36.5859),
    "курск": (51.7373, 36.1874),
    "воронеж": (51.6608, 39.2003),
    "ростов": (47.2357, 39.5444),
    "минск": (53.9006, 27.5590),
    "гомель": (52.4345, 30.9754),
    "варшава": (52.2297, 21.0122),
    "кишинёв": (47.0105, 28.8638),
    "донецк": (48.0159, 37.8028),
    "луганск": (48.5740, 39.3078),
    "мариуполь": (47.0971, 37.5435),
    "симферополь": (44.9521, 34.1024),
    "севастополь": (44.6166, 33.5254),
    "николаев": (46.9750, 31.9946),
    "полтава": (49.5937, 34.5435),
    "сумы": (50.9077, 34.7981),
    "чернигов": (51.4982, 31.2893),
    "донбасс": (48.3000, 38.0000),
    "крым": (45.2000, 34.4000),
}
# ====================================


# ---------- Конфигурация ----------
def load_config() -> dict:
    """Загружает конфигурацию из файла."""
    if not Path(CONFIG_FILE).exists():
        return {
            "api_id": None,
            "api_hash": None,
            "phone": None,
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict):
    """Сохраняет конфигурацию в файл."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def get_api_credentials() -> tuple:
    """Возвращает API credentials из конфига."""
    config = load_config()
    api_id = config.get("api_id")
    api_hash = config.get("api_hash")
    phone = config.get("phone")
    
    if not all([api_id, api_hash, phone]):
        raise ValueError("API credentials не настроены. Откройте настройки в GUI.")
    
    return int(api_id), api_hash, phone


# ---------- Дедупликация ----------
def load_index() -> set[tuple[str, int]]:
    if not Path(INDEX_FILE).exists():
        return set()
    with open(INDEX_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return {(item["channel"], item["msg_id"]) for item in data}


def save_index(index: set[tuple[str, int]]):
    data = [{"channel": ch, "msg_id": mid} for ch, mid in sorted(index)]
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_duplicate(index: set, channel: str, msg_id: int) -> bool:
    return (channel, msg_id) in index


def add_to_index(index: set, channel: str, msg_id: int):
    index.add((channel, msg_id))


# ---------- Работа с датами ----------
def parse_date_arg(value: str) -> datetime | None:
    if not value:
        return None
    dt = dateparser.parse(
        value,
        languages=["ru", "en"],
        settings={
            "PREFER_DAY_OF_MONTH": "first",
            "PREFER_DATES_FROM": "past",
            "RETURN_AS_TIMEZONE_AWARE": False,
        }
    )
    if dt is None:
        raise ValueError(f"Не удалось распознать дату: '{value}'")
    return dt


# ---------- Работа с источниками ----------
def load_sources() -> list[dict]:
    if not Path(SOURCES_FILE).exists():
        console.print(f"[yellow]⚠️  Файл {SOURCES_FILE} не найден.[/]")
        return []
    with open(SOURCES_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("sources", [])


def filter_sources(sources: list[dict], args) -> list[dict]:
    result = sources
    if args.only:
        only_set = {u.strip().lstrip("@").lower() for u in args.only.split(",")}
        result = [s for s in result if s["username"].lower() in only_set]
    if args.except_:
        except_set = {u.strip().lstrip("@").lower() for u in args.except_.split(",")}
        result = [s for s in result if s["username"].lower() not in except_set]
    if args.group:
        groups_set = {g.strip().lower() for g in args.group.split(",")}
        result = [s for s in result if groups_set & {g.lower() for g in s.get("groups", [])}]
    if not args.all and not args.only and not args.group:
        result = [s for s in result if s.get("enabled", True)]
    return result


# ---------- Извлечение сущностей ----------
def extract_coordinates(text: str) -> list[dict]:
    coords = []
    # Десятичные градусы: точка или запятая в дробной части (35,18066 — русский
    # формат), точность после разделителя от 3 до 15 знаков (встречается и
    # 47.80499465299742 с «лишней» точностью от карт)
    def _num(s: str) -> float:
        return float(s.replace(",", "."))

    for m in re.finditer(
            r"(-?\d{1,3}[.,]\d{3,15})\s*[,;|]?\s*(-?\d{1,3}[.,]\d{3,15})", text):
        try:
            lat, lon = _num(m.group(1)), _num(m.group(2))
        except ValueError:
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            coords.append({"lat": round(lat, 6), "lon": round(lon, 6), "format": "decimal"})
    for m in re.finditer(
        r"(\d{1,3})°(\d{1,2})[′'](\d{1,2})[″\"]\s*с\.?\s*ш\.?\s*,?\s*(\d{1,3})°(\d{1,2})[′'](\d{1,2})[″\"]\s*в\.?\s*д\.?",
        text, re.IGNORECASE
    ):
        lat = int(m.group(1)) + int(m.group(2))/60 + int(m.group(3))/3600
        lon = int(m.group(4)) + int(m.group(5))/60 + int(m.group(6))/3600
        coords.append({"lat": round(lat, 6), "lon": round(lon, 6), "format": "dms"})
    return coords


def extract_entities(text: str) -> dict:
    t = text.lower()
    missiles = [m for m in MISSILE_TYPES if m in t]
    countries = [c for c in COUNTRIES if c in t]
    cities = [c for c in CITIES if c in t]
    return {
        "missile_type": missiles[0] if missiles else None,
        "country": countries[0] if countries else None,
        "location": cities[0] if cities else None,
    }


def classify_event(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["прилёт", "прилет", "удар", "взрыв"]): return "прилёты"
    if any(w in t for w in ["перехват", "сбит"]): return "перехваты"
    if any(w in t for w in ["дрон", "бпла"]): return "дроны"
    return "прочее"


def resolve_coordinates(coords: list, entities: dict) -> tuple[list, bool]:
    """Если явных координат в посте нет, но упомянут известный город/регион —
    подставляет приблизительный центр. Возвращает (координаты, approximate)."""
    if coords:
        return coords, False
    loc = entities.get("location")
    if loc and loc in REGION_CENTERS:
        lat, lon = REGION_CENTERS[loc]
        return [{"lat": lat, "lon": lon, "format": "approx"}], True
    return [], False


def save_event(channel_username: str, channel_title: str, message, entities: dict,
               coords: list, category: str, approximate: bool = False):
    folder = os.path.join(OUTPUT_DIR, category)
    os.makedirs(folder, exist_ok=True)
    filename = f"{message.date.strftime('%Y-%m-%d_%H-%M')}_msg{message.id}.json"
    # Для публичных каналов правильная ссылка — t.me/<username>/<id>
    if channel_username:
        link = f"https://t.me/{channel_username}/{message.id}"
    else:
        link = f"https://t.me/c/{getattr(message, 'chat_id', '')}/{message.id}"
    data = {
        "id": message.id,
        "channel_username": channel_username,
        "channel": channel_title,
        "date": message.date.isoformat(),
        "category": category,
        "full_text": message.text or "",
        "link": link,
        "geo": {"coordinates": coords, "location_name": entities["location"],
                "country": entities["country"], "approximate": approximate},
        "military": {"missile_type": entities["missile_type"]},
    }
    with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ---------- CLI ----------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Telegram OSINT парсер")
    p.add_argument("--from", dest="date_from",
                   help="С какой даты. Примеры: '2026-08-01', 'вчера', '3 days ago'")
    p.add_argument("--to", dest="date_to",
                   help="До какой даты. Примеры: '2026-08-15', 'сегодня'")
    p.add_argument("--all", action="store_true", help="Парсить все источники (включая disabled)")
    p.add_argument("--only", help="Только эти каналы: kanal1,kanal2")
    p.add_argument("--except", dest="except_", help="Исключить каналы: kanal3")
    p.add_argument("--group", help="Только из групп: военкоры,официальные")
    p.add_argument("--limit", type=int, default=500, help="Макс. постов на канал")
    p.add_argument("--force", action="store_true", help="Игнорировать дедупликацию")
    p.add_argument("--mode", choices=["api", "web"], default="api",
                   help="Способ парсинга: api — Telethon (нужны ключи), web — веб-превью t.me/s (без ключей)")
    return p


# ---------- Веб-режим (t.me/s, без API-ключей) ----------
def run_web_parsing(sources: list[dict], date_from, date_to, limit: int,
                    force: bool, index: set,
                    log=None, progress=None) -> tuple[int, int]:
    """Парсит каналы через веб-превью t.me/s. Возвращает (новых, дубликатов).

    Использует ту же обработку, что и API-режим: триггеры, извлечение
    сущностей, категории, дедупликацию и формат сохранения.
    """
    from web_fetch import ChannelUnavailableError, iter_posts

    log = log or console.print
    total_new = 0
    total_dup = 0

    for i, source in enumerate(sources):
        username = source["username"]
        title = source.get("title", username)
        if progress:
            progress(i, len(sources))
        log(f"\n📡 {title} (@{username}) [веб]")

        count = 0
        duplicates = 0
        try:
            for post in iter_posts(username, limit=limit,
                                   date_from=date_from, date_to=date_to,
                                   log=log):
                if not force and is_duplicate(index, username, post.id):
                    duplicates += 1
                    continue

                if not post.text:
                    continue

                text_lower = post.text.lower()
                if not any(w in text_lower for w in TRIGGER_WORDS):
                    continue

                coords = extract_coordinates(post.text)
                entities = extract_entities(post.text)
                category = classify_event(post.text)
                coords, approx = resolve_coordinates(coords, entities)
                save_event(username, title, post, entities, coords, category, approx)
                add_to_index(index, username, post.id)
                count += 1
                log(f"  ✓ [{category}] {post.date:%d.%m %H:%M} — {post.text[:60]}...")
        except ChannelUnavailableError as e:
            log(f"  ❌ {e}")
            continue

        log(f"  Новых: {count}  Дубликатов пропущено: {duplicates}")
        total_new += count
        total_dup += duplicates
        time.sleep(1)   # вежливая пауза между каналами

    return total_new, total_dup


# ---------- Основная логика ----------
async def parse_channel(client, source: dict, date_from, date_to, limit: int, index: set, force: bool):
    username = source["username"]
    title = source.get("title", username)
    console.print(f"\n[bold cyan]📡 {title}[/] (@{username})")

    try:
        entity = await client.get_entity(username)
    except Exception as e:
        console.print(f"  [red]❌ Не удалось получить канал: {e}[/]")
        return 0, 0

    kwargs = {"limit": limit}
    if date_from:
        kwargs["offset_date"] = date_from

    count = 0
    duplicates = 0
    async for message in client.iter_messages(entity, **kwargs):
        if date_to and message.date < date_to:
            console.print(f"  [dim]⏹ Достигли нижней границы[/]")
            break

        if not force and is_duplicate(index, username, message.id):
            duplicates += 1
            continue

        if not message.text:
            continue

        text_lower = message.text.lower()
        if not any(w in text_lower for w in TRIGGER_WORDS):
            continue

        coords = extract_coordinates(message.text)
        entities = extract_entities(message.text)
        category = classify_event(message.text)
        coords, approx = resolve_coordinates(coords, entities)
        save_event(username, title, message, entities, coords, category, approx)
        add_to_index(index, username, message.id)
        count += 1
        console.print(f"  [green]✓[/] [{category}] {message.date:%d.%m %H:%M} — {message.text[:60]}...")

    console.print(f"  [bold]Новых: {count}[/]  [dim]Дубликатов пропущено: {duplicates}[/]")
    return count, duplicates


async def main():
    args = build_parser().parse_args()

    date_from = parse_date_arg(args.date_from) if args.date_from else None
    date_to = parse_date_arg(args.date_to) if args.date_to else None

    console.rule("[bold blue]Telegram OSINT Parser")
    if date_from: console.print(f"📅 От: [cyan]{date_from:%Y-%m-%d %H:%M}[/]")
    if date_to:   console.print(f"📅 До: [cyan]{date_to:%Y-%m-%d %H:%M}[/]")
    if args.force: console.print("[yellow]⚠️  Режим --force: дедупликация отключена[/]")

    all_sources = load_sources()
    sources = filter_sources(all_sources, args)
    if not sources:
        console.print("[red]❌ Нет каналов для парсинга.[/]")
        return

    table = Table(title=f"Выбрано источников: {len(sources)}")
    table.add_column("Канал", style="cyan")
    table.add_column("Группы", style="yellow")
    for s in sources:
        table.add_row(s["username"], ", ".join(s.get("groups", [])) or "—")
    console.print(table)

    index = load_index()
    console.print(f"[dim]📋 В индексе: {len(index)} постов[/]")

    if args.mode == "web":
        console.print("[bold blue]🌐 Режим: веб-превью t.me/s (без API-ключей)[/]")
        total_new, total_dup = run_web_parsing(
            sources, date_from, date_to, args.limit, args.force, index,
            log=lambda m: console.print(m))
        save_index(index)
        console.rule()
        console.print(f"[bold green]🏁 Готово! Новых: {total_new}  Дубликатов: {total_dup}[/]")
        return

    # Получаем credentials из конфига
    api_id, api_hash, phone = get_api_credentials()

    from telethon import TelegramClient
    client = TelegramClient("session_name", api_id, api_hash)
    await client.start(phone=phone)

    total_new = 0
    total_dup = 0
    for source in sources:
        new, dup = await parse_channel(client, source, date_from, date_to, args.limit, index, args.force)
        total_new += new
        total_dup += dup
        await asyncio.sleep(1)

    save_index(index)

    await client.disconnect()
    console.rule()
    console.print(f"[bold green]🏁 Готово! Новых: {total_new}  Дубликатов: {total_dup}[/]")


if __name__ == "__main__":
    asyncio.run(main())