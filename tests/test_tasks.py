"""Tareas y entregas (Fase 7): agrupación y exportación .ics."""

from uji_sync.tasks import group_events, to_ics

NOW = 1_800_000_000
EV = [
    {"id": 1, "course": "Cálculo I", "name": "Práctica 1; parte A, B", "timesort": NOW + 86400,
     "url": "https://aulavirtual.uji.es/mod/assign/view.php?id=7", "action": "Añadir entrega",
     "overdue": False, "modulename": "assign", "done": False},
    {"id": 2, "course": "Física I", "name": "Cuestionario", "timesort": NOW - 3600, "url": "", "action": "",
     "overdue": False, "modulename": "quiz", "done": False},
    {"id": 3, "course": "Física I", "name": "Informe", "timesort": NOW + 7200, "url": "", "action": "",
     "overdue": False, "modulename": "assign", "done": True},
]


def test_group_events():
    g = group_events(EV, now=NOW)
    assert [e["id"] for e in g["overdue"]] == [2]  # pasó la fecha
    assert [e["id"] for e in g["upcoming"]] == [1]
    assert [e["id"] for e in g["done"]] == [3]


def test_ics():
    ics = to_ics(EV)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 3 and "UID:ujistudy-1@aulavirtual.uji.es" in ics
    assert r"SUMMARY:Entrega: Práctica 1\; parte A\, B (Cálculo I)" in ics  # texto escapado (RFC 5545)
    assert "DTSTART:20270116T080000Z" in ics and "TRIGGER:-P1D" in ics
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))  # líneas plegadas
