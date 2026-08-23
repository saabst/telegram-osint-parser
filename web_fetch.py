#!/usr/bin/env python3
"""Получение постов публичных каналов через веб-превью t.me/s/<username>.

Работает без API-ключей и аккаунта: Telegram отдаёт HTML-превью публичных
каналов по адресу https://t.me/s/<username>. История подгружается пагинацией
параметром ?before=<id_сообщения>.

Ограничения веб-режима:
  - только публичные каналы (у которых есть @username);
  - только текст постов (медиа не скачивается);
  - приватные каналы и каналы с отключённым превью недоступны.
"""
import html as html_mod
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Iterator
from urllib.parse import quote

import requests

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
PAGE_DELAY = (1.5, 3.0)   # случайная пауза перед запросом страницы, сек
REQUEST_TIMEOUT = 20
MAX_RETRIES = 3


class ChannelUnavailableError(Exception):
    """Канал недоступен через веб-превью (закрыт, удалён или превью выключено)."""


@dataclass
class Post:
    id: int
    date: datetime      # naive UTC (совместимо с dateparser без таймзон)
    text: str | None


_session = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en"})
        _session = s
    return _session


def _fetch(url: str) -> str:
    """GET с задержкой, ретраями и обработкой rate-limit."""
    last_status = None
    for attempt in range(MAX_RETRIES):
        time.sleep(random.uniform(*PAGE_DELAY))
        resp = _get_session().get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code == 429:
            last_status = 429
            time.sleep(10 * (attempt + 1))   # вежливо ждём и пробуем снова
            continue
        if resp.status_code == 404:
            raise ChannelUnavailableError("сервер вернул 404 (канал не найден)")
        resp.raise_for_status()
        return resp.text
    raise RuntimeError(f"t.me не отвечает (HTTP {last_status}) после {MAX_RETRIES} попыток")


# ---------- Разбор HTML ----------

_POST_DIV_RE = re.compile(
    r'<div class="tgme_widget_message\b[^"]*"[^>]*data-post="([^"/]+)/(\d+)"')
_TIME_RE = re.compile(r'<time[^>]*datetime="([^"]+)"')
_TEXT_CLASS_RE = re.compile(r'class="tgme_widget_message_text[^"]*"')
_DIV_TAG_RE = re.compile(r'<(/?)div\b', re.I)


def _extract_text(block: str) -> str | None:
    """Достаёт текст поста из блока tgme_widget_message_text."""
    m = _TEXT_CLASS_RE.search(block)
    if not m:
        return None
    # содержимое начинается после закрывающей '>' открывающего тега div
    gt = block.index(">", m.start()) + 1

    # ищем закрывающий </div> с учётом вложенности
    depth = 1
    end = len(block)
    for t in _DIV_TAG_RE.finditer(block, gt):
        depth += -1 if t.group(1) == "/" else 1
        if depth == 0:
            end = t.start()
            break

    raw = block[gt:end]
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)   # переносы строк
    raw = re.sub(r"<[^>]+>", "", raw)                    # остальные теги
    raw = html_mod.unescape(raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def parse_posts(page_html: str) -> list[Post]:
    """Разбирает страницу превью в список Post (по возрастанию id)."""
    posts = []
    matches = list(_POST_DIV_RE.finditer(page_html))
    for i, m in enumerate(matches):
        block_end = matches[i + 1].start() if i + 1 < len(matches) else len(page_html)
        block = page_html[m.end():block_end]

        tm = _TIME_RE.search(block)
        if not tm:
            continue   # служебный блок без времени — пропускаем

        date = datetime.fromisoformat(tm.group(1)).replace(tzinfo=None)
        posts.append(Post(id=int(m.group(2)), date=date, text=_extract_text(block)))
    return posts


def iter_posts(username: str,
               limit: int = 500,
               date_from: datetime | None = None,
               date_to: datetime | None = None,
               log=None) -> Iterator[Post]:
    """Отдаёт посты канала от новых к старым в границах дат.

    Сам останавливается при достижении date_from, лимита или конца истории.
    Бросает ChannelUnavailableError, если превью недоступно.
    """
    log = log or (lambda m: None)
    username = username.lstrip("@")
    url = f"https://t.me/s/{quote(username)}"
    fetched = 0

    while fetched < limit:
        page_html = _fetch(url)
        posts = parse_posts(page_html)

        if not posts:
            if fetched == 0:
                raise ChannelUnavailableError(
                    f"@{username}: веб-превью недоступно "
                    "(канал закрыт, удалён или превью отключено)")
            break

        # страница отсортирована по возрастанию id — идём от новых к старым
        for post in reversed(posts):
            if date_to is not None and post.date > date_to:
                continue                       # ещё слишком свежие
            if date_from is not None and post.date < date_from:
                return                         # дошли до нижней границы
            fetched += 1
            yield post
            if fetched >= limit:
                break

        oldest_id = posts[0].id                # минимальный id на странице
        if oldest_id <= 1:
            break                              # история кончилась
        url = f"https://t.me/s/{quote(username)}?before={oldest_id}"

    if fetched >= limit:
        log(f"  ⏹ Достигнут лимит {limit} сообщений")


if __name__ == "__main__":
    # Быстрая проверка: python web_fetch.py durov
    import sys
    for p in iter_posts(sys.argv[1] if len(sys.argv) > 1 else "telegram",
                        limit=5, log=print):
        print(f"[{p.id}] {p.date:%d.%m.%Y %H:%M} — {(p.text or '')[:80]}")
