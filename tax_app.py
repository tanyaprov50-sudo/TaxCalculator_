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

# ============================================================================
# МОДУЛЬ 1: БАЗА ДАННЫХ (SQLite)
# ============================================================================


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
                (марка, модель, гос_номер, мощность, год_выпуска, тип_тс, vin, инв_номер, дата_постановки, статус, примечание)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                data = {
                    "марка": str(row.get("марка", "")),
                    "модель": str(row.get("модель", "")),
                    "гос_номер": gos,
                    "мощность": float(мощность),
                    "год_выпуска": int(год),
                    "тип_тс": str(row.get("тип_тс", "легковые")),
                    "vin": str(row.get("vin", "")),
                    "инв_номер": инв,
                    "дата_постановки": str(row.get("дата_постановки", "")),
                    "дата_списания": str(row.get("дата_списания", "")),
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
        # Всегда создаем свой собственный root для диалога
        self.root = tk.Tk()
        self.own_root = True
        self.root.withdraw()  # Скрываем корневое окно
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
        self.root.geometry("1200x750")
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

    def create_ui(self):
        # Верхняя панель
        top = tk.Frame(self.root, bg="#f0f0f0", pady=8)
        top.pack(fill="x")

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
                top, text=text, command=cmd, bg=bg, relief="flat", padx=8, pady=4
            ).pack(side="left", padx=3)

        # Регион
        tk.Label(top, text="Регион:", bg="#f0f0f0").pack(side="left", padx=(15, 2))
        self.region_var = tk.StringVar(value="Пермский край")
        self.region_cb = ttk.Combobox(
            top,
            textvariable=self.region_var,
            values=[
                "Пермский край",
                "Москва",
                "Санкт-Петербург",
                "Свердловская область",
                "Краснодарский край",
            ],
            width=20,
            state="readonly",
        )
        self.region_cb.pack(side="left", padx=5)
        self.region_cb.bind("<<ComboboxSelected>>", self.on_region_change)

        self.lbl_status = tk.Label(top, text="⏳ Загрузка...", fg="blue", bg="#f0f0f0")
        self.lbl_status.pack(side="left", padx=15)

        # Чекбокс авто-определения типа
        self._auto_detect = False
        self.auto_detect_var = tk.BooleanVar(value=False)
        self.auto_detect_var.trace(
            "w", lambda *a: setattr(self, "_auto_detect", self.auto_detect_var.get())
        )
        tk.Checkbutton(
            top, text="🔍 Авто-тип", variable=self.auto_detect_var, bg="#f0f0f0"
        ).pack(side="left", padx=5)

        # Кнопка смены организации
        tk.Button(
            top,
            text="🏢 Сменить орг.",
            command=self.switch_org,
            bg="#ede7f6",
            relief="flat",
            padx=8,
            pady=4,
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
        cols = [
            ("id", "ID", 40),
            ("инв_номер", "Инв. №", 80),
            ("гос_номер", "Гос. номер", 100),
            ("марка", "Марка", 120),
            ("модель", "Модель", 120),
            ("мощность", "Л.с.", 60),
            ("год", "Год", 55),
            ("тип_тс", "Тип", 90),
            ("ставка", "Ставка", 70),
            ("мес", "Мес.", 45),
            ("налог", "Налог ₽", 90),
            ("статус", "Статус", 80),
        ]
        self.tree = ttk.Treeview(
            tf, columns=[c[0] for c in cols], show="headings", selectmode="extended"
        )
        for cid, ctxt, cw in cols:
            self.tree.heading(cid, text=ctxt)
            self.tree.column(
                cid, width=cw, anchor="w" if cid in ("марка", "модель") else "center"
            )
        vsb = ttk.Scrollbar(tf, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(tf, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tf.grid_rowconfigure(0, weight=1)
        tf.grid_columnconfigure(0, weight=1)

        # Контекстное меню
        self.ctx = tk.Menu(self.root, tearoff=0)
        self.ctx.add_command(label="✏️ Редактировать", command=self.edit_vehicle)
        self.ctx.add_command(label="🗑️ Списать", command=self.dispose_vehicle)
        self.ctx.add_command(label="📊 История налога", command=self.show_tax_history)
        self.ctx.add_separator()
        self.ctx.add_command(label="❌ Удалить полностью", command=self.delete_vehicle)
        self.tree.bind("<Button-3>", lambda e: self.ctx.post(e.x_root, e.y_root))
        self.tree.bind("<Double-1>", lambda e: self.edit_vehicle())

        # Нижняя панель
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

    def get_rate_for_vehicle(self, vehicle):
        hp = vehicle.get("мощность", 0)
        vtype = vehicle.get("тип_тс", "легковые")
        year = vehicle.get("год_выпуска", 0)

        # Сначала проверяем пользовательские ставки
        custom_table = self.custom_rates.get(vtype, {})
        if custom_table:
            for (low, high), rate in custom_table.items():
                if low < hp <= high or (low == 0 and hp <= high):
                    return rate

        # Если пользовательских ставок нет, используем загруженные ставки
        rate_table = None
        if vtype == "легковые" and year and int(year) > 0:
            age = 2026 - int(year)
            for (af, at), tbl in self.config_loader.rates_by_age.items():
                if af < age <= at or (af == 0 and age <= at):
                    rate_table = tbl
                    break
        if rate_table is None:
            rate_table = self.rates.get(vtype, {})
        for (low, high), rate in rate_table.items():
            if low < hp <= high or (low == 0 and hp <= high):
                return rate
        return max(rate_table.values()) if rate_table and rate_table.values() else 50

    def show_vehicles_table(self, vehicles):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.calculated_results = []
        year = 2026
        for v in vehicles:
            rate = self.get_rate_for_vehicle(v)
            months = self.get_ownership_months(v)
            coeff = months / 12
            tax = v["мощность"] * rate * coeff
            # Автоматически сохраняем расчет в базу данных
            self.db.save_tax_calculation(v["id"], year, rate, tax)
            self.tree.insert(
                "",
                "end",
                values=[
                    v["id"],
                    v.get("инв_номер", ""),
                    v.get("гос_номер", ""),
                    v.get("марка", ""),
                    v.get("модель", ""),
                    v["мощность"],
                    v.get("год_выпуска", ""),
                    v.get("тип_тс", ""),
                    rate,
                    months,
                    f"{tax:,.2f}",
                    v.get("статус", "active"),
                ],
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
                    "месяцев": months,
                    "коэффициент": coeff,
                    "налог": tax,
                    "год": year,
                }
            )
        self.update_summary()

    def filter_vehicles(self):
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
        total_tax = sum(
            v["мощность"]
            * self.get_rate_for_vehicle(v)
            * self.get_ownership_months(v)
            / 12
            for v in self.current_vehicles
        )
        self.lbl_summary.config(
            text=f"📊 Всего: {total} ТС | Налог: {total_tax:,.0f} ₽"
        )

    def _vehicle_dialog(self, title, initial=None):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("480x420")
        dialog.transient(self.root)
        dialog.grab_set()
        fields = [
            ("гос_номер", "Гос. номер"),
            ("марка", "Марка"),
            ("модель", "Модель"),
            ("мощность", "Мощность (л.с.) *"),
            ("год_выпуска", "Год выпуска *"),
            ("тип_тс", "Тип ТС"),
            ("инв_номер", "Инвентарный номер"),
            ("дата_постановки", "Дата постановки (ГГГГ-ММ-ДД)"),
            ("дата_списания", "Дата списания (ГГГГ-ММ-ДД)"),
            ("vin", "VIN"),
            ("примечание", "Примечание"),
        ]
        entries = {}
        for i, (key, label) in enumerate(fields):
            tk.Label(dialog, text=label).grid(
                row=i, column=0, sticky="e", padx=10, pady=4
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
                    width=28,
                    state="readonly",
                )
                entries[key].set(
                    initial.get(key, "легковые") if initial else "легковые"
                )
            else:
                entries[key] = ttk.Entry(dialog, width=30)
                default = initial.get(key, "") if initial else ""
                entries[key].insert(0, str(default) if default else "")
            entries[key].grid(row=i, column=1, padx=10, pady=4)
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

        tk.Button(dialog, text="💾 Сохранить", command=save, bg="#e8f5e9").grid(
            row=nf, column=0, columnspan=2, pady=15
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
                self.db.update_vehicle(vid, data)
                self.load_vehicles_from_db()
                dialog.destroy()
                messagebox.showinfo("Успех", "Данные обновлены")
            except Exception as e:
                messagebox.showerror("Ошибка", str(e))

        tk.Button(dialog, text="💾 Сохранить", command=save, bg="#e8f5e9").grid(
            row=nf, column=0, columnspan=2, pady=15
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
            months = self.get_ownership_months(v, year)
            coeff = months / 12
            tax = v["мощность"] * rate * months / 12
            self.db.save_tax_calculation(v["id"], year, rate, tax)
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
                    "месяцев": months,
                    "коэффициент": coeff,
                    "налог": tax,
                    "год": year,
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
        """Пытается угадать колонку по ключевым словам"""
        hints = {
            "мощность": ["мощ", "л.с", "лс", "hp", "л/с", "сил"],
            "год_выпуска": ["год", "year", "выпуск"],
            "марка": ["марк", "brand", "наименован", "назван"],
            "модель": ["модел", "model"],
            "гос_номер": ["гос", "номер", "рег", "number", "plate"],
            "инв_номер": ["инв", "inv", "инвентар"],
            "тип_тс": ["тип", "type", "категор"],
            "vin": ["vin", "вин"],
            "дата_постановки": ["постановк", "принят", "начал", "регистр"],
            "дата_списания": ["списан", "снят", "выбыт", "конец"],
            "примечание": ["примеч", "коммент", "note"],
        }
        kws = hints.get(field_key, [])
        for col in file_cols:
            col_l = str(col).lower()
            if any(kw in col_l for kw in kws):
                return str(col)
        return None

    def export_excel(self):
        fp = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            initialfile=f"Автопарк_{datetime.now().strftime('%Y%m%d')}.xlsx",
        )
        if not fp:
            return
        # Лист 1 — вся база с последним расчётом
        self.db.export_to_excel(fp)
        # Лист 2 — текущий расчёт если есть
        if self.calculated_results:
            with pd.ExcelWriter(
                fp, engine="openpyxl", mode="a", if_sheet_exists="replace"
            ) as writer:
                pd.DataFrame(self.calculated_results).to_excel(
                    writer, index=False, sheet_name="Расчёт_налога"
                )
        messagebox.showinfo("Успех", f"Экспортировано: {fp}")

    def show_tax_history(self):
        sel = self.tree.selection()
        if not sel:
            return
        vid = self.tree.item(sel[0])["values"][0]
        vehicle = self.db.get_vehicle_by_id(vid)
        history = self.db.get_tax_history(vid)
        d = tk.Toplevel(self.root)
        d.title(f"📊 История: {vehicle.get('гос_номер', '')}")
        d.geometry("500x350")
        t = tk.Text(d, wrap="none", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=10, pady=10)
        if history:
            lines = [f"{'Год':<8} {'Ставка':<10} {'Сумма':>12}", "=" * 32]
            for h in history:
                lines.append(
                    f"{h['год_расчёта']:<8} {h['ставка']:<10} {h['сумма_налога']:>10,.0f} ₽"
                )
            t.insert("1.0", "\n".join(lines))
        else:
            t.insert("1.0", "История отсутствует")
        t.config(state="disabled")
        tk.Button(d, text="Закрыть", command=d.destroy).pack(pady=5)

    def show_year_report(self):
        year = 2026
        # Если есть текущие расчеты, используем их, иначе берем из базы
        if self.calculated_results:
            # Группируем по типу ТС
            summary = {}
            for r in self.calculated_results:
                vtype = r["тип_тс"]
                if vtype not in summary:
                    summary[vtype] = {
                        "количество": 0,
                        "общая_сумма": 0,
                        "средняя_сумма": 0,
                    }
                summary[vtype]["количество"] += 1
                summary[vtype]["общая_сумма"] += r["налог"]

            # Рассчитываем средние
            for vtype, data in summary.items():
                if data["количество"] > 0:
                    data["средняя_сумма"] = data["общая_сумма"] / data["количество"]

            summary = [{"тип_тс": k, **v} for k, v in summary.items()]
        else:
            summary = self.db.get_year_summary(year)

        d = tk.Toplevel(self.root)
        d.title(f"📈 Отчёт за {year} год")
        d.geometry("500x350")
        t = tk.Text(d, wrap="none", font=("Consolas", 10))
        t.pack(fill="both", expand=True, padx=10, pady=10)
        lines = [f"ТРАНСПОРТНЫЙ НАЛОГ {year}", "=" * 50]
        total_tax, total_count = 0, 0
        for row in summary:
            lines.append(
                f"{row['тип_тс']:<15} {row['количество']:>5} ТС  {row['общая_сумма']:>12,.0f} ₽"
            )
            total_tax += row["общая_сумма"]
            total_count += row["количество"]
        lines += ["=" * 50, f"ИТОГО: {total_count} ТС | {total_tax:,.0f} ₽"]
        t.insert("1.0", "\n".join(lines))
        t.config(state="disabled")
        tk.Button(d, text="Закрыть", command=d.destroy).pack(pady=5)

    def show_change_log(self):
        d = tk.Toplevel(self.root)
        d.title("📋 Журнал изменений (30 дней)")
        d.geometry("700x450")
        t = tk.Text(d, wrap="none", font=("Consolas", 9))
        t.pack(fill="both", expand=True, padx=10, pady=10)
        since = (datetime.now() - timedelta(days=30)).isoformat()
        changes = self.db.get_changes_since(since)
        if changes:
            for ch in changes:
                t.insert(
                    "end",
                    f"{ch['created_at'][:19]} | {ch['действие']:<10} | ТС #{ch['vehicle_id']}\n",
                )
        else:
            t.insert("1.0", "Изменений за последние 30 дней нет")
        t.config(state="disabled")
        tk.Button(d, text="Закрыть", command=d.destroy).pack(pady=5)

    def _on_close(self):
        """Обработчик закрытия главного окна"""
        self.root.destroy()
        # Завершаем программу
        import sys

        sys.exit(0)

    def switch_org(self):
        """Перезапуск с выбором другой организации"""
        if messagebox.askyesno(
            "Сменить организацию",
            "Открыть другую организацию?\nТекущее окно закроется.",
        ):
            self.root.destroy()
            main()


def main():
    selector = OrgSelector()

    if not selector.selected_org:
        return

    app_root = tk.Tk()
    # Принудительно показываем окно
    app_root.update()
    app_root.deiconify()
    
    app = TaxApp(app_root, org_name=selector.selected_org, db_file=selector.selected_db)
    app_root.mainloop()


if __name__ == "__main__":
    main()
