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

# --- подсветка статуса ---
check("_date_year ISO", tax_app._date_year("2026-09-10") == 2026)
check("_date_year RU", tax_app._date_year("15.03.2025") == 2025)
check("_date_year пусто", tax_app._date_year("") is None)
check(
    "_status_tag списано в году",
    tax_app._status_tag({"дата_списания": "2026-09-20"}, 2026) == "disp_year",
)
check(
    "_status_tag поставлено в году",
    tax_app._status_tag({"дата_постановки": "2026-03-15"}, 2026) == "reg_year",
)
check(
    "_status_tag прочие годы без подсветки",
    tax_app._status_tag(
        {"дата_постановки": "2020-01-01", "дата_списания": "2024-01-01"}, 2026
    )
    == "",
)
check(
    "_status_tag приоритет списания",
    tax_app._status_tag(
        {"дата_постановки": "2026-03-01", "дата_списания": "2026-09-01"}, 2026
    )
    == "disp_year",
)

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

# --- Сортировка по клику на заголовок ---
app._sort_col = None
app._sort_asc = True
check("сортировка: число с пробелами", app._sort_value("итого", "1 234") == (0, 1234.0, ""))
check("сортировка: прочерк в конец", app._sort_value("итого", "—") == (2, 0.0, ""))
check("сортировка: пусто в конец", app._sort_value("ставка", "") == (2, 0.0, ""))
check("сортировка: инв. номер по числу", app._sort_value("инв_номер", "45") == (0, 45.0, ""))
check(
    "сортировка: 45 < 123 как числа",
    app._sort_value("инв_номер", "45") < app._sort_value("инв_номер", "123"),
)
check(
    "сортировка: текст без регистра",
    app._sort_value("марка", "LADA") == (0, 0.0, "lada"),
)
rows = ["1200", "350", "—", "9800", ""]
keys = [app._sort_value("итого", r) for r in rows]
check(
    "сортировка: итоговый порядок",
    [rows[i] for i in sorted(range(len(rows)), key=lambda i: keys[i])]
    == ["350", "1200", "9800", "—", ""],
)

# --- 8. Экспорт данных в ZIP ---
import tempfile  # noqa: E402
import zipfile  # noqa: E402

tmp = tempfile.mkdtemp()
os.makedirs(os.path.join(tmp, "backups"))
with open(os.path.join(tmp, "organizations.json"), "w", encoding="utf-8") as f:
    f.write("{}")
with open(os.path.join(tmp, "fleet_test.db"), "wb") as f:
    f.write(b"x")
with open(os.path.join(tmp, "backups", "fleet_test_20260101.db"), "wb") as f:
    f.write(b"x")

zpath = os.path.join(tmp, "export.zip")
added = tax_app.build_data_zip(zpath, tmp)
expected = {"organizations.json", "fleet_test.db", "backups/fleet_test_20260101.db"}
check("zip: собраны все данные", set(added) == expected, str(added))
with zipfile.ZipFile(zpath) as z:
    names = set(z.namelist())
check("zip: есть manifest.txt", "manifest.txt" in names, str(names))
check("zip: бэкапы внутри", "backups/fleet_test_20260101.db" in names)

empty_dir = tempfile.mkdtemp()
check(
    "zip: пустая папка -> пусто",
    tax_app.build_data_zip(os.path.join(empty_dir, "e.zip"), empty_dir) == [],
)

