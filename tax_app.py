#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расчёт ТН 2026 — С БАЗОЙ ДАННЫХ АВТОПАРКА
Хранит ТС между сессиями, позволяет добавлять/удалять вручную
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import tkinter.simpledialog
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import threading
import json
import os
import re
import sqlite3
from contextlib import contextmanager

def _parse_ru_date(s):
    """Парсит дату в формате ДД.ММ.ГГГГ или ДД-ММ-ГГГГ в строку ГГГГ-ММ-ДД для БД"""
    if not s or str(s).strip() == "":
        return ""
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    for sep in [".", "-"]:
        parts = s.split(sep)
        if len(parts) == 3:
            try:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                dt = datetime(y, m, d)
                return dt.strftime("%Y-%m-%d")
            except (ValueError, IndexError):
                pass
    return s


def _db_date_to_ru(s):
    """Конвертирует дату из БД (ГГГГ-ММ-ДД) в русский формат (ДД.ММ.ГГГГ)"""
    if not s or str(s).strip() == "" or str(s).strip() in ("None", "nan"):
        return ""
    s = str(s).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        try:
            y, m, d = s.split("-")
            return f"{d}.{m}.{y}"
        except:
            return s
    # Если уже в русском формате — оставляем
    return s


class VehicleDatabase:
    """Управление базой данных транспортных средств"""

    DB_FILE = "vehicle_fleet.db"

    def __init__(self, db_file=None):
        self.DB_FILE = db_file or VehicleDatabase.DB_FILE
        self._memory_conn = None  # Для :memory: режима
        self.init_database()

    @contextmanager
    def get_connection(self):
        # Для :memory: базы используем одно соединение
        if self.DB_FILE == ":memory:":
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(":memory:")
                self._memory_conn.row_factory = sqlite3.Row
            conn = self._memory_conn
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
        else:
            conn = sqlite3.connect(self.DB_FILE)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise e
            finally:
                conn.close()

    def init_database(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                марка TEXT, модель TEXT, гос_номер TEXT,
                мощность REAL, год_выпуска INTEGER, тип_тс TEXT,
                vin TEXT, инв_номер TEXT, дата_постановки DATE, дата_списания DATE,
                статус TEXT DEFAULT 'active', примечание TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS tax_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER, год_расчёта INTEGER,
                ставка REAL, сумма_налога REAL,
                рассчитано_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles(id))""")
            cursor.execute("""CREATE TABLE IF NOT EXISTS change_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER, действие TEXT,
                старое_значение TEXT, новое_значение TEXT,
                пользователь TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON vehicles(статус)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_gos_number ON vehicles(гос_номер)"
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_type ON vehicles(тип_тс)")

    def add_vehicle(self, data):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO vehicles
                (марка, модель, гос_номер, мощность, год_выпуска, тип_тс, vin, инв_номер, дата_постановки, дата_списания, статус, примечание)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.get("марка", ""),
                    data.get("модель", ""),
                    data.get("гос_номер", ""),
                    data.get("мощность", 0),
                    data.get("год_выпуска", datetime.now().year),
                    data.get("тип_тс", "легковые"),
                    data.get("vin", ""),
                    data.get("инв_номер", ""),
                    data.get("дата_постановки", datetime.now().strftime("%Y-%m-%d")),
                    data.get("дата_списания", ""),
                    "active",
                    data.get("примечание", ""),
                ),
            )
            vehicle_id = cursor.lastrowid
            self._log_change(conn, vehicle_id, "create", None, str(data))
            return vehicle_id

    def update_vehicle(self, vehicle_id, data):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,))
            old_data = dict(cursor.fetchone())
            set_clause = (
                ", ".join([f"{k} = ?" for k in data.keys()])
                + ", updated_at = CURRENT_TIMESTAMP"
            )
            values = list(data.values()) + [vehicle_id]
            cursor.execute(f"UPDATE vehicles SET {set_clause} WHERE id = ?", values)
            self._log_change(conn, vehicle_id, "update", str(old_data), str(data))

    def delete_vehicle(self, vehicle_id, soft_delete=True):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if soft_delete:
                cursor.execute(
                    """UPDATE vehicles SET статус = 'disposed', дата_списания = ? WHERE id = ?""",
                    (datetime.now().strftime("%Y-%m-%d"), vehicle_id),
                )
            else:
                cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            self._log_change(conn, vehicle_id, "delete", "active", "disposed")

    def get_all_vehicles(self, status="active"):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles WHERE статус = ?", (status,))
            return [dict(row) for row in cursor.fetchall()]

    def get_vehicle_by_id(self, vehicle_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def get_vehicle_by_gos_number(self, gos_number):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles WHERE гос_номер = ?", (gos_number,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def save_tax_calculation(self, vehicle_id, year, rate, tax_amount):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM tax_history WHERE vehicle_id = ? AND год_расчёта = ?",
                (vehicle_id, year),
            )
            cursor.execute(
                "INSERT INTO tax_history (vehicle_id, год_расчёта, ставка, сумма_налога) VALUES (?, ?, ?, ?)",
                (vehicle_id, year, rate, tax_amount),
            )

    def get_tax_history(self, vehicle_id):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM tax_history WHERE vehicle_id = ? ORDER BY год_расчёта DESC",
                (vehicle_id,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_year_summary(self, year):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """SELECT v.тип_тс, COUNT(*) as количество,
                SUM(t.сумма_налога) as общая_сумма, AVG(t.сумма_налога) as средняя_сумма
                FROM tax_history t JOIN vehicles v ON t.vehicle_id = v.id
                WHERE t.год_расчёта = ? AND v.статус = 'active' GROUP BY v.тип_тс""",
                (year,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def get_changes_since(self, date_str):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM change_log WHERE created_at > ? ORDER BY created_at DESC",
                (date_str,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def _log_change(self, conn, vehicle_id, action, old_val, new_val):
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO change_log (vehicle_id, действие, старое_значение, новое_значение, пользователь) VALUES (?, ?, ?, ?, ?)",
            (vehicle_id, action, old_val, new_val, "system"),
        )

    def export_to_excel(self, filename):
        with self.get_connection() as conn:
            vehicles_df = pd.read_sql_query(
                "SELECT * FROM vehicles WHERE статус = ?", conn, params=("active",)
            )
            tax_df = pd.read_sql_query(
                "SELECT vehicle_id, год_расчёта, ставка, сумма_налога FROM tax_history",
                conn,
            )

        # Объединяем — берём последний расчёт по каждому ТС
        if not tax_df.empty:
            latest_tax = tax_df.sort_values(
                "год_расчёта", ascending=False
            ).drop_duplicates("vehicle_id")
            merged = vehicles_df.merge(
                latest_tax, left_on="id", right_on="vehicle_id", how="left"
            )
        else:
            merged = vehicles_df.copy()
            merged["ставка"] = ""
            merged["сумма_налога"] = ""
            merged["год_расчёта"] = ""

        # Оставляем нужные колонки в читаемом порядке
        cols_order = [
            "инв_номер",
            "марка",
            "модель",
            "гос_номер",
            "мощность",
            "год_выпуска",
            "тип_тс",
            "vin",
            "дата_постановки",
            "дата_списания",
            "ставка",
            "год_расчёта",
            "сумма_налога",
            "примечание",
        ]
        cols_exist = [c for c in cols_order if c in merged.columns]
        merged[cols_exist].to_excel(filename, index=False, sheet_name="Автопарк")

    def import_from_excel(self, df_or_filepath, mapping=None):
        if isinstance(df_or_filepath, str):
            df = pd.read_excel(df_or_filepath)
        else:
            df = df_or_filepath
        if mapping:
            rename = {v: k for k, v in mapping.items() if v and str(v) in df.columns}
            df = df.rename(columns=rename)
        else:
            df.columns = df.columns.str.lower().str.strip()

        # Нормализация данных
        df = DataNormalizer().normalize_dataframe(df)

        added, skipped, errors = 0, 0, []
        for idx, row in df.iterrows():
            try:
                мощность = row.get("мощность", None)
                if мощность is None or pd.isna(мощность):
                    errors.append(f"Строка {idx + 2}: нет мощности")
                    continue
                год = row.get("год_выпуска", None)
                if год is None or pd.isna(год):
                    errors.append(f"Строка {idx + 2}: нет года выпуска")
                    continue
                gos = str(row.get("гос_номер", "")).strip()
                if gos.lower() == "nan":
                    gos = ""
                инв_val = row.get("инв_номер")
                if pd.isna(инв_val) or str(инв_val).strip() == "":
                    инв = ""
                else:
                    инв = str(инв_val).strip()
                # Обработка дат: Excel может вернуть datetime
                def to_date_str(val):
                    if pd.isna(val) or val is None or str(val).strip() == "":
                        return ""
                    if isinstance(val, datetime):
                        return val.strftime("%Y-%m-%d")
                    if hasattr(val, 'strftime'):  # pandas Timestamp
                        return val.strftime("%Y-%m-%d")
                    return str(val).strip()

                data = {
                    "марка": str(row.get("марка", "")),
                    "модель": str(row.get("модель", "")),
                    "гос_номер": gos,
                    "мощность": float(мощность),
                    "год_выпуска": int(год),
                    "тип_тс": str(row.get("тип_тс", "легковые")),
                    "vin": str(row.get("vin", "")),
                    "инв_номер": инв,
                    "дата_постановки": to_date_str(row.get("дата_постановки", "")),
                    "дата_списания": to_date_str(row.get("дата_списания", "")),
                    "примечание": str(row.get("примечание", "")),
                }
                self.add_vehicle(data)
                added += 1
            except Exception as e:
                errors.append(f"Строка {idx + 2}: {e}")
        return added, skipped, errors


# ============================================================================
# МОДУЛЬ 2: НОРМАЛИЗАЦИЯ ДАННЫХ
# ============================================================================


class DataNormalizer:
    """Нормализация данных при импорте"""

    TYPE_MAPPING = {
        "легк": "легковые",
        "легковой": "легковые",
        "car": "легковые",
        "passenger": "легковые",
        "груз": "грузовые",
        "грузовой": "грузовые",
        "truck": "грузовые",
        "cargo": "грузовые",
        "автобус": "автобусы",
        "bus": "автобусы",
        "пасс": "автобусы",
        "мото": "мотоциклы",
        "motorcycle": "мотоциклы",
        "байк": "мотоциклы",
        "спец": "спецтехника",
        "трактор": "спецтехника",
        "погрузчик": "спецтехника",
    }

    @staticmethod
    def normalize_gos_number(value):
        if pd.isna(value):
            return ""
        value = str(value).upper().replace(" ", "")
        for lat, cyr in {
            "A": "А",
            "B": "В",
            "E": "Е",
            "K": "К",
            "M": "М",
            "H": "Н",
            "O": "О",
            "P": "Р",
            "C": "С",
            "T": "Т",
            "Y": "У",
            "X": "Х",
        }.items():
            value = value.replace(lat, cyr)
        return value

    @staticmethod
    def normalize_vehicle_type(value):
        if pd.isna(value):
            return "легковые"
        val = str(value).lower().strip()
        for key, vtype in DataNormalizer.TYPE_MAPPING.items():
            if key in val:
                return vtype
        return (
            val
            if val in ["легковые", "грузовые", "автобусы", "мотоциклы", "спецтехника"]
            else "легковые"
        )

    @staticmethod
    def normalize_power(value):
        try:
            s = str(value).replace(",", ".").strip().lower()
            # Определяем единицу измерения
            is_kwt = "квт" in s or "kw" in s or "квт" in s
            # Убираем единицы измерения
            s = re.sub(r"[^\d.]", "", s)
            hp = float(s)
            if hp <= 0 or hp >= 3000:
                return None
            # Переводим кВт в л.с.
            if is_kwt:
                hp = round(hp * 1.3596, 2)
            return hp
        except:
            return None

    @staticmethod
    def normalize_year(value):
        try:
            year = int(float(str(value).replace(",", ".").strip()))
            return year if 1900 <= year <= datetime.now().year + 1 else None
        except:
            return None

    def normalize_dataframe(self, df):
        df = df.copy()
        if "гос_номер" in df.columns:
            df["гос_номер"] = df["гос_номер"].apply(self.normalize_gos_number)
        if "тип_тс" in df.columns:
            df["тип_тс"] = df["тип_тс"].apply(self.normalize_vehicle_type)
        if "мощность" in df.columns:
            df["мощность"] = df["мощность"].apply(self.normalize_power)
        if "год_выпуска" in df.columns:
            df["год_выпуска"] = df["год_выпуска"].apply(self.normalize_year)
        return df


# ============================================================================
# МОДУЛЬ 3: СТАВКИ (с поддержкой регионов и возраста ТС)
# ============================================================================


class AutoConfigLoader:
    CACHE_FILE = "tax_config_cache.json"

    REGION_TABLE_SOURCES = {
        "Пермский край": "https://tcnalog.ru/reg-stavki-transportnogo-naloga-Permskij-kraj.html",
        "Москва": "https://tcnalog.ru/reg-stavki-transportnogo-naloga-Moskva.html",
        "Санкт-Петербург": "https://tcnalog.ru/reg-stavki-transportnogo-naloga-Sankt-Peterburg.html",
        "Свердловская область": "https://tcnalog.ru/reg-stavki-transportnogo-naloga-Sverdlovskaya-oblast.html",
        "Краснодарский край": "https://tcnalog.ru/reg-stavki-transportnogo-naloga-Krasnodarskij-kraj.html",
    }

    def __init__(self):
        self.rates = {}
        self.rates_by_age = {}
        self.last_update = None
        self.source_name = "Локальный кэш"

    def load_config(self, force_update=False, region="Пермский край"):
        if not force_update and os.path.exists(self.CACHE_FILE):
            if self._load_from_cache() and self._is_cache_fresh():
                return True, "Загружено из кэша"
        success, msg = self._fetch_from_web(region)
        if success:
            self._save_to_cache()
            return True, msg
        if self._load_from_cache():
            return True, "Интернет недоступен. Использован кэш."
        self._load_fallback_rates(region)
        return True, f"Нет кэша и интернета. Загружены базовые ставки РФ."

    def _load_from_cache(self):
        try:
            with open(self.CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.rates = self._convert_rates_keys(data.get("rates", {}))
                self.rates_by_age = self._convert_rates_keys(data.get("rates_by_age", {}))
                self.last_update = data.get("timestamp")
                self.source_name = data.get("source", "Кэш")
                return bool(self.rates)
        except:
            return False

    def _convert_rate_keys(self, rates_dict):
        """Преобразует строковые ключи '(0, 100)' обратно в кортежи"""
        if not rates_dict:
            return rates_dict
        result = {}
        for vtype, rates in rates_dict.items():
            result[vtype] = {}
            for key_str, rate in rates.items():
                try:
                    # Убираем скобки и разбиваем
                    key_str = key_str.strip("()")
                    parts = key_str.split(",")
                    min_val = int(parts[0].strip())
                    max_str = parts[1].strip()
                    max_val = float("inf") if max_str == "inf" or "1000000" in max_str else int(max_str)
                    result[vtype][(min_val, max_val)] = rate
                except:
                    # Если не удалось преобразовать, пропускаем
                    continue
        return result

    def _save_to_cache(self):
        with open(self.CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "rates": self._serialize_rates(self.rates),
                    "rates_by_age": self._serialize_rates(getattr(self, "rates_by_age", {})),
                    "timestamp": datetime.now().isoformat(),
                    "source": self.source_name,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    def _serialize_rates(self, rates_dict):
        """Преобразует кортежи-ключи в строки для JSON"""
        if not rates_dict:
            return rates_dict
        result = {}
        for vtype, rates in rates_dict.items():
            result[vtype] = {}
            for key_tuple, rate in rates.items():
                min_val, max_val = key_tuple
                max_str = "inf" if max_val == float("inf") else str(max_val)
                key_str = f"({min_val}, {max_str})"
                result[vtype][key_str] = rate
        return result

    def _is_cache_fresh(self):
        try:
            return (datetime.now() - datetime.fromisoformat(self.last_update)).days < 30
        except:
            return False

    def _fetch_from_web(self, region="Пермский край"):
        url = self.REGION_TABLE_SOURCES.get(region)
        if not url:
            return False, f"Нет источника для: {region}"
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get(url, timeout=15, headers=headers)
            if resp.status_code == 200:
                parsed = self._parse_html(resp.text)
                if parsed:
                    self.rates = parsed
                    self.source_name = f"tcnalog.ru ({region})"
                    self.last_update = datetime.now().isoformat()
                    return True, f"Обновлено с сайта: {region}"
        except Exception:
            pass
        return False, f"Не удалось загрузить ставки для: {region}"

    def _parse_html(self, html):
        soup = BeautifulSoup(html, "html.parser")
        rates = {}
        for table in soup.find_all("table"):
            text = table.get_text().lower()
            vtype = None
            for t, kws in [
                ("легковые", ["легковые"]),
                ("грузовые", ["грузовые"]),
                ("автобусы", ["автобусы"]),
                ("мотоциклы", ["мотоциклы"]),
                ("спецтехника", ["трактор", "спецтехника"]),
            ]:
                if any(k in text for k in kws):
                    vtype = t
                    break
            if not vtype:
                continue
            type_rates = {}
            for row in table.find_all("tr"):
                cols = row.find_all("td")
                if len(cols) >= 2:
                    try:
                        low, high = self._parse_range(cols[0].text.strip())
                        if low is None:
                            continue
                        rate = int("".join(filter(str.isdigit, cols[-1].text.strip())))
                        if rate > 0:
                            type_rates[(low, high)] = rate
                    except:
                        continue
            if type_rates:
                rates[vtype] = type_rates
        return rates if rates else None

    def _parse_range(self, text):
        text = text.lower()
        nums = list(map(int, re.findall(r"\d+", text)))
        if "до" in text:
            return (0, nums[0]) if nums else (None, None)
        elif "свыше" in text or "более" in text:
            return (nums[0], float("inf")) if nums else (None, None)
        elif "-" in text:
            return (nums[0], nums[1]) if len(nums) >= 2 else (None, None)
        elif len(nums) == 1:
            return 0, nums[0]
        return None, None

    def _load_fallback_rates(self, region="Пермский край"):
        REGIONS = {
            "Пермский край": {
                "by_age": {
                    (0, 5): {
                        (0, 100): 25,
                        (100, 125): 33,
                        (125, 150): 35,
                        (150, 175): 47,
                        (175, 200): 50,
                        (200, 225): 65,
                        (225, 250): 72,
                        (250, 275): 90,
                        (275, 300): 105,
                        (300, float("inf")): 135,
                    },
                    (5, 10): {
                        (0, 100): 23,
                        (100, 125): 32,
                        (125, 150): 34,
                        (150, 175): 46,
                        (175, 200): 49,
                        (200, 225): 63,
                        (225, 250): 70,
                        (250, 275): 85,
                        (275, 300): 100,
                        (300, float("inf")): 125,
                    },
                    (10, 15): {
                        (0, 100): 22,
                        (100, 125): 31,
                        (125, 150): 33,
                        (150, 175): 45,
                        (175, 200): 48,
                        (200, 225): 62,
                        (225, 250): 68,
                        (250, 275): 80,
                        (275, 300): 95,
                        (300, float("inf")): 120,
                    },
                    (15, float("inf")): {
                        (0, 100): 20,
                        (100, 125): 30,
                        (125, 150): 32,
                        (150, 175): 44,
                        (175, 200): 47,
                        (200, 225): 60,
                        (225, 250): 65,
                        (250, 275): 75,
                        (275, 300): 92,
                        (300, float("inf")): 115,
                    },
                },
                "rates": {
                    "легковые": {
                        (0, 100): 25,
                        (100, 125): 33,
                        (125, 150): 35,
                        (150, 175): 47,
                        (175, 200): 50,
                        (200, 225): 65,
                        (225, 250): 72,
                        (250, 275): 90,
                        (275, 300): 105,
                        (300, float("inf")): 135,
                    },
                    "грузовые": {
                        (0, 100): 25,
                        (100, 150): 40,
                        (150, 200): 50,
                        (200, 250): 65,
                        (250, float("inf")): 85,
                    },
                    "мотоциклы": {
                        (0, 20): 10,
                        (20, 35): 20,
                        (35, 75): 30,
                        (75, 100): 40,
                        (100, float("inf")): 50,
                    },
                    "автобусы": {(0, 200): 50, (200, float("inf")): 85},
                    "снегоходы": {(0, 50): 15, (50, float("inf")): 30},
                    "катера": {(0, 100): 30, (100, float("inf")): 50},
                    "яхты": {(0, 100): 50, (100, float("inf")): 80},
                    "гидроциклы": {(0, 100): 50, (100, float("inf")): 100},
                    "спецтехника": {(0, float("inf")): 25},
                },
            },
            "Москва": {
                "by_age": {
                    (0, float("inf")): {
                        (0, 100): 12,
                        (100, 125): 25,
                        (125, 150): 35,
                        (150, 175): 45,
                        (175, 200): 50,
                        (200, 225): 65,
                        (225, 250): 75,
                        (250, float("inf")): 150,
                    }
                },
                "rates": {
                    "легковые": {
                        (0, 100): 12,
                        (100, 125): 25,
                        (125, 150): 35,
                        (150, 175): 45,
                        (175, 200): 50,
                        (200, 225): 65,
                        (225, 250): 75,
                        (250, float("inf")): 150,
                    },
                    "грузовые": {
                        (0, 100): 15,
                        (100, 150): 26,
                        (150, 200): 38,
                        (200, 250): 55,
                        (250, float("inf")): 70,
                    },
                    "мотоциклы": {(0, 20): 7, (20, 35): 15, (35, float("inf")): 50},
                    "автобусы": {(0, 200): 55, (200, float("inf")): 80},
                    "спецтехника": {(0, float("inf")): 50},
                },
            },
            "Санкт-Петербург": {
                "by_age": {
                    (0, float("inf")): {
                        (0, 100): 24,
                        (100, 150): 35,
                        (150, 200): 50,
                        (200, 250): 75,
                        (250, float("inf")): 150,
                    }
                },
                "rates": {
                    "легковые": {
                        (0, 100): 24,
                        (100, 150): 35,
                        (150, 200): 50,
                        (200, 250): 75,
                        (250, float("inf")): 150,
                    },
                    "грузовые": {
                        (0, 100): 25,
                        (100, 150): 40,
                        (150, 200): 50,
                        (200, 250): 55,
                        (250, float("inf")): 65,
                    },
                    "мотоциклы": {(0, 20): 10, (20, 35): 20, (35, float("inf")): 50},
                    "автобусы": {(0, 200): 50, (200, float("inf")): 65},
                    "спецтехника": {(0, float("inf")): 25},
                },
            },
            "Свердловская область": {
                "by_age": {
                    (0, float("inf")): {
                        (0, 100): 2,
                        (100, 150): 9,
                        (150, 200): 32,
                        (200, 250): 60,
                        (250, float("inf")): 60,
                    }
                },
                "rates": {
                    "легковые": {
                        (0, 100): 2,
                        (100, 150): 9,
                        (150, 200): 32,
                        (200, 250): 60,
                        (250, float("inf")): 60,
                    },
                    "грузовые": {
                        (0, 100): 2,
                        (100, 150): 6,
                        (150, 200): 8,
                        (200, 250): 14,
                        (250, float("inf")): 17,
                    },
                    "мотоциклы": {(0, 20): 2, (20, 35): 4, (35, float("inf")): 10},
                    "автобусы": {(0, 200): 7, (200, float("inf")): 14},
                    "спецтехника": {(0, float("inf")): 4},
                },
            },
            "Краснодарский край": {
                "by_age": {
                    (0, float("inf")): {
                        (0, 100): 12,
                        (100, 150): 25,
                        (150, 200): 50,
                        (200, 250): 75,
                        (250, float("inf")): 150,
                    }
                },
                "rates": {
                    "легковые": {
                        (0, 100): 12,
                        (100, 150): 25,
                        (150, 200): 50,
                        (200, 250): 75,
                        (250, float("inf")): 150,
                    },
                    "грузовые": {
                        (0, 100): 20,
                        (100, 150): 25,
                        (150, 200): 33,
                        (200, 250): 45,
                        (250, float("inf")): 58,
                    },
                    "мотоциклы": {(0, 20): 6, (20, 35): 12, (35, float("inf")): 25},
                    "автобусы": {(0, 200): 35, (200, float("inf")): 55},
                    "спецтехника": {(0, float("inf")): 14},
                },
            },
        }
        data = REGIONS.get(region, REGIONS["Пермский край"])
        self.rates_by_age = data["by_age"]
        self.rates = data["rates"]
        self.source_name = f"Ставки 2026 ({region})"


# ============================================================================
# ДИАЛОГ ВЫБОРА ОРГАНИЗАЦИИ
# ============================================================================


class OrgSelector:
    """Диалог выбора или создания организации при запуске"""

    ORGS_FILE = "organizations.json"

    def __init__(self, root=None):
        # Используем переданный root или создаём свой
        if root is not None:
            self.root = root
            self.own_root = False
        else:
            self.root = tk.Tk()
            self.own_root = True
            self.root.withdraw()
        self.selected_db = None
        self.selected_org = None
        self.orgs = self._load_orgs()
        self._show()

    def _load_orgs(self):
        if os.path.exists(self.ORGS_FILE):
            try:
                with open(self.ORGS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
            except Exception:
                pass
        return {}

    def _save_orgs(self):
        with open(self.ORGS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.orgs, f, ensure_ascii=False, indent=2)

    def _show(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Выбор организации")
        dialog.geometry("420x380")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        try:
            import sys

            # Определяем базовую папку для PyInstaller и Nuitka
            if hasattr(sys, "_MEIPASS"):  # PyInstaller
                base = sys._MEIPASS
            elif hasattr(sys, "frozen") or "__compiled__" in globals():  # Nuitka
                base = os.path.dirname(sys.executable)
            else:  # Обычный Python
                base = os.path.dirname(os.path.abspath(__file__))
            dialog.iconbitmap(os.path.join(base, "icon.ico"))
        except:
            pass

        tk.Label(
            dialog, text="🏢 Выберите организацию", font=("Segoe UI", 12, "bold")
        ).pack(pady=(15, 5))
        tk.Label(dialog, text="или создайте новую", fg="gray").pack()

        # Список организаций
        frame = tk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=15, pady=10)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            frame,
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 10),
            selectmode="single",
            height=8,
        )
        self.listbox.pack(fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)

        for name in self.orgs:
            self.listbox.insert("end", name)

        self.listbox.bind("<Double-1>", lambda e: self._select(dialog))

        # Кнопки
        btn_frame = tk.Frame(dialog)
        btn_frame.pack(fill="x", padx=15, pady=5)

        tk.Button(
            btn_frame,
            text="✅ Открыть",
            command=lambda: self._select(dialog),
            bg="#e8f5e9",
            width=12,
        ).pack(side="left", padx=3)
        tk.Button(
            btn_frame,
            text="➕ Новая",
            command=lambda: self._create(dialog),
            bg="#e3f2fd",
            width=12,
        ).pack(side="left", padx=3)
        tk.Button(
            btn_frame,
            text="🗑️ Удалить",
            command=lambda: self._delete(dialog),
            bg="#ffebee",
            width=12,
        ).pack(side="left", padx=3)

        # Сводный режим
        tk.Frame(dialog, height=1, bg="#ccc").pack(fill="x", padx=15, pady=5)
        tk.Button(
            dialog,
            text="📊 Сводный режим (все организации)",
            command=lambda: self._summary_mode(dialog),
            bg="#fff9c4",
            width=35,
        ).pack(pady=5)

        dialog.protocol("WM_DELETE_WINDOW", lambda: (dialog.destroy(), self._cleanup()))
        self.root.wait_window(dialog)
        self._cleanup()

    def _cleanup(self):
        if self.own_root and self.root:
            try:
                self.root.destroy()
            except:
                pass

    def _select(self, dialog):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning(
                "Внимание", "Выберите организацию из списка", parent=dialog
            )
            return
        name = self.listbox.get(sel[0])
        self.selected_org = name
        self.selected_db = self.orgs[name]
        dialog.destroy()

    def _create(self, dialog):
        name = tk.simpledialog.askstring(
            "Новая организация", "Введите название организации:", parent=dialog
        )
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.orgs:
            messagebox.showwarning(
                "Внимание", "Организация уже существует", parent=dialog
            )
            return
        # Имя файла БД — транслитерация + sanitize
        safe = re.sub(r"[^\w]", "_", name)[:30]
        db_file = f"fleet_{safe}.db"
        self.orgs[name] = db_file
        self._save_orgs()
        self.listbox.insert("end", name)

        # Программно выбираем новый элемент и вызываем стандартный обработчик
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self.listbox.size() - 1)
        self._select(dialog)

    def _delete(self, dialog):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self.listbox.get(sel[0])
        if not messagebox.askyesno(
            "Удаление",
            f"Удалить организацию «{name}»?\nФайл базы данных останется на диске.",
            parent=dialog,
        ):
            return
        del self.orgs[name]
        self._save_orgs()
        self.listbox.delete(sel[0])

    def _summary_mode(self, dialog):
        self.selected_org = "__summary__"
        self.selected_db = list(self.orgs.values())
        dialog.destroy()


# ============================================================================
# ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ============================================================================


class TaxApp:
    def __init__(self, root, org_name="", db_file=None):
        self.root = root
        self.org_name = org_name
        self.is_summary = org_name == "__summary__"
        title = (
            "📊 Сводный режим — все организации"
            if self.is_summary
            else f"🚗 {org_name} — Расчёт ТН 2026"
        )
        self.root.title(title)
        self.root.state("zoomed")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            import sys

            # Определяем базовую папку для PyInstaller и Nuitka
            if hasattr(sys, "_MEIPASS"):  # PyInstaller
                base = sys._MEIPASS
            elif hasattr(sys, "frozen") or "__compiled__" in globals():  # Nuitka
                base = os.path.dirname(sys.executable)
            else:  # Обычный Python
                base = os.path.dirname(os.path.abspath(__file__))
            self.root.iconbitmap(os.path.join(base, "icon.ico"))
        except Exception:
            pass

        # В сводном режиме — несколько БД, иначе одна
        if self.is_summary and isinstance(db_file, list):
            self.db = VehicleDatabase(db_file[0]) if db_file else VehicleDatabase()
            self.all_dbs = [VehicleDatabase(f) for f in db_file]
        else:
            self.db = VehicleDatabase(db_file)
            self.all_dbs = [self.db]

        self.config_loader = AutoConfigLoader()
        self.rates = {}
        self.custom_rates = {}
        self.current_vehicles = []
        self.calculated_results = []
        self._auto_detect = False

        self.create_ui()
        self.auto_load_config()
        self.load_vehicles_from_db()

    def _on_close(self):
        """Обработка закрытия окна"""
        if messagebox.askokcancel("Выход", "Вы уверены, что хотите выйти?"):
            self.root.destroy()

    def switch_org(self):
        """Смена организации"""
        if messagebox.askyesno("Смена организации", "Сменить организацию? Текущие данные будут закрыты."):
            self.root.destroy()
            main()

    def show_tax_history(self):
        """Показать историю налога для выбранного ТС"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Выберите ТС")
            return
        vid = self.tree.item(sel[0])["values"][0]
        vehicle = self.db.get_vehicle_by_id(vid)
        if not vehicle:
            return
        
        history = self.db.get_tax_history(vid)
        
        d = tk.Toplevel(self.root)
        d.title(f"📊 История: {vehicle.get('гос_номер', '')}")
        d.geometry("500x350")
        
        text = tk.Text(d, wrap="none", font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=10, pady=10)
        
        if not history:
            text.insert("end", "История расчётов пуста")
        else:
            for h in history:
                text.insert("end", f"Год {h['год_расчёта']}: Ставка {h['ставка']} руб/л.с. → Налог: {h['сумма_налога']:,.0f} руб.\n")

    def show_year_report(self):
        """Показать отчёт по годам"""
        year = 2026
        d = tk.Toplevel(self.root)
        d.title(f"📈 Отчёт за {year} год (поквартально)")
        d.geometry("700x450")
        
        t = tk.Text(d, wrap="none", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=10, pady=10)
        
        if not self.calculated_results:
            t.insert("end", "Сначала выполните расчёт налога")
            return
        
        # Группируем по типам ТС
        by_type = {}
        for r in self.calculated_results:
            vtype = r.get("тип_тс", "другие")
            if vtype not in by_type:
                by_type[vtype] = {"count": 0, "налог": 0}
            by_type[vtype]["count"] += 1
            by_type[vtype]["налог"] += r.get("налог", 0)
        
        t.insert("end", f"📊 Отчёт по транспортному налогу за {year} год\n")
        t.insert("end", "=" * 50 + "\n\n")
        
        total_tax = 0
        total_count = 0
        for vtype, data in sorted(by_type.items()):
            t.insert("end", f"🚗 {vtype}:\n")
            t.insert("end", f"   Количество ТС: {data['count']}\n")
            t.insert("end", f"   Сумма налога: {data['налог']:,.0f} руб.\n\n")
            total_tax += data['налог']
            total_count += data['count']
        
        t.insert("end", "=" * 50 + "\n")
        t.insert("end", f"ИТОГО: {total_count} ТС, {total_tax:,.0f} руб.")

    def show_change_log(self):
        """Показать журнал изменений"""
        d = tk.Toplevel(self.root)
        d.title("📋 Журнал изменений (30 дней)")
        d.geometry("700x450")
        
        t = tk.Text(d, wrap="none", font=("Consolas", 9))
        t.pack(fill="both", expand=True, padx=10, pady=10)
        
        try:
            from datetime import timedelta
            date_30_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
            changes = self.db.get_changes_since(date_30_days_ago)
            
            if not changes:
                t.insert("end", "Изменений за последние 30 дней нет")
            else:
                for c in changes:
                    t.insert("end", f"{c['created_at']} | {c['действие']} | ТС ID {c['vehicle_id']}\n")
        except Exception as e:
            t.insert("end", f"Ошибка: {e}")

    def create_ui(self):
        # Инициализируем переменные для чекбоксов ДО их использования
        self.show_registration_var = tk.BooleanVar(value=False)
        self.show_disposal_var = tk.BooleanVar(value=False)
        self.show_notes_var = tk.BooleanVar(value=False)

        # Верхняя панель
        top = tk.Frame(self.root, bg="#f0f0f0", pady=5)
        top.pack(fill="x")

        # Первая строка - кнопки и регион
        top_row1 = tk.Frame(top, bg="#f0f0f0")
        top_row1.pack(fill="x", pady=3)

        for text, cmd, bg in [
            ("🔄 Ставки", self.update_config, "#e1f5fe"),
            ("⚙️ Редактировать ставки", self.edit_rates, "#e1f5fe"),
            ("➕ Добавить ТС", self.add_vehicle_dialog, "#e8f5e9"),
            ("📊 Рассчитать налог", self.calculate_tax, "#e8f5e9"),
            ("💾 Сохранить расчёт", self.save_calculation, "#fff3e0"),
            ("📁 Импорт Excel", self.import_excel, "#fff3e0"),
            ("📤 Экспорт в Excel", self.export_excel, "#f3e5f5"),
        ]:
            tk.Button(
                top_row1, text=text, command=cmd, bg=bg, relief="flat", padx=8, pady=3
            ).pack(side="left", padx=2)

        # Регион
        tk.Label(top_row1, text="Регион:", bg="#f0f0f0").pack(side="left", padx=(10, 2))
        self.region_var = tk.StringVar(value="Пермский край")
        self.region_cb = ttk.Combobox(
            top_row1,
            textvariable=self.region_var,
            values=[
                "Пермский край",
                "Москва",
                "Санкт-Петербург",
                "Свердловская область",
                "Краснодарский край",
            ],
            width=18,
            state="readonly",
        )
        self.region_cb.pack(side="left", padx=3)
        self.region_cb.bind("<<ComboboxSelected>>", self.on_region_change)

        self.lbl_status = tk.Label(top_row1, text="⏳ Загрузка...", fg="blue", bg="#f0f0f0", font=("Segoe UI", 8))
        self.lbl_status.pack(side="left", padx=10)

        # Чекбокс авто-определения типа
        self._auto_detect = False
        self.auto_detect_var = tk.BooleanVar(value=False)
        self.auto_detect_var.trace(
            "w", lambda *a: setattr(self, "_auto_detect", self.auto_detect_var.get())
        )
        tk.Checkbutton(
            top_row1, text="🔍 Авто-тип", variable=self.auto_detect_var, bg="#f0f0f0"
        ).pack(side="left", padx=5)

        # Вторая строка - чекбоксы для дополнительных колонок
        top_row2 = tk.Frame(top, bg="#e8e8e8")
        top_row2.pack(fill="x", pady=2, padx=5)

        tk.Label(top_row2, text=" Показать колонки:", bg="#e8e8e8", fg="#666", font=("Segoe UI", 9, "bold")).pack(side="left", padx=5)

        tk.Checkbutton(
            top_row2, text="Дата постановки", variable=self.show_registration_var,
            bg="#e8e8e8", selectcolor="#fff", command=self.filter_vehicles, font=("Segoe UI", 9)
        ).pack(side="left", padx=3)

        tk.Checkbutton(
            top_row2, text="Дата списания", variable=self.show_disposal_var,
            bg="#e8e8e8", selectcolor="#fff", command=self.filter_vehicles, font=("Segoe UI", 9)
        ).pack(side="left", padx=3)

        tk.Checkbutton(
            top_row2, text="Примечания", variable=self.show_notes_var,
            bg="#e8e8e8", selectcolor="#fff", command=self.filter_vehicles, font=("Segoe UI", 9)
        ).pack(side="left", padx=3)

        # Кнопка смены организации (справа)
        tk.Button(
            top_row2,
            text="🏢 Сменить орг.",
            command=self.switch_org,
            bg="#ede7f6",
            relief="flat",
            padx=8,
            pady=2,
            font=("Segoe UI", 9)
        ).pack(side="right", padx=5)
        flt = tk.Frame(self.root, bg="#fafafa", pady=4)
        flt.pack(fill="x", padx=10)
        tk.Label(flt, text="🔍 Поиск:", bg="#fafafa").pack(side="left", padx=5)
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *a: self.filter_vehicles())
        ttk.Entry(flt, textvariable=self.search_var, width=20).pack(side="left", padx=5)
        tk.Label(flt, text="Тип:", bg="#fafafa").pack(side="left", padx=(20, 5))
        self.type_filter = ttk.Combobox(
            flt,
            values=[
                "Все",
                "легковые",
                "грузовые",
                "автобусы",
                "мотоциклы",
                "спецтехника",
            ],
            state="readonly",
            width=12,
        )
        self.type_filter.set("Все")
        self.type_filter.bind("<<ComboboxSelected>>", lambda *a: self.filter_vehicles())
        self.type_filter.pack(side="left", padx=5)

        # Таблица
        tf = tk.Frame(self.root)
        tf.pack(fill="both", expand=True, padx=10, pady=5)
        self.tree_frame = tf  # Сохраняем ссылку на фрейм таблицы
        
        # Базовые колонки
        self.base_cols = [
            ("id", "ID", 40),
            ("инв_номер", "Инв. №", 80),
            ("гос_номер", "Гос. номер", 100),
            ("vin", "VIN", 100),
            ("марка", "Марка", 120),
            ("модель", "Модель", 120),
            ("мощность", "Л.с.", 60),
            ("год", "Год", 55),
            ("тип_тс", "Тип", 90),
            ("ставка", "Ставка", 70),
            ("1кв", "1 кв", 70),
            ("2кв", "2 кв", 70),
            ("3кв", "3 кв", 70),
            ("4кв", "4 кв", 70),
            ("итого", "Итого ₽", 90),
            ("статус", "Статус", 80),
        ]
        
        # Дополнительные колонки
        self.extra_cols = [
            ("дата_постановки", "Дата пост.", 110),
            ("дата_списания", "Дата спис.", 110),
            ("примечание", "Примечание", 150),
        ]
        
        # Создаём tree (пересоздаётся при изменении видимых колонок)
        self.tree = None
        self.vsb = None
        self.hsb = None
        self._create_tree()
        
        # Контекстное меню
        self.ctx = tk.Menu(self.root, tearoff=0)
        self.ctx.add_command(label="✏️ Редактировать", command=self.edit_vehicle)
        self.ctx.add_command(label="🗑️ Списать", command=self.dispose_vehicle)
        self.ctx.add_command(label="📊 История налога", command=self.show_tax_history)
        self.ctx.add_separator()
        self.ctx.add_command(label="❌ Удалить полностью", command=self.delete_vehicle)
        self.tree.bind("<Button-3>", lambda e: self.ctx.post(e.x_root, e.y_root))
        self.tree.bind("<Double-1>", lambda e: self.edit_vehicle())

        # Нижняя панель (создаётся один раз)
        bot = tk.Frame(self.root, bg="#f0f0f0", pady=8)
        bot.pack(fill="x")
        self.lbl_summary = tk.Label(
            bot,
            text="📊 Всего: 0 ТС | Налог: 0 ₽",
            font=("Segoe UI", 10, "bold"),
            bg="#f0f0f0",
        )
        self.lbl_summary.pack(side="left", padx=20)
        tk.Button(
            bot, text="📈 Отчёт по годам", command=self.show_year_report, bg="#e8e8e8"
        ).pack(side="right", padx=5)
        tk.Button(
            bot, text="📋 Журнал изменений", command=self.show_change_log, bg="#e8e8e8"
        ).pack(side="right", padx=5)

    def _create_tree(self):
        """Создаёт или пересоздаёт дерево с текущими колонками"""
        # Определяем видимые колонки
        cols = list(self.base_cols)
        if self.show_registration_var.get():
            cols.append(self.extra_cols[0])
        if self.show_disposal_var.get():
            cols.append(self.extra_cols[1])
        if self.show_notes_var.get():
            cols.append(self.extra_cols[2])

        # Если дерево уже существует - удаляем его
        if self.tree is not None:
            self.tree.destroy()
            if self.vsb is not None:
                self.vsb.destroy()
            if self.hsb is not None:
                self.hsb.destroy()
            self.hsb = None

        # Используем сохранённый фрейм
        tf = self.tree_frame

        # Создаём новое дерево
        self.tree = ttk.Treeview(
            tf, columns=[c[0] for c in cols], show="headings", selectmode="extended"
        )
        for cid, ctxt, cw in cols:
            self.tree.heading(cid, text=ctxt)
            self.tree.column(
                cid, width=cw, anchor="w" if cid in ("марка", "модель", "примечание") else "center",
                stretch=True
            )

        self.vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        self.hsb = None
        self.tree.configure(yscrollcommand=self.vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        tf.grid_rowconfigure(0, weight=1)
        tf.grid_columnconfigure(0, weight=1)

        # Привязываем контекстное меню к новому дереву
        self.tree.bind("<Button-3>", lambda e: self.ctx.post(e.x_root, e.y_root))
        self.tree.bind("<Double-1>", lambda e: self.edit_vehicle())

    def auto_load_config(self):
        def thread():
            region = self.region_var.get()
            success, msg = self.config_loader.load_config(
                force_update=False, region=region
            )
            self.rates = self.config_loader.rates
            if not self.config_loader.rates_by_age:
                self.config_loader._load_fallback_rates(region)
                self.rates = self.config_loader.rates

            # Загружаем пользовательские ставки
            self.custom_rates = self._load_custom_rates("custom_rates.json")

            text = f"✅ {msg} | {self.config_loader.source_name}"
            self.root.after(
                0,
                lambda: self.lbl_status.config(
                    text=text, fg="green" if success else "orange"
                ),
            )

        threading.Thread(target=thread, daemon=True).start()

    def on_region_change(self, event=None):
        region = self.region_var.get()
        self.lbl_status.config(text=f"⏳ Загрузка ставок: {region}...", fg="blue")

        def thread():
            success, msg = self.config_loader.load_config(
                force_update=True, region=region
            )
            self.rates = self.config_loader.rates
            if not self.config_loader.rates_by_age:
                self.config_loader._load_fallback_rates(region)
                self.rates = self.config_loader.rates

            # Загружаем пользовательские ставки
            self.custom_rates = self._load_custom_rates("custom_rates.json")

            text = (
                f"✅ {msg}"
                if success
                else f"⚠️ Используются встроенные ставки ({region})"
            )
            self.root.after(
                0,
                lambda: [
                    self.lbl_status.config(
                        text=text, fg="green" if success else "orange"
                    ),
                    self.show_vehicles_table(self.current_vehicles),
                ],
            )

        threading.Thread(target=thread, daemon=True).start()

    def update_config(self):
        region = self.region_var.get()
        self.lbl_status.config(text=f"🔄 Обновление: {region}...", fg="blue")

        def thread():
            success, msg = self.config_loader.load_config(
                force_update=True, region=region
            )
            self.rates = self.config_loader.rates
            if not self.config_loader.rates_by_age:
                self.config_loader._load_fallback_rates(region)
                self.rates = self.config_loader.rates

            # Загружаем пользовательские ставки
            self.custom_rates = self._load_custom_rates("custom_rates.json")

            text = f"✅ {msg}" if success else f"⚠️ {msg}"
            self.root.after(
                0,
                lambda: [
                    self.lbl_status.config(
                        text=text, fg="green" if success else "orange"
                    ),
                    messagebox.showinfo("Ставки", text),
                    self.show_vehicles_table(self.current_vehicles),
                ],
            )

        threading.Thread(target=thread, daemon=True).start()

    def edit_rates(self):
        """Диалог для ручного редактирования ставок налога"""
        dialog = tk.Toplevel(self.root)
        dialog.title("⚙️ Редактирование ставок налога")
        dialog.geometry("800x600")
        dialog.transient(self.root)
        dialog.grab_set()

        # Создаем notebook для разных вкладок
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill="both", expand=True, padx=10, pady=10)

        # Загружаем текущие ставки
        custom_rates_file = "custom_rates.json"
        custom_rates = self._load_custom_rates(custom_rates_file)

        # Функция для создания вкладки с типом ТС
        def create_vehicle_type_tab(vehicle_type, display_name):
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=display_name)

            # Создаем таблицу ставок
            tree = ttk.Treeview(
                frame, columns=("диапазон", "ставка"), show="headings", height=15
            )
            tree.heading("диапазон", text="Диапазон мощности (л.с.)")
            tree.heading("ставка", text="Ставка (руб/л.с.)")
            tree.column("диапазон", width=200)
            tree.column("ставка", width=150)

            # Получаем ставки для этого типа ТС
            rates = custom_rates.get(vehicle_type, self.rates.get(vehicle_type, {}))

            # Заполняем таблицу
            for (low, high), rate in sorted(rates.items()):
                range_text = (
                    f"{low} - {high}" if high != float("inf") else f"свыше {low}"
                )
                tree.insert("", "end", values=(range_text, rate))

            tree.pack(fill="both", expand=True, padx=5, pady=5)

            # Кнопки управления
            btn_frame = ttk.Frame(frame)
            btn_frame.pack(fill="x", pady=5)

            def add_rate():
                # Диалог для добавления новой ставки
                add_dialog = tk.Toplevel(dialog)
                add_dialog.title("Добавить ставку")
                add_dialog.geometry("300x150")
                add_dialog.transient(dialog)
                add_dialog.grab_set()

                ttk.Label(add_dialog, text="Мин. мощность:").grid(
                    row=0, column=0, padx=5, pady=5
                )
                min_power = ttk.Entry(add_dialog, width=10)
                min_power.grid(row=0, column=1, padx=5, pady=5)

                ttk.Label(add_dialog, text="Макс. мощность (0 = свыше):").grid(
                    row=1, column=0, padx=5, pady=5
                )
                max_power = ttk.Entry(add_dialog, width=10)
                max_power.grid(row=1, column=1, padx=5, pady=5)

                ttk.Label(add_dialog, text="Ставка (руб/л.с.):").grid(
                    row=2, column=0, padx=5, pady=5
                )
                rate_entry = ttk.Entry(add_dialog, width=10)
                rate_entry.grid(row=2, column=1, padx=5, pady=5)

                def save_new_rate():
                    try:
                        min_p = int(min_power.get())
                        max_p = int(max_power.get())
                        rate = float(rate_entry.get())

                        if max_p == 0:
                            max_p = float("inf")

                        if vehicle_type not in custom_rates:
                            custom_rates[vehicle_type] = {}

                        custom_rates[vehicle_type][(min_p, max_p)] = rate

                        # Обновляем таблицу
                        range_text = (
                            f"{min_p} - {max_p}"
                            if max_p != float("inf")
                            else f"свыше {min_p}"
                        )
                        tree.insert("", "end", values=(range_text, rate))

                        add_dialog.destroy()
                    except ValueError:
                        messagebox.showerror("Ошибка", "Введите корректные числа")

                ttk.Button(add_dialog, text="Сохранить", command=save_new_rate).grid(
                    row=3, column=0, columnspan=2, pady=10
                )

            def edit_rate():
                selected = tree.selection()
                if not selected:
                    messagebox.showwarning(
                        "Внимание", "Выберите ставку для редактирования"
                    )
                    return

                item = tree.item(selected[0])
                range_text, current_rate = item["values"]

                # Парсим диапазон
                if "свыше" in range_text:
                    min_p = int(range_text.split("свыше")[1].strip())
                    max_p = float("inf")
                else:
                    parts = range_text.split("-")
                    min_p = int(parts[0].strip())
                    max_p = int(parts[1].strip())

                edit_dialog = tk.Toplevel(dialog)
                edit_dialog.title("Редактировать ставку")
                edit_dialog.geometry("250x100")
                edit_dialog.transient(dialog)
                edit_dialog.grab_set()

                ttk.Label(edit_dialog, text="Ставка (руб/л.с.):").grid(
                    row=0, column=0, padx=5, pady=5
                )
                rate_entry = ttk.Entry(edit_dialog, width=10)
                rate_entry.insert(0, str(current_rate))
                rate_entry.grid(row=0, column=1, padx=5, pady=5)

                def save_edited_rate():
                    try:
                        new_rate = float(rate_entry.get())
                        custom_rates[vehicle_type][(min_p, max_p)] = new_rate

                        # Обновляем таблицу
                        tree.item(selected[0], values=(range_text, new_rate))
                        edit_dialog.destroy()
                    except ValueError:
                        messagebox.showerror("Ошибка", "Введите корректное число")

                ttk.Button(
                    edit_dialog, text="Сохранить", command=save_edited_rate
                ).grid(row=1, column=0, columnspan=2, pady=10)

            def delete_rate():
                selected = tree.selection()
                if not selected:
                    messagebox.showwarning("Внимание", "Выберите ставку для удаления")
                    return

                if messagebox.askyesno("Подтверждение", "Удалить выбранную ставку?"):
                    item = tree.item(selected[0])
                    range_text = item["values"][0]

                    # Парсим диапазон для удаления
                    if "свыше" in range_text:
                        min_p = int(range_text.split("свыше")[1].strip())
                        max_p = float("inf")
                    else:
                        parts = range_text.split("-")
                        min_p = int(parts[0].strip())
                        max_p = int(parts[1].strip())

                    if (
                        vehicle_type in custom_rates
                        and (min_p, max_p) in custom_rates[vehicle_type]
                    ):
                        del custom_rates[vehicle_type][(min_p, max_p)]
                        tree.delete(selected[0])

            ttk.Button(btn_frame, text="➕ Добавить", command=add_rate).pack(
                side="left", padx=5
            )
            ttk.Button(btn_frame, text="✏️ Редактировать", command=edit_rate).pack(
                side="left", padx=5
            )
            ttk.Button(btn_frame, text="🗑️ Удалить", command=delete_rate).pack(
                side="left", padx=5
            )

        # Создаем вкладки для каждого типа ТС
        vehicle_types = [
            ("легковые", "Легковые автомобили"),
            ("грузовые", "Грузовые автомобили"),
            ("автобусы", "Автобусы"),
            ("мотоциклы", "Мотоциклы"),
            ("спецтехника", "Спецтехника"),
        ]

        for vtype, display_name in vehicle_types:
            create_vehicle_type_tab(vtype, display_name)

        # Кнопки внизу диалога
        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", pady=10)

        def save_changes():
            # Сохраняем пользовательские ставки
            self._save_custom_rates(custom_rates_file, custom_rates)
            # Применяем изменения
            self.custom_rates = custom_rates
            # Обновляем отображение
            self.show_vehicles_table(self.current_vehicles)
            messagebox.showinfo("Успех", "Ставки сохранены и применены")
            dialog.destroy()

        def reset_to_default():
            if messagebox.askyesno(
                "Подтверждение", "Сбросить все ставки к значениям по умолчанию?"
            ):
                if os.path.exists(custom_rates_file):
                    os.remove(custom_rates_file)
                self.custom_rates = {}
                dialog.destroy()
                self.show_vehicles_table(self.current_vehicles)

        ttk.Button(btn_frame, text="💾 Сохранить изменения", command=save_changes).pack(
            side="left", padx=10
        )
        ttk.Button(
            btn_frame, text="🔄 Сбросить к умолчанию", command=reset_to_default
        ).pack(side="left", padx=10)
        ttk.Button(btn_frame, text="❌ Отмена", command=dialog.destroy).pack(
            side="right", padx=10
        )

    def _load_custom_rates(self, filename):
        """Загружает пользовательские ставки из файла"""
        if os.path.exists(filename):
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Преобразуем ключи обратно в кортежи
                    result = {}
                    for vtype, rates in data.items():
                        result[vtype] = {}
                        for key, rate in rates.items():
                            # key может быть строкой "(0, inf)" - преобразуем в кортеж
                            if isinstance(key, str):
                                # Парсим строку вручную, чтобы обработать inf
                                key = key.strip("()")
                                parts = key.split(",")
                                min_val = int(parts[0].strip())
                                max_str = parts[1].strip()
                                if max_str == "inf":
                                    max_val = float("inf")
                                else:
                                    max_val = int(max_str)
                                key_tuple = (min_val, max_val)
                            else:
                                key_tuple = key
                            result[vtype][key_tuple] = rate
                    return result
            except Exception as e:
                print(f"Error loading custom rates: {e}")
        return {}

    def _save_custom_rates(self, filename, rates):
        """Сохраняет пользовательские ставки в файл"""
        # Преобразуем ключи кортежей в строки для JSON
        serializable = {}
        for vtype, vtype_rates in rates.items():
            serializable[vtype] = {}
            for key_tuple, rate in vtype_rates.items():
                # Преобразуем float('inf') в строку 'inf' для JSON
                min_val, max_val = key_tuple
                if max_val == float("inf"):
                    key_str = f"({min_val}, inf)"
                else:
                    key_str = str(key_tuple)
                serializable[vtype][key_str] = rate

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2)

    def load_vehicles_from_db(self):
        if self.is_summary:
            self.current_vehicles = []
            for db in self.all_dbs:
                vehicles = db.get_all_vehicles(status="active")
                # Добавляем имя БД для отображения
                for v in vehicles:
                    v["_db"] = db
                self.current_vehicles.extend(vehicles)
        else:
            self.current_vehicles = self.db.get_all_vehicles(status="active")
        self.show_vehicles_table(self.current_vehicles)

    def get_ownership_months(self, vehicle, tax_year=2026):
        """Считает количество полных месяцев владения в налоговом году"""
        try:
            start_str = vehicle.get("дата_постановки", "")
            end_str = vehicle.get("дата_списания", "")

            year_start = datetime(tax_year, 1, 1)
            year_end = datetime(tax_year, 12, 31)

            # Дата начала владения
            if start_str and str(start_str) not in ("", "None", "nan"):
                start = datetime.strptime(str(start_str)[:10], "%Y-%m-%d")
            else:
                start = year_start

            # Дата конца владения
            if end_str and str(end_str) not in ("", "None", "nan"):
                end = datetime.strptime(str(end_str)[:10], "%Y-%m-%d")
            else:
                end = year_end

            # Обрезаем по границам года
            start = max(start, year_start)
            end = min(end, year_end)

            if end < start:
                return 0

            # Считаем полные месяцы (правило НК РФ: месяц постановки/снятия считается полным)
            months = (end.year - start.year) * 12 + end.month - start.month + 1
            return min(months, 12)
        except Exception:
            return 12  # Если дат нет — полный год

    def get_quarter_months(self, vehicle, tax_year=2026):
        """Возвращает dict с количеством месяцев владения по кварталам: {1: N, 2: N, 3: N, 4: N}"""
        try:
            start_str = vehicle.get("дата_постановки", "")
            end_str = vehicle.get("дата_списания", "")

            year_start = datetime(tax_year, 1, 1)
            year_end = datetime(tax_year, 12, 31)

            if start_str and str(start_str) not in ("", "None", "nan"):
                start = datetime.strptime(str(start_str)[:10], "%Y-%m-%d")
            else:
                start = year_start

            if end_str and str(end_str) not in ("", "None", "nan"):
                end = datetime.strptime(str(end_str)[:10], "%Y-%m-%d")
            else:
                end = year_end

            start = max(start, year_start)
            end = min(end, year_end)

            if end < start:
                return {1: 0, 2: 0, 3: 0, 4: 0}

            # Определяем месяцы владения
            start_month = start.month
            end_month = end.month

            # Кварталы: 1кв=(1,2,3), 2кв=(4,5,6), 3кв=(7,8,9), 4кв=(10,11,12)
            quarter_months = {1: 0, 2: 0, 3: 0, 4: 0}
            for m in range(start_month, end_month + 1):
                q = (m - 1) // 3 + 1
                quarter_months[q] += 1

            return quarter_months
        except Exception:
            return {1: 3, 2: 3, 3: 3, 4: 3}

    def get_rate_for_vehicle(self, vehicle):
        hp = vehicle.get("мощность", 0)
        if not hp:
            return 0
        hp = float(hp)
        vtype = vehicle.get("тип_тс", "легковые")
        year = vehicle.get("год_выпуска", 0)

        # Сначала проверяем пользовательские ставки
        custom_table = self.custom_rates.get(vtype, {})
        if custom_table:
            for (low, high), rate in custom_table.items():
                if (low == 0 and hp <= high) or (low < hp <= high):
                    return rate

        # Проверяем ставки по возрасту (для легковых)
        rate_table = None
        if vtype == "легковые" and year:
            try:
                age = 2026 - int(year)
                rates_by_age = getattr(self.config_loader, "rates_by_age", {})
                if rates_by_age:
                    for (af, at), tbl in rates_by_age.items():
                        if af == 0:
                            if age <= at:
                                rate_table = tbl
                                break
                        elif af < age <= at:
                            rate_table = tbl
                            break
            except:
                pass

        # Если не нашли по возрасту — берём обычную таблицу
        if rate_table is None:
            rate_table = self.rates.get(vtype, {})

        # Ищем ставку в таблице
        for (low, high), rate in rate_table.items():
            if (low == 0 and hp <= high) or (low < hp <= high):
                return rate

        # Fallback: берём первую ставку из таблицы
        if rate_table:
            return next(iter(rate_table.values()))

        return 0

    def show_vehicles_table(self, vehicles):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.calculated_results = []
        year = 2026
        for v in vehicles:
            rate = self.get_rate_for_vehicle(v)
            quarter_months = self.get_quarter_months(v, year)
            total_months = sum(quarter_months.values())

            # Нормализуем дату списания из БД (может быть datetime-объектом)
            disposal_date = v.get("дата_списания", "")
            if isinstance(disposal_date, datetime):
                disposal_date = disposal_date.strftime("%Y-%m-%d")
            elif disposal_date:
                disposal_date = str(disposal_date).strip()
            status = v.get("статус", "active")

            is_disposed = status == "disposed" or bool(disposal_date)

            # Расчёт налога: сначала точная итоговая сумма, потом распределение по кварталам
            total_months = sum(quarter_months.values())
            total_tax = round(v["мощность"] * rate * total_months / 12)

            power = v["мощность"]
            raw = {q: power * rate * m / 12 for q, m in quarter_months.items()}
            floored = {q: int(raw[q]) for q in raw}
            remainders = sorted(raw.keys(), key=lambda q: -(raw[q] - floored[q]))
            diff = total_tax - sum(floored.values())
            quarter_taxes = dict(floored)
            for i in range(diff):
                quarter_taxes[remainders[i]] += 1

            # Если ТС списано — обнуляем кварталы после списания
            if is_disposed and disposal_date:
                try:
                    disp = datetime.strptime(str(disposal_date)[:10], "%Y-%m-%d")
                    disp_quarter = (disp.month - 1) // 3 + 1
                    for q in range(disp_quarter + 1, 5):
                        quarter_taxes[q] = 0
                except:
                    pass

            # Пересчитываем итого после обнуления кварталов
            total_tax = sum(quarter_taxes.values())

            # Сохраняем расчёт в БД
            self.db.save_tax_calculation(v["id"], year, rate, total_tax)

            # Форматирование с пробелом вместо запятой
            def fmt(val):
                if val == 0 and is_disposed:
                    return "—"
                return f"{val:,}".replace(",", " ")

            # Форматируем даты для отображения
            reg_date = v.get("дата_постановки", "")
            if reg_date:
                reg_date = _db_date_to_ru(reg_date)
            else:
                reg_date = ""
                
            disp_date = v.get("дата_списания", "")
            if disp_date:
                disp_date = _db_date_to_ru(disp_date)
            else:
                disp_date = ""

            # Базовые значения
            values = [
                v["id"],
                v.get("инв_номер", ""),
                v.get("гос_номер", ""),
                v.get("vin", ""),
                v.get("марка", ""),
                v.get("модель", ""),
                v["мощность"],
                v.get("год_выпуска", ""),
                v.get("тип_тс", ""),
                rate,
                fmt(quarter_taxes[1]),
                fmt(quarter_taxes[2]),
                fmt(quarter_taxes[3]),
                fmt(quarter_taxes[4]),
                fmt(total_tax),
                "списан" if is_disposed else "актив",
            ]
            
            # Добавляем дополнительные колонки если они включены
            if self.show_registration_var.get():
                values.append(reg_date)
            if self.show_disposal_var.get():
                values.append(disp_date)
            if self.show_notes_var.get():
                values.append(v.get("примечание", ""))

            self.tree.insert(
                "",
                "end",
                values=values,
            )
            self.calculated_results.append(
                {
                    "vehicle_id": v["id"],
                    "инв_номер": v.get("инв_номер", ""),
                    "гос_номер": v.get("гос_номер", ""),
                    "марка": v.get("марка", ""),
                    "модель": v.get("модель", ""),
                    "мощность": v["мощность"],
                    "год_выпуска": v.get("год_выпуска", ""),
                    "тип_тс": v.get("тип_тс", ""),
                    "ставка": rate,
                    "месяцев_1кв": quarter_months[1],
                    "месяцев_2кв": quarter_months[2],
                    "месяцев_3кв": quarter_months[3],
                    "месяцев_4кв": quarter_months[4],
                    "налог_1кв": quarter_taxes[1],
                    "налог_2кв": quarter_taxes[2],
                    "налог_3кв": quarter_taxes[3],
                    "налог_4кв": quarter_taxes[4],
                    "налог": total_tax,
                    "год": year,
                    "статус": "списан" if is_disposed else "актив",
                }
            )
        self.update_summary()

    def filter_vehicles(self):
        # Пересоздаём дерево с текущими настройками колонок
        self._create_tree()
        
        s = self.search_var.get().lower()
        vt = self.type_filter.get()
        filtered = [
            v
            for v in self.current_vehicles
            if (
                not s
                or s in str(v.get("гос_номер", "")).lower()
                or s in str(v.get("марка", "")).lower()
                or s in str(v.get("модель", "")).lower()
            )
            and (vt == "Все" or v.get("тип_тс") == vt)
        ]
        self.show_vehicles_table(filtered)

    def update_summary(self):
        total = len(self.current_vehicles)
        total_tax = 0
        for v in self.current_vehicles:
            rate = self.get_rate_for_vehicle(v)
            quarter_months = self.get_quarter_months(v)

            # Нормализуем дату списания
            disposal_date = v.get("дата_списания", "")
            if isinstance(disposal_date, datetime):
                disposal_date = disposal_date.strftime("%Y-%m-%d")
            elif disposal_date:
                disposal_date = str(disposal_date).strip()
            is_disposed = v.get("статус") == "disposed" or bool(disposal_date)

            quarter_taxes = {}
            for q, m_count in quarter_months.items():
                quarter_taxes[q] = round(v["мощность"] * rate * m_count / 12)

            if is_disposed and disposal_date:
                try:
                    disp = datetime.strptime(str(disposal_date)[:10], "%Y-%m-%d")
                    disp_quarter = (disp.month - 1) // 3 + 1
                    for q in range(disp_quarter + 1, 5):
                        quarter_taxes[q] = 0
                except:
                    pass

            total_tax += sum(quarter_taxes.values())
        self.lbl_summary.config(
            text=f"📊 Всего: {total} ТС | Налог: {total_tax:,.0f} ₽"
        )

    def _vehicle_dialog(self, title, initial=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("1200x900")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        fields = [
            ("гос_номер", "Гос. номер"),
            ("марка", "Марка"),
            ("модель", "Модель"),
            ("мощность", "Мощность (л.с.) *"),
            ("год_выпуска", "Год выпуска *"),
            ("тип_тс", "Тип ТС"),
            ("инв_номер", "Инвентарный номер"),
            ("дата_постановки", "Дата постановки (ДД.ММ.ГГГГ)"),
            ("дата_списания", "Дата списания (ДД.ММ.ГГГГ)"),
            ("vin", "VIN"),
            ("примечание", "Примечание"),
        ]
        entries = {}
        for i, (key, label) in enumerate(fields):
            tk.Label(dialog, text=label, font=("Segoe UI", 10)).grid(
                row=i, column=0, sticky="e", padx=10, pady=8
            )
            if key == "тип_тс":
                entries[key] = ttk.Combobox(
                    dialog,
                    values=[
                        "легковые",
                        "грузовые",
                        "автобусы",
                        "мотоциклы",
                        "спецтехника",
                    ],
                    width=55,
                    state="readonly",
                )
                entries[key].set(
                    initial.get(key, "легковые") if initial else "легковые"
                )
            else:
                entries[key] = ttk.Entry(dialog, width=55)
                default = initial.get(key, "") if initial else ""
                # Даты из БД конвертируем в ДД.ММ.ГГГГ
                if key in ("дата_постановки", "дата_списания") and default:
                    default = _db_date_to_ru(default)
                entries[key].insert(0, str(default) if default else "")
            entries[key].grid(row=i, column=1, padx=10, pady=8)
        return dialog, entries, len(fields)

    def add_vehicle_dialog(self):
        dialog, entries, nf = self._vehicle_dialog("➕ Добавить ТС")

        def save():
            try:
                data = {
                    k: (
                        float(v.get())
                        if k == "мощность"
                        else (int(v.get()) if k == "год_выпуска" else v.get())
                    )
                    for k, v in entries.items()
                }
                # Парсим даты в русском формате
                data["дата_постановки"] = _parse_ru_date(data.get("дата_постановки", ""))
                data["дата_списания"] = _parse_ru_date(data.get("дата_списания", ""))
                if not data["мощность"] or not data["год_выпуска"]:
                    raise ValueError(
                        "Заполните обязательные поля: Мощность и Год выпуска"
                    )
                # Если гос. номер не указан — генерируем временный
                if not data["гос_номер"]:
                    import time

                    data["гос_номер"] = f"БН-{int(time.time())}"
                self.db.add_vehicle(data)
                self.load_vehicles_from_db()
                dialog.destroy()
                messagebox.showinfo("Успех", "ТС добавлено")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tk.Button(dialog, text="💾 Сохранить", command=save, bg="#e8f5e9", font=("Segoe UI", 11), padx=20, pady=8).grid(
            row=nf, column=0, columnspan=2, pady=25
        )

    def edit_vehicle(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("Внимание", "Выберите ТС")
            return
        vid = self.tree.item(sel[0])["values"][0]
        vehicle = self.db.get_vehicle_by_id(vid)
        if not vehicle:
            return
        dialog, entries, nf = self._vehicle_dialog("✏️ Редактировать ТС", vehicle)

        def save():
            try:
                data = {
                    k: (
                        float(v.get())
                        if k == "мощность"
                        else (int(v.get()) if k == "год_выпуска" else v.get())
                    )
                    for k, v in entries.items()
                }
                data["дата_постановки"] = _parse_ru_date(data.get("дата_постановки", ""))
                data["дата_списания"] = _parse_ru_date(data.get("дата_списания", ""))
                self.db.update_vehicle(vid, data)
                self.load_vehicles_from_db()
                dialog.destroy()
                messagebox.showinfo("Успех", "Данные обновлены")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tk.Button(dialog, text="💾 Сохранить", command=save, bg="#e8f5e9", font=("Segoe UI", 11), padx=20, pady=8).grid(
            row=nf, column=0, columnspan=2, pady=25
        )

    def dispose_vehicle(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Списание", "Списать выбранное ТС в архив?"):
            vid = self.tree.item(sel[0])["values"][0]
            self.db.delete_vehicle(vid, soft_delete=True)
            self.load_vehicles_from_db()

    def delete_vehicle(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Удаление", "⚠️ Удалить ТС БЕЗВОЗВРАТНО?"):
            vid = self.tree.item(sel[0])["values"][0]
            self.db.delete_vehicle(vid, soft_delete=False)
            self.load_vehicles_from_db()

    def calculate_tax(self):
        if not self.current_vehicles:
            messagebox.showwarning("Внимание", "База пуста. Добавьте ТС")
            return
        self.calculated_results = []
        year = 2026
        for v in self.current_vehicles:
            rate = self.get_rate_for_vehicle(v)
            quarter_months = self.get_quarter_months(v, year)

            # Нормализуем дату списания
            disposal_date = v.get("дата_списания", "")
            if isinstance(disposal_date, datetime):
                disposal_date = disposal_date.strftime("%Y-%m-%d")
            elif disposal_date:
                disposal_date = str(disposal_date).strip()
            status = v.get("статус", "active")
            is_disposed = status == "disposed" or bool(disposal_date)

            # Расчёт налога: сначала точная итоговая сумма, потом распределение по кварталам
            total_months = sum(quarter_months.values())
            total_tax = round(v["мощность"] * rate * total_months / 12)

            power = v["мощность"]
            raw = {q: power * rate * m / 12 for q, m in quarter_months.items()}
            floored = {q: int(raw[q]) for q in raw}
            remainders = sorted(raw.keys(), key=lambda q: -(raw[q] - floored[q]))
            diff = total_tax - sum(floored.values())
            quarter_taxes = dict(floored)
            for i in range(diff):
                quarter_taxes[remainders[i]] += 1

            # Обнуляем кварталы после списания
            if is_disposed and disposal_date:
                try:
                    disp = datetime.strptime(str(disposal_date)[:10], "%Y-%m-%d")
                    disp_quarter = (disp.month - 1) // 3 + 1
                    for q in range(disp_quarter + 1, 5):
                        quarter_taxes[q] = 0
                except:
                    pass

            total_tax = sum(quarter_taxes.values())
            self.db.save_tax_calculation(v["id"], year, rate, total_tax)
            self.calculated_results.append(
                {
                    "vehicle_id": v["id"],
                    "инв_номер": v.get("инв_номер", ""),
                    "гос_номер": v.get("гос_номер", ""),
                    "марка": v.get("марка", ""),
                    "модель": v.get("модель", ""),
                    "мощность": v["мощность"],
                    "год_выпуска": v.get("год_выпуска", ""),
                    "тип_тс": v.get("тип_тс", ""),
                    "ставка": rate,
                    "месяцев_1кв": quarter_months[1],
                    "месяцев_2кв": quarter_months[2],
                    "месяцев_3кв": quarter_months[3],
                    "месяцев_4кв": quarter_months[4],
                    "налог_1кв": quarter_taxes[1],
                    "налог_2кв": quarter_taxes[2],
                    "налог_3кв": quarter_taxes[3],
                    "налог_4кв": quarter_taxes[4],
                    "налог": total_tax,
                    "год": year,
                    "статус": "списан" if is_disposed else "актив",
                }
            )
        self.show_vehicles_table(self.current_vehicles)
        total = sum(r["налог"] for r in self.calculated_results)
        messagebox.showinfo(
            "Расчёт завершён",
            f"✅ Рассчитано: {len(self.calculated_results)} ТС\n💰 Итого: {total:,.0f} ₽",
        )

    def save_calculation(self):
        if not self.calculated_results:
            messagebox.showwarning("Внимание", "Сначала выполните расчёт")
            return
        fp = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"Расчёт_ТН_{datetime.now().strftime('%Y%m%d')}.xlsx",
        )
        if fp:
            pd.DataFrame(self.calculated_results).to_excel(fp, index=False)
            messagebox.showinfo("Успех", f"Сохранено: {fp}")

    def import_excel(self):
        fp = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx *.xls")])
        if not fp:
            return
        try:
            # Читаем все колонки как строки, чтобы сохранить точность длинных номеров
            df = pd.read_excel(fp, dtype=str, keep_default_na=False)
            # Показываем диалог сопоставления колонок
            mapping = self._column_mapping_dialog(list(df.columns))
            if mapping is None:
                return  # Пользователь отменил
            added, skipped, errors = self.db.import_from_excel(df, mapping)
            self.load_vehicles_from_db()
            msg = f"✅ Добавлено: {added}\n⏭️ Пропущено: {skipped}"
            if errors:
                msg += f"\n❌ Ошибок: {len(errors)}\n\nПервые 5:\n" + "\n".join(
                    errors[:5]
                )
            messagebox.showinfo("Импорт", msg)
        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def export_excel(self):
        """Экспорт данных в Excel"""
        fp = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"Автопарк_{datetime.now().strftime('%Y%m%d')}.xlsx",
            filetypes=[("Excel", "*.xlsx")],
        )
        if fp:
            try:
                self.db.export_to_excel(fp)
                messagebox.showinfo("Успех", f"Экспорт завершён:\n{fp}")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

    def _column_mapping_dialog(self, file_cols):
        """Диалог сопоставления колонок файла с полями базы"""
        dialog = tk.Toplevel(self.root)
        dialog.title("📋 Сопоставление колонок")
        dialog.geometry("500x480")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        tk.Label(
            dialog,
            text="Укажите какая колонка файла соответствует каждому полю.\n«— не импортировать —» если колонки нет.",
            justify="left",
            fg="gray",
        ).pack(padx=15, pady=(10, 5), anchor="w")

        # Поля базы: (ключ, отображаемое имя, обязательное)
        db_fields = [
            ("мощность", "Мощность (л.с.) *", True),
            ("год_выпуска", "Год выпуска *", True),
            ("марка", "Марка", False),
            ("модель", "Модель", False),
            ("гос_номер", "Гос. номер", False),
            ("инв_номер", "Инвентарный номер", False),
            ("тип_тс", "Тип ТС", False),
            ("vin", "VIN", False),
            ("дата_постановки", "Дата постановки", False),
            ("дата_списания", "Дата списания", False),
            ("примечание", "Примечание", False),
        ]

        choices = ["— не импортировать —"] + [str(c) for c in file_cols]

        frame = tk.Frame(dialog)
        frame.pack(fill="both", expand=True, padx=15, pady=5)

        combos = {}
        for i, (key, label, required) in enumerate(db_fields):
            color = "#c00000" if required else "black"
            tk.Label(frame, text=label, fg=color, width=22, anchor="e").grid(
                row=i, column=0, pady=3, padx=5
            )
            cb = ttk.Combobox(frame, values=choices, state="readonly", width=28)
            # Авто-угадываем по похожести
            best = self._guess_column(key, file_cols)
            cb.set(best if best else choices[0])
            cb.grid(row=i, column=1, pady=3)
            combos[key] = cb

        result = {"mapping": None}

        def confirm():
            # Проверяем обязательные
            for key, label, required in db_fields:
                if required and combos[key].get() == choices[0]:
                    messagebox.showwarning(
                        "Внимание", f"Укажите колонку для поля: {label}", parent=dialog
                    )
                    return
            result["mapping"] = {
                k: (cb.get() if cb.get() != choices[0] else None)
                for k, cb in combos.items()
            }
            dialog.destroy()

        def cancel():
            dialog.destroy()

        btn_f = tk.Frame(dialog)
        btn_f.pack(pady=10)
        tk.Button(
            btn_f, text="✅ Импортировать", command=confirm, bg="#e8f5e9", width=18
        ).pack(side="left", padx=5)
        tk.Button(btn_f, text="❌ Отмена", command=cancel, width=10).pack(
            side="left", padx=5
        )

        dialog.wait_window()
        return result["mapping"]

    def _guess_column(self, field_key, file_cols):
        """Угадывает колонку по названию поля"""
        field_key = field_key.lower()
        # Частые варианты названий колонок
        synonyms = {
            "мощность": ["мощн", "л.с.", "лс", "hp", "power", "сила"],
            "год_выпуска": ["год", "выпуск", "year", "г/в"],
            "марка": ["марка", "make", "brand", "производитель"],
            "модель": ["модель", "model"],
            "гос_номер": ["гос", "номер", "reg", "регистр", "state"],
            "инв_номер": ["инв", "инвентар", "inventory"],
            "тип_тс": ["тип", "тс", "type", "vehicle"],
            "vin": ["vin", "иин", "frame"],
            "дата_постановки": ["постановк", "регистр", "date_in"],
            "дата_списания": ["списан", "выбыт", "date_out"],
            "примечание": ["примеч", "заметк", "note", "comment"],
        }
        for col in file_cols:
            col_lower = str(col).lower().strip()
            # Прямое совпадение
            if field_key in col_lower or col_lower in field_key:
                return col
            # По синонимам
            if field_key in synonyms:
                for syn in synonyms[field_key]:
                    if syn in col_lower:
                        return col
        return None


# ============================================================================
# ЗАПУСК ПРИЛОЖЕНИЯ
# ============================================================================

def main():
    root = tk.Tk()
    root.withdraw()  # Скрываем главное окно
    
    # Показываем диалог выбора организации
    selector = OrgSelector(root)
    
    # Если организация не выбрана - выходим
    if not selector.selected_org:
        root.destroy()
        return
    
    # Показываем главное окно
    root.deiconify()
    
    # Создаём приложение
    app = TaxApp(root, selector.selected_org, selector.selected_db)
    
    root.mainloop()


if __name__ == "__main__":
    main()
