#!/usr/bin/env python3
"""GUI-лаунчер для Telegram OSINT парсера."""
import os
import sys
import json
import asyncio
import threading
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk
import dateparser
from telethon import TelegramClient

# Импортируем функции из parser.py
from parser import (
    load_sources, save_index, load_index, is_duplicate, add_to_index,
    extract_coordinates, extract_entities, classify_event, save_event,
    load_config, save_config,
    TRIGGER_WORDS
)

# Настройки темы
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class ParserGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("🛰 Telegram OSINT Parser")
        self.geometry("1000x750")
        
        # Состояние
        self.sources = load_sources()
        self.config = load_config()
        self.is_running = False
        
        self.setup_ui()
        self.load_sources_to_ui()
    
    def setup_ui(self):
        """Создаёт интерфейс."""
        # Главный контейнер
        main_frame = ctk.CTkFrame(self)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # ===== ВЕРХНЯЯ ПАНЕЛЬ — ДАТЫ И НАСТРОЙКИ =====
        top_frame = ctk.CTkFrame(main_frame)
        top_frame.pack(fill="x", pady=(0, 10))
        
        # Левая часть — даты
        date_frame = ctk.CTkFrame(top_frame)
        date_frame.pack(side="left", fill="x", expand=True)
        
        ctk.CTkLabel(date_frame, text="📅 Период парсинга", font=("", 14, "bold")).pack(anchor="w", pady=(0, 5))
        
        date_row = ctk.CTkFrame(date_frame)
        date_row.pack(fill="x")
        
        ctk.CTkLabel(date_row, text="От:").pack(side="left", padx=(0, 5))
        self.date_from_entry = ctk.CTkEntry(date_row, width=200, placeholder_text="вчера, 2026-08-01, 3 days ago")
        self.date_from_entry.pack(side="left", padx=(0, 20))
        
        ctk.CTkLabel(date_row, text="До:").pack(side="left", padx=(0, 5))
        self.date_to_entry = ctk.CTkEntry(date_row, width=200, placeholder_text="сегодня, 2026-08-15")
        self.date_to_entry.pack(side="left", padx=(0, 20))
        
        self.force_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(date_row, text="Игнорировать дедупликацию", variable=self.force_var).pack(side="left")
        
        # Правая часть — настройки API
        settings_frame = ctk.CTkFrame(top_frame)
        settings_frame.pack(side="right", fill="y")
        
        ctk.CTkLabel(settings_frame, text="⚙️ Настройки", font=("", 14, "bold")).pack(anchor="w", pady=(0, 5))
        
        api_status = "✓ Настроено" if all([self.config.get("api_id"), self.config.get("api_hash"), self.config.get("phone")]) else "✗ Не настроено"
        api_color = "green" if api_status.startswith("✓") else "red"
        
        self.api_status_label = ctk.CTkLabel(settings_frame, text=f"API: {api_status}", text_color=api_color)
        self.api_status_label.pack(anchor="w")
        
        ctk.CTkButton(settings_frame, text="Настроить API", width=150, command=self.open_api_settings).pack(pady=(5, 0))
        
        # ===== СРЕДНЯЯ ПАНЕЛЬ — ИСТОЧНИКИ =====
        middle_frame = ctk.CTkFrame(main_frame)
        middle_frame.pack(fill="both", expand=True, pady=(0, 10))
        
        # Заголовок
        header = ctk.CTkFrame(middle_frame)
        header.pack(fill="x", pady=(0, 5))
        ctk.CTkLabel(header, text="📡 Источники", font=("", 14, "bold")).pack(side="left")
        
        # Кнопки управления
        btn_frame = ctk.CTkFrame(header)
        btn_frame.pack(side="right")
        
        ctk.CTkButton(btn_frame, text="➕ Добавить", width=100, command=self.add_source).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="🗑 Удалить", width=100, command=self.remove_selected).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="✓ Все", width=80, command=self.select_all).pack(side="left", padx=2)
        ctk.CTkButton(btn_frame, text="✗ Никто", width=80, command=self.deselect_all).pack(side="left", padx=2)
        
        # Список источников с чекбоксами
        self.sources_scroll = ctk.CTkScrollableFrame(middle_frame)
        self.sources_scroll.pack(fill="both", expand=True)
        
        self.source_checkboxes = []
        
        # ===== НИЖНЯЯ ПАНЕЛЬ — УПРАВЛЕНИЕ И ЛОГ =====
        bottom_frame = ctk.CTkFrame(main_frame)
        bottom_frame.pack(fill="both", expand=True)
        
        # Кнопки запуска
        control_frame = ctk.CTkFrame(bottom_frame)
        control_frame.pack(fill="x", pady=(0, 5))
        
        self.start_btn = ctk.CTkButton(
            control_frame, text="🚀 Запустить парсинг", font=("", 14, "bold"),
            height=40, command=self.start_parsing
        )
        self.start_btn.pack(side="left", padx=(0, 10))
        
        # Кнопки viewer и экспорта
        viewer_btns = ctk.CTkFrame(control_frame)
        viewer_btns.pack(side="left", padx=(0, 10))
        
        ctk.CTkButton(viewer_btns, text="🌐 Обновить viewer", width=150, command=self.update_viewer).pack(side="left", padx=2)
        ctk.CTkButton(viewer_btns, text="📊 Экспорт в Excel", width=150, command=self.export_excel).pack(side="left", padx=2)
        
        self.progress = ctk.CTkProgressBar(control_frame, width=200)
        self.progress.pack(side="left", padx=(0, 10))
        self.progress.set(0)
        
        self.status_label = ctk.CTkLabel(control_frame, text="Готов к запуску")
        self.status_label.pack(side="left")
        
        # Лог
        ctk.CTkLabel(bottom_frame, text="📋 Лог работы", font=("", 12, "bold")).pack(anchor="w", pady=(5, 2))
        
        self.log_text = ctk.CTkTextbox(bottom_frame, height=150, font=("Consolas", 11))
        self.log_text.pack(fill="both", expand=True)
    
    def load_sources_to_ui(self):
        """Загружает источники в UI."""
        for cb in self.source_checkboxes:
            cb[0].destroy()
        self.source_checkboxes.clear()
        
        for source in self.sources:
            frame = ctk.CTkFrame(self.sources_scroll)
            frame.pack(fill="x", pady=2)
            
            var = ctk.BooleanVar(value=source.get("enabled", True))
            cb = ctk.CTkCheckBox(
                frame,
                text=f"@{source['username']} — {source.get('title', '')}",
                variable=var,
                command=lambda s=source, v=var: self.toggle_source(s, v.get())
            )
            cb.pack(side="left", padx=5, pady=5)
            
            groups = ", ".join(source.get("groups", []))
            if groups:
                ctk.CTkLabel(frame, text=f"[{groups}]", text_color="gray").pack(side="left", padx=5)
            
            self.source_checkboxes.append((cb, var, source))
    
    def toggle_source(self, source: dict, enabled: bool):
        source["enabled"] = enabled
        self.save_sources()
    
    def save_sources(self):
        with open("sources.json", "w", encoding="utf-8") as f:
            json.dump({"sources": self.sources}, f, ensure_ascii=False, indent=2)
    
    def add_source(self):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Добавить источник")
        dialog.geometry("400x300")
        dialog.transient(self)
        dialog.update()
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Username (без @):").pack(anchor="w", padx=20, pady=(20, 5))
        username_entry = ctk.CTkEntry(dialog, width=300)
        username_entry.pack(padx=20)
        
        ctk.CTkLabel(dialog, text="Название:").pack(anchor="w", padx=20, pady=(10, 5))
        title_entry = ctk.CTkEntry(dialog, width=300)
        title_entry.pack(padx=20)
        
        ctk.CTkLabel(dialog, text="Группы (через запятую):").pack(anchor="w", padx=20, pady=(10, 5))
        groups_entry = ctk.CTkEntry(dialog, width=300)
        groups_entry.pack(padx=20)
        
        def save():
            username = username_entry.get().strip().lstrip("@")
            if not username:
                messagebox.showerror("Ошибка", "Введите username")
                return
            
            if any(s["username"].lower() == username.lower() for s in self.sources):
                messagebox.showerror("Ошибка", "Такой канал уже есть")
                return
            
            title = title_entry.get().strip() or username
            groups = [g.strip() for g in groups_entry.get().split(",") if g.strip()]
            
            self.sources.append({
                "username": username,
                "title": title,
                "enabled": True,
                "groups": groups,
            })
            self.save_sources()
            self.load_sources_to_ui()
            dialog.destroy()
        
        ctk.CTkButton(dialog, text="Сохранить", command=save).pack(pady=20)
    
    def remove_selected(self):
        if not self.sources:
            messagebox.showinfo("Информация", "Список источников пуст")
            return
        
        # Создаём диалог выбора
        dialog = ctk.CTkToplevel(self)
        dialog.title("Удалить источники")
        dialog.geometry("500x600")
        dialog.transient(self)
        dialog.update()
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="Выберите каналы для удаления:", font=("", 14, "bold")).pack(pady=(20, 10))
        
        # Scrollable frame для списка
        scroll_frame = ctk.CTkScrollableFrame(dialog, width=450, height=400)
        scroll_frame.pack(padx=20, pady=10, fill="both", expand=True)
        
        # Чекбоксы для выбора
        checkboxes = []
        for source in self.sources:
            frame = ctk.CTkFrame(scroll_frame)
            frame.pack(fill="x", pady=2)
            
            var = ctk.BooleanVar(value=False)
            cb = ctk.CTkCheckBox(
                frame,
                text=f"@{source['username']} — {source.get('title', '')}",
                variable=var
            )
            cb.pack(side="left", padx=5, pady=5)
            
            groups = ", ".join(source.get("groups", []))
            if groups:
                ctk.CTkLabel(frame, text=f"[{groups}]", text_color="gray").pack(side="left", padx=5)
            
            checkboxes.append((var, source))
        
        def confirm_delete():
            to_remove = [s for var, s in checkboxes if var.get()]
            
            if not to_remove:
                messagebox.showinfo("Информация", "Ничего не выбрано", parent=dialog)
                return
            
            if not messagebox.askyesno("Подтверждение", f"Удалить {len(to_remove)} источник(ов)?", parent=dialog):
                return
            
            # Удаляем из основного списка
            self.sources = [s for s in self.sources if s not in to_remove]
            self.save_sources()
            self.load_sources_to_ui()
            dialog.destroy()
        
        # Кнопки управления
        btn_frame = ctk.CTkFrame(dialog)
        btn_frame.pack(pady=10)
        
        ctk.CTkButton(btn_frame, text="Выбрать все", width=120, 
                      command=lambda: [var.set(True) for var, _ in checkboxes]).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Снять все", width=120,
                      command=lambda: [var.set(False) for var, _ in checkboxes]).pack(side="left", padx=5)
        
        ctk.CTkButton(dialog, text="Удалить выбранные", fg_color="red", hover_color="darkred",
                      command=confirm_delete, width=200).pack(pady=(10, 20))
    
    def select_all(self):
        for cb, var, source in self.source_checkboxes:
            var.set(True)
            source["enabled"] = True
        self.save_sources()
    
    def deselect_all(self):
        for cb, var, source in self.source_checkboxes:
            var.set(False)
            source["enabled"] = False
        self.save_sources()
    
    def open_api_settings(self):
        """Открывает диалог настроек API."""
        dialog = ctk.CTkToplevel(self)
        dialog.title("Настройки Telegram API")
        dialog.geometry("500x400")
        dialog.transient(self)
        dialog.update()
        dialog.grab_set()
        
        ctk.CTkLabel(dialog, text="🔑 Telegram API Credentials", font=("", 16, "bold")).pack(pady=(20, 10))
        
        ctk.CTkLabel(dialog, text="Получить API можно на https://my.telegram.org", text_color="gray").pack(pady=(0, 20))
        
        ctk.CTkLabel(dialog, text="API ID (число):").pack(anchor="w", padx=30, pady=(0, 5))
        api_id_entry = ctk.CTkEntry(dialog, width=400)
        api_id_entry.pack(padx=30)
        if self.config.get("api_id"):
            api_id_entry.insert(0, str(self.config["api_id"]))
        
        ctk.CTkLabel(dialog, text="API Hash (строка):").pack(anchor="w", padx=30, pady=(15, 5))
        api_hash_entry = ctk.CTkEntry(dialog, width=400, show="•")
        api_hash_entry.pack(padx=30)
        if self.config.get("api_hash"):
            api_hash_entry.insert(0, self.config["api_hash"])
        
        ctk.CTkLabel(dialog, text="Телефон (с кодом страны):").pack(anchor="w", padx=30, pady=(15, 5))
        phone_entry = ctk.CTkEntry(dialog, width=400)
        phone_entry.pack(padx=30)
        if self.config.get("phone"):
            phone_entry.insert(0, self.config["phone"])
        
        def save():
            api_id = api_id_entry.get().strip()
            api_hash = api_hash_entry.get().strip()
            phone = phone_entry.get().strip()
            
            if not all([api_id, api_hash, phone]):
                messagebox.showerror("Ошибка", "Заполните все поля")
                return
            
            try:
                api_id = int(api_id)
            except ValueError:
                messagebox.showerror("Ошибка", "API ID должен быть числом")
                return
            
            self.config = {
                "api_id": api_id,
                "api_hash": api_hash,
                "phone": phone,
            }
            save_config(self.config)
            
            self.api_status_label.configure(text="API: ✓ Настроено", text_color="green")
            messagebox.showinfo("Успех", "Настройки сохранены!")
            dialog.destroy()
        
        ctk.CTkButton(dialog, text="Сохранить", command=save, width=200).pack(pady=30)
    
    def update_viewer(self):
        """Собирает и открывает HTML viewer."""
        self.log("🌐 Сборка viewer...")
        self.status_label.configure(text="Сборка viewer...")
        
        try:
            # Запускаем build_viewer.py
            result = subprocess.run(
                [sys.executable, "build_viewer.py"],
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            
            if result.returncode != 0:
                self.log(f"❌ Ошибка сборки: {result.stderr}")
                messagebox.showerror("Ошибка", f"Не удалось собрать viewer:\n{result.stderr}")
                return
            
            self.log("✓ Viewer собран")
            
            # Открываем в браузере
            viewer_path = os.path.abspath("viewer.html")
            if os.path.exists(viewer_path):
                webbrowser.open(f"file://{viewer_path}")
                self.log("✓ Открыт в браузере")
                self.status_label.configure(text="Viewer открыт")
            else:
                self.log("❌ viewer.html не найден")
                messagebox.showerror("Ошибка", "viewer.html не найден")
        
        except Exception as e:
            self.log(f"❌ Ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))
            self.status_label.configure(text="Ошибка")
    
    def export_excel(self):
        """Экспортирует события в Excel."""
        self.log("📊 Экспорт в Excel...")
        self.status_label.configure(text="Экспорт...")
        
        try:
            result = subprocess.run(
                [sys.executable, "export.py"],
                capture_output=True,
                text=True,
                encoding="utf-8"
            )
            
            if result.returncode != 0:
                self.log(f"❌ Ошибка экспорта: {result.stderr}")
                messagebox.showerror("Ошибка", f"Не удалось экспортировать:\n{result.stderr}")
                return
            
            self.log("✓ Excel экспортирован")
            self.status_label.configure(text="Экспорт завершён")
            
            # Открываем файл
            excel_path = os.path.abspath("events_export.xlsx")
            if os.path.exists(excel_path):
                if sys.platform == "win32":
                    os.startfile(excel_path)
                elif sys.platform == "darwin":
                    subprocess.run(["open", excel_path])
                else:
                    subprocess.run(["xdg-open", excel_path])
                self.log("✓ Файл открыт")
        
        except Exception as e:
            self.log(f"❌ Ошибка: {e}")
            messagebox.showerror("Ошибка", str(e))
            self.status_label.configure(text="Ошибка")
    
    def log(self, message: str):
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.update()
    
    def parse_date(self, value: str) -> datetime | None:
        if not value:
            return None
        dt = dateparser.parse(
            value,
            languages=["ru", "en"],
            settings={"PREFER_DAY_OF_MONTH": "first", "PREFER_DATES_FROM": "past"}
        )
        return dt
    
    def start_parsing(self):
        if self.is_running:
            messagebox.showwarning("Внимание", "Парсинг уже запущен")
            return
        
        # Проверяем API credentials
        if not all([self.config.get("api_id"), self.config.get("api_hash"), self.config.get("phone")]):
            messagebox.showerror("Ошибка", "Сначала настройте API credentials")
            return
        
        selected = [s for _, var, s in self.source_checkboxes if var.get()]
        if not selected:
            messagebox.showerror("Ошибка", "Выберите хотя бы один источник")
            return
        
        try:
            date_from = self.parse_date(self.date_from_entry.get())
            date_to = self.parse_date(self.date_to_entry.get())
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось распознать дату: {e}")
            return
        
        self.is_running = True
        self.start_btn.configure(state="disabled", text="⏳ Парсинг...")
        self.progress.set(0)
        self.log_text.delete("1.0", "end")
        
        thread = threading.Thread(
            target=self.run_parser,
            args=(selected, date_from, date_to, self.force_var.get()),
            daemon=True
        )
        thread.start()
    
    def run_parser(self, sources: list[dict], date_from, date_to, force: bool):
        try:
            api_id, api_hash, phone = self.config["api_id"], self.config["api_hash"], self.config["phone"]
            
            self.log(f"🚀 Запуск парсера")
            self.log(f"📡 Источников: {len(sources)}")
            if date_from:
                self.log(f"📅 От: {date_from:%Y-%m-%d %H:%M}")
            if date_to:
                self.log(f"📅 До: {date_to:%Y-%m-%d %H:%M}")
            if force:
                self.log("⚠️  Режим: игнорировать дедупликацию")
            self.log("")
            
            index = load_index()
            self.log(f"📋 В индексе: {len(index)} постов\n")
            
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def parse_all():
                client = TelegramClient("session_name", api_id, api_hash)
                await client.start(phone=phone)
                
                total_new = 0
                total_dup = 0
                
                for i, source in enumerate(sources):
                    username = source["username"]
                    title = source.get("title", username)
                    
                    self.log(f"📡 {title} (@{username})")
                    self.status_label.configure(text=f"Парсинг: {title}")
                    self.progress.set((i + 1) / len(sources))
                    
                    try:
                        entity = await client.get_entity(username)
                    except Exception as e:
                        self.log(f"  ❌ Не удалось получить канал: {e}\n")
                        continue
                    
                    kwargs = {"limit": 500}
                    if date_from:
                        kwargs["offset_date"] = date_from
                    
                    count = 0
                    duplicates = 0
                    
                    async for message in client.iter_messages(entity, **kwargs):
                        if date_to and message.date < date_to:
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
                        save_event(username, title, message, entities, coords, category)
                        add_to_index(index, username, message.id)
                        count += 1
                        
                        self.log(f"  ✓ [{category}] {message.date:%d.%m %H:%M} — {message.text[:60]}...")
                    
                    self.log(f"  Новых: {count}  Дубликатов: {duplicates}\n")
                    total_new += count
                    total_dup += duplicates
                    
                    await asyncio.sleep(1)
                
                await client.disconnect()
                return total_new, total_dup
            
            total_new, total_dup = loop.run_until_complete(parse_all())
            
            save_index(index)
            
            self.log(f"\n🏁 Готово! Новых: {total_new}  Дубликатов: {total_dup}")
            self.status_label.configure(text="Готово")
            self.progress.set(1.0)
            
            messagebox.showinfo("Готово", f"Парсинг завершён!\nНовых: {total_new}\nДубликатов: {total_dup}")
        
        except Exception as e:
            self.log(f"\n❌ Ошибка: {e}")
            self.status_label.configure(text="Ошибка")
            messagebox.showerror("Ошибка", str(e))
        
        finally:
            self.is_running = False
            self.start_btn.configure(state="normal", text="🚀 Запустить парсинг")


if __name__ == "__main__":
    app = ParserGUI()
    app.mainloop()