# --- 9. Повышающий коэффициент и льгота (ст. 362 НК РФ) ---
base = {"тип_тс": "легковые", "год_выпуска": 2024, "стоимость_млн": 12.0}
check(
    "коэффициент: по умолчанию выключен",
    tax_app.vehicle_adjustments(base, 2026) == (1.0, 1.0),
)
check(
    "коэффициент: вкл, 12 млн, 2 года -> x3",
    tax_app.vehicle_adjustments({**base, "коэф_вкл": 1}, 2026) == (3.0, 1.0),
)
check(
    "коэффициент: возраст 16 лет > 10 -> не применяется",
    tax_app.vehicle_adjustments({**base, "коэф_вкл": 1, "год_выпуска": 2010}, 2026)
    == (1.0, 1.0),
)
check(
    "коэффициент: 16 млн, возраст 15 <= 20 -> x3",
    tax_app.vehicle_adjustments(
        {**base, "коэф_вкл": 1, "стоимость_млн": 16.0, "год_выпуска": 2011}, 2026
    )
    == (3.0, 1.0),
)
check(
    "коэффициент: только легковые",
    tax_app.vehicle_adjustments({**base, "коэф_вкл": 1, "тип_тс": "грузовые"}, 2026)
    == (1.0, 1.0),
)
check(
    "коэффициент: 9 млн < 10 -> не применяется",
    tax_app.vehicle_adjustments({**base, "коэф_вкл": 1, "стоимость_млн": 9.0}, 2026)
    == (1.0, 1.0),
)
check(
    "льгота: по умолчанию выключена",
    tax_app.vehicle_adjustments({"льгота_процент": 50}, 2026) == (1.0, 1.0),
)
check(
    "льгота 50% вкл -> множитель 0.5",
    tax_app.vehicle_adjustments({"льгота_вкл": 1, "льгота_процент": 50}, 2026)
    == (1.0, 0.5),
)
check(
    "льгота 100% -> налог 0",
    tax_app.vehicle_adjustments({"льгота_вкл": 1, "льгота_процент": 100}, 2026)
    == (1.0, 0.0),
)
combo = {
    **base, "коэф_вкл": 1, "стоимость_млн": 20.0,
    "льгота_вкл": 1, "льгота_процент": 50,
}
check("комбинация: коэффициент + льгота", tax_app.vehicle_adjustments(combo, 2026) == (3.0, 0.5))

# Формула: 100 л.с. × 50 ₽ × 12/12 = 5000; ×3 = 15000; −50% = 7500
k, kb = tax_app.vehicle_adjustments(
    {**base, "коэф_вкл": 1, "льгота_вкл": 1, "льгота_процент": 50}, 2026
)
check("формула: коэффициент + льгота", round(100 * 50 * 12 / 12 * k * kb) == 7500)
k0, kb0 = tax_app.vehicle_adjustments(base, 2026)
check("формула: выключено = как раньше", round(100 * 50 * 12 / 12 * k0 * kb0) == 5000)

check(
    "текст колонки пуст, когда выкл",
    tax_app.format_adjustments(base, 1.0, 1.0) == "",
)
check(
    "текст колонки: коэффициент и льгота",
    tax_app.format_adjustments({"льгота_процент": 50}, 3.0, 0.5) == "×3 −50%",
)

# --- 10. БД: поля коэффициента/льготы ---
db2 = tax_app.VehicleDatabase(":memory:")
vid0 = db2.add_vehicle({"мощность": 100, "год_выпуска": 2025, "тип_тс": "легковые"})
v0 = db2.get_vehicle_by_id(vid0)
check(
    "новые поля выключены по умолчанию",
    v0["коэф_вкл"] == 0 and v0["льгота_вкл"] == 0 and v0["стоимость_млн"] == 0,
    str(v0),
)
vid = db2.add_vehicle(
    {
        "мощность": 100, "год_выпуска": 2025, "тип_тс": "легковые",
        "коэф_вкл": 1, "стоимость_млн": 12.5,
        "льгота_вкл": 1, "льгота_процент": 50,
    }
)
v1 = db2.get_vehicle_by_id(vid)
check(
    "новые поля сохранились в БД",
    v1["коэф_вкл"] == 1 and v1["стоимость_млн"] == 12.5 and v1["льгота_процент"] == 50,
    str(v1),
)
db2.update_vehicle(vid, {"льгота_вкл": 0, "льгота_процент": 0})
v2 = db2.get_vehicle_by_id(vid)
check(
    "UPDATE новых полей через белый список",
    v2["льгота_вкл"] == 0 and v2["коэф_вкл"] == 1 and v2["стоимость_млн"] == 12.5,
    str(v2),
)

