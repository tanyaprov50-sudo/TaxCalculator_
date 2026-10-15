# -*- coding: utf-8 -*-
"""Смоук-тесты ядра tax_app.py без GUI.

Запуск: python tests/test_smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import tax_app  # noqa: E402

FAILED = []


def check(name, cond, detail=""):
    status = "OK " if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)


# --- 1. Парсинг дат ---
check("_parse_ru_date ДД.ММ.ГГГГ", tax_app._parse_ru_date("15.03.2026") == "2026-03-15")
check("_parse_ru_date ДД-ММ-ГГГГ", tax_app._parse_ru_date("15-03-2026") == "2026-03-15")
check("_parse_ru_date уже ISO", tax_app._parse_ru_date("2026-03-15") == "2026-03-15")
check("_parse_ru_date пусто", tax_app._parse_ru_date("") == "")
check("_parse_ru_date мусор не падает", tax_app._parse_ru_date("abc") == "abc")

dt = tax_app._parse_date_to_datetime("15.03.2026")
check("_parse_date_to_datetime ru", dt is not None and dt.day == 15 and dt.month == 3)
check("_parse_date_to_datetime None", tax_app._parse_date_to_datetime("") is None)

check("_db_date_to_ru", tax_app._db_date_to_ru("2026-03-15") == "15.03.2026")

# --- 2. Нормализация данных ---
n = tax_app.DataNormalizer()
check("мощность строка", n.normalize_power("150") == 150.0)
check("мощность запятая", n.normalize_power("150,5") == 150.5)
check("мощность кВт", n.normalize_power("100 кВт") == 135.96)
check("мощность некорректно", n.normalize_power("abc") is None)
check("мощность вне диапазона", n.normalize_power("5000") is None)
check("тип: грузовой", n.normalize_vehicle_type("ГРУЗОВОЙ бортовой") == "грузовые")
check("тип: неизвестный", n.normalize_vehicle_type("квадроцикл") == "легковые")
check("тип: спецтехника", n.normalize_vehicle_type("трактор МТЗ") == "спецтехника")

# --- 3. Парсер диапазонов ставок ---
ac = tax_app.AutoConfigLoader()
check("диапазон 'до 100'", ac._parse_range("до 100 включительно") == (0, 100))
check("диапазон 'свыше 300'", ac._parse_range("свыше 300") == (300, float("inf")))
check("диапазон '100-125'", ac._parse_range("100-125") == (100, 125))

# --- 4. Сериализация ставок (кортежи <-> строки, inf) ---
rates = {"легковые": {(0, 100): 25, (300, float("inf")): 135}}
ser = ac._serialize_rates(rates)
back = ac._convert_rate_keys(ser)
check(
    "сериализация ставок roundtrip",
    back == rates,
    f"получено: {back}",
)

# --- 5. БД: дедупликация, белый список UPDATE ---
db = tax_app.VehicleDatabase(":memory:")
db.add_vehicle(
    {
        "марка": "LADA", "модель": "Vesta", "гос_номер": "А123ВС",
        "мощность": 110, "год_выпуска": 2020, "тип_тс": "легковые",
        "vin": "XTA1234567890", "инв_номер": "123",
    }
)
dup = db.find_duplicate_vehicle({"инв_номер": "123", "vin": "", "гос_номер": ""})
check("дубликат по инв. номеру", dup is not None)
dup2 = db.find_duplicate_vehicle({"инв_номер": "", "vin": "XTA1234567890", "гос_номер": ""})
check("дубликат по VIN", dup2 is not None)
check("нет дубликата", db.find_duplicate_vehicle({"инв_номер": "999"}) is None)

db.update_vehicle(dup, {"мощность": 106, "несуществующая_колонка": "x"})
v = db.get_vehicle_by_id(dup)
check("белый список UPDATE", v["мощность"] == 106)

# --- 6. Импорт Excel: повторный импорт не создаёт дубли ---
import pandas as pd  # noqa: E402

rows = [
    {"инв_номер": "201", "гос_номер": "Е777КХ", "vin": "VIN201", "марка": "ГАЗель",
     "модель": "NEXT", "мощность": "120", "год_выпуска": "2021",
     "тип_тс": "грузовая", "vin2": "", "примечание": ""},
    {"инв_номер": "202", "гос_номер": "К888ММ", "vin": "VIN202", "марка": "ПАЗ",
     "модель": "3204", "мощность": "130", "год_выпуска": "2019",
     "тип_тс": "автобус", "примечание": ""},
]
df = pd.DataFrame(rows)
added1, upd1, err1 = db.import_from_excel(df.copy(), mapping=None)
check("импорт 1: добавлено 2", added1 == 2 and len(err1) == 0, f"{added1}, {err1}")
added2, upd2, err2 = db.import_from_excel(df.copy(), mapping=None)
check("импорт 2: обновлено 2, дублей нет", added2 == 0 and upd2 == 2, f"{added2}, {upd2}")
check("всего ТС 3 (LADA + 2 импортированных)", len(db.get_all_vehicles()) == 3)

# --- 7. Логика расчёта (без GUI, через __new__) ---
app = tax_app.TaxApp.__new__(tax_app.TaxApp)
app.tax_year = 2026
app.custom_rates = {}
app.config_loader = tax_app.AutoConfigLoader()
app.config_loader._load_fallback_rates("Пермский край")
app.rates = app.config_loader.rates

qm = app.get_quarter_months({"дата_постановки": "15.03.2026", "дата_списания": ""}, 2026)
# Март — это I квартал; владение с марта по декабрь = 10 месяцев
check("кварталы: постановка 15.03", qm == {1: 1, 2: 3, 3: 3, 4: 3}, str(qm))

qm2 = app.get_quarter_months({"дата_постановки": "", "дата_списания": ""}, 2026)
check("кварталы: полный год", qm2 == {1: 3, 2: 3, 3: 3, 4: 3}, str(qm2))

qm3 = app.get_quarter_months(
    {"дата_постановки": "01.02.2025", "дата_списания": "20.09.2026"}, 2026
)
check("кварталы: владение с 2025, списание в 2026", qm3 == {1: 3, 2: 3, 3: 3, 4: 0}, str(qm3))

r1 = app.get_rate_for_vehicle(
    {"мощность": 100, "тип_тс": "легковые", "год_выпуска": 2026}
)
check("ставка: новое авто до 100 л.с.", r1 == 25, str(r1))

r2 = app.get_rate_for_vehicle(
    {"мощность": 150, "тип_тс": "легковые", "год_выпуска": 2010}
)
# 150 л.с. входит в диапазон «свыше 125 до 150» (граница включена) — 32 руб
check("ставка: авто 16 лет, 150 л.с.", r2 == 32, str(r2))

r2b = app.get_rate_for_vehicle(
    {"мощность": 151, "тип_тс": "легковые", "год_выпуска": 2010}
)
check("ставка: авто 16 лет, 151 л.с.", r2b == 44, str(r2b))

r3 = app.get_rate_for_vehicle(
    {"мощность": 120, "тип_тс": "грузовые", "год_выпуска": 2010}
)
check("ставка: грузовые не по возрасту", r3 == 40, str(r3))

r4 = app.get_rate_for_vehicle(
    {"мощность": 500, "тип_тс": "легковые", "год_выпуска": 2024}
)
check("ставка: свыше 300 л.с.", r4 == 135, str(r4))

print()
if FAILED:
    print(f"ПРОВАЛЕНО тестов: {len(FAILED)}: {', '.join(FAILED)}")
    sys.exit(1)
print("Все тесты пройдены.")
