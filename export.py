#!/usr/bin/env python3
"""Экспорт событий из events/ в CSV и Excel."""
import os
import json
import glob
from datetime import datetime

import pandas as pd
from rich.console import Console

console = Console()

EVENTS_DIR = "events"


def load_all_events() -> list[dict]:
    """Загружает все JSON-события из папки events/ рекурсивно."""
    events = []
    pattern = os.path.join(EVENTS_DIR, "**/*.json")
    for path in glob.glob(pattern, recursive=True):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                data["_file"] = os.path.basename(path)
                events.append(data)
        except Exception as e:
            console.print(f"[yellow]⚠️  Пропущен {path}: {e}[/]")
    return events


def flatten_event(e: dict) -> dict:
    """Разворачивает вложенные поля (geo, military) в плоскую структуру для таблицы."""
    coords = e.get("geo", {}).get("coordinates", [])
    coord_str = ""
    if coords:
        c = coords[0]
        coord_str = f"{c['lat']:.6f}, {c['lon']:.6f}"

    return {
        "ID": e.get("id"),
        "Дата": e.get("date", "")[:19].replace("T", " "),
        "Категория": e.get("category"),
        "Канал": e.get("channel"),
        "Username": e.get("channel_username"),
        "Страна": e.get("geo", {}).get("country") or "—",
        "Локация": e.get("geo", {}).get("location_name") or "—",
        "Координаты": coord_str,
        "Тип ракеты": e.get("military", {}).get("missile_type") or "—",
        "Текст поста": e.get("full_text", ""),
        "Ссылка": e.get("link", ""),
    }


def export_csv(events: list[dict], filename: str = "events_export.csv") -> pd.DataFrame:
    """Экспорт в CSV. Кодировка utf-8-sig — чтобы Excel корректно открывал кириллицу."""
    df = pd.DataFrame([flatten_event(e) for e in events])
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    console.print(f"[green]✓ CSV сохранён: {filename}[/] ({len(df)} строк)")
    return df


def export_excel(events: list[dict], filename: str = "events_export.xlsx") -> pd.DataFrame:
    """Экспорт в Excel с форматированием, автофильтром и замороженным заголовком."""
    df = pd.DataFrame([flatten_event(e) for e in events])

    # Сортируем по дате: новые сверху
    df = df.sort_values("Дата", ascending=False).reset_index(drop=True)

    with pd.ExcelWriter(filename, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="События")

        workbook = writer.book
        worksheet = writer.sheets["События"]

        # Формат заголовка
        header_fmt = workbook.add_format({
            "bold": True,
            "bg_color": "#4da3ff",
            "font_color": "#ffffff",
            "border": 1,
            "align": "center",
            "valign": "vcenter",
        })

        # Формат для ссылок (синий, подчёркнутый)
        link_fmt = workbook.add_format({
            "font_color": "#1a73e8",
            "underline": True,
        })

        # Формат для текста поста (перенос строк)
        text_fmt = workbook.add_format({
            "text_wrap": True,
            "valign": "top",
        })

        # Применяем формат к заголовкам
        for col_num, col_name in enumerate(df.columns.values):
            worksheet.write(0, col_num, col_name, header_fmt)

        # Ширины колонок
        worksheet.set_column("A:A", 10)   # ID
        worksheet.set_column("B:B", 18)   # Дата
        worksheet.set_column("C:C", 12)   # Категория
        worksheet.set_column("D:D", 25)   # Канал
        worksheet.set_column("E:E", 20)   # Username
        worksheet.set_column("F:F", 15)   # Страна
        worksheet.set_column("G:G", 20)   # Локация
        worksheet.set_column("H:H", 22)   # Координаты
        worksheet.set_column("I:I", 15)   # Тип ракеты
        worksheet.set_column("J:J", 60)   # Текст поста
        worksheet.set_column("K:K", 40)   # Ссылка

        # Превращаем ссылки в кликабельные гиперссылки
        for row_num, url in enumerate(df["Ссылка"], start=1):
            if url and url != "—":
                worksheet.write_url(row_num, 10, url, link_fmt, url)

        # Включаем перенос текста в колонке "Текст поста"
        for row_num in range(1, len(df) + 1):
            worksheet.write(row_num, 9, df.iloc[row_num - 1]["Текст поста"], text_fmt)

        # Автофильтр по всем колонкам
        worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

        # Заморозить заголовок
        worksheet.freeze_panes(1, 0)

        # Высота строк по содержимому (для текста поста)
        worksheet.set_default_row(15)

    console.print(f"[green]✓ Excel сохранён: {filename}[/] ({len(df)} строк)")
    return df


def main():
    console.rule("[bold blue]Экспорт событий")

    events = load_all_events()
    if not events:
        console.print("[yellow]⚠️  Нет событий для экспорта. Запусти сначала парсер.[/]")
        return

    console.print(f"📦 Загружено событий: [cyan]{len(events)}[/]")

    # Считаем категории
    categories = {}
    for e in events:
        cat = e.get("category", "прочее")
        categories[cat] = categories.get(cat, 0) + 1
    for cat, count in sorted(categories.items()):
        console.print(f"  • {cat}: {count}")

    console.print()

    # Экспортируем оба формата
    export_csv(events)
    export_excel(events)

    console.print()
    console.print("[bold green]🏁 Готово![/]")


if __name__ == "__main__":
    main()