# ==================== 11. Десятичные ставки ====================
print("\n--- 11. Десятичные ставки ---")
check("ставка: '12,5' -> 12.5", tax_app._parse_rate_value("12,5") == 12.5)
check("ставка: '12.5' -> 12.5", tax_app._parse_rate_value("12.5") == 12.5)
check("ставка: '30' -> 30.0", tax_app._parse_rate_value("30") == 30.0)
check("ставка: '10,6 руб./л.с.' -> 10.6", tax_app._parse_rate_value("10,6 руб./л.с.") == 10.6)
check("ставка: 'свыше 200 - 80' -> 80", tax_app._parse_rate_value("свыше 200 - 80") == 80.0)
check(
    "ставка: неразрывный пробел",
    tax_app._parse_rate_value("12,5\xa0руб.") == 12.5,
)
try:
    tax_app._parse_rate_value("нет числа")
    check("ставка: мусор -> ValueError", False)
except ValueError:
    check("ставка: мусор -> ValueError", True)

# _parse_html раньше ломал «12,5» в «125» (int от всех цифр) — регрессия под запятую
html_rates = """
<table>
<tr><td>Легковые автомобили</td></tr>
<tr><td>100 - 150</td><td>12,5</td></tr>
<tr><td>свыше 350</td><td>80</td></tr>
</table>
"""
_loader = tax_app.AutoConfigLoader.__new__(tax_app.AutoConfigLoader)
_parsed = _loader._parse_html(html_rates) or {}
_leg = _parsed.get("легковые", {})
check("html-парсер: десятичная ставка 12,5 не ломается", _leg.get((100, 150)) == 12.5, str(_leg))
check("html-парсер: целая ставка 80", _leg.get((350, float("inf"))) == 80.0, str(_leg))

# ==================== 12. Единая функция расчёта ====================
print("\n--- 12. Единая функция расчёта ---")
_base_v = {"мощность": 100, "год_выпуска": 2020, "тип_тс": "легковые"}
_qm = {1: 3, 2: 3, 3: 3, 4: 3}
_t1, _qt1, _k1, _kb1 = tax_app.compute_vehicle_tax(_base_v, 2026, 50, _qm)
check(
    "единый расчёт: базовый",
    _t1 == 5000 and all(_qt1[q] == 1250 for q in (1, 2, 3, 4)) and _k1 == 1 and _kb1 == 1,
    f"{_t1} {_qt1}",
)
_combo_v = dict(_base_v, коэф_вкл=1, стоимость_млн=12, льгота_вкл=1, льгота_процент=50)
_t2, _qt2, _k2, _kb2 = tax_app.compute_vehicle_tax(_combo_v, 2026, 50, _qm)
check(
    "единый расчёт: коэффициент + льгота",
    _t2 == 7500 and _qt2[1] == 1875 and _k2 == 3.0 and _kb2 == 0.5,
    f"{_t2} {_qt2}",
)
_disp_v = dict(_base_v, дата_списания="2026-03-15")
_t3, _qt3, _k3, _kb3 = tax_app.compute_vehicle_tax(_disp_v, 2026, 50, _qm)
check(
    "единый расчёт: списание обнуляет кварталы",
    _t3 == 1250 and _qt3 == {1: 1250, 2: 0, 3: 0, 4: 0},
    f"{_t3} {_qt3}",
)
check(
    "единый расчёт: итог = сумма кварталов",
    _t1 == sum(_qt1.values()) and _t2 == sum(_qt2.values()) and _t3 == sum(_qt3.values()),
)

# ==================== 13. Парсер диапазонов ставок ====================
print("\n--- 13. Парсер диапазонов ---")
check("диапазон: 'от 100 до 150'", _loader._parse_range("от 100 до 150") == (100, 150))
check("диапазон: 'до 100'", _loader._parse_range("до 100") == (0, 100))
check("диапазон: 'свыше 200'", _loader._parse_range("свыше 200") == (200, float("inf")))
check("диапазон: '100-150'", _loader._parse_range("100-150") == (100, 150))

print()
if FAILED:
    print(f"ПРОВАЛЕНО тестов: {len(FAILED)}: {', '.join(FAILED)}")
    sys.exit(1)
print("Все тесты пройдены.")
