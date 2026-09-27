"""Tareas y entregas (Fase 7): agrupación y exportación a calendario (.ics)."""

from __future__ import annotations

from datetime import datetime, timezone

DAY_NAMES = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def group_events(events: list[dict], now: float | None = None) -> dict:
    """Vencidas, próximas y hechas (las hechas no cuentan como pendientes)."""
    now = now if now is not None else datetime.now().timestamp()
    overdue = [e for e in events if not e["done"] and (e["overdue"] or e["timesort"] < now)]
    upcoming = [e for e in events if not e["done"] and e not in overdue]
    done = [e for e in events if e["done"]]
    return {"overdue": overdue, "upcoming": upcoming, "done": done}


def _ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> str:
    """Las líneas de un .ics no deben superar 75 octetos (RFC 5545)."""
    out, current = [], ""
    for ch in line:
        if len((current + ch).encode("utf-8")) > 75:
            out.append(current)
            current = " " + ch
        else:
            current += ch
    out.append(current)
    return "\r\n".join(out)


def to_ics(events: list[dict]) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//UJI Study Assistant//ES",
             "CALSCALE:GREGORIAN", "X-WR-CALNAME:UJI · Entregas"]
    for e in events:
        when = datetime.fromtimestamp(e["timesort"], timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        summary = f"Entrega: {e['name']}" + (f" ({e['course']})" if e["course"] else "")
        lines += [
            "BEGIN:VEVENT",
            f"UID:ujistudy-{e['id']}@aulavirtual.uji.es",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{when}",
            f"DTEND:{when}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape((e['action'] + ' · ' if e['action'] else '') + e['url'])}",
        ]
        if e["url"]:
            lines.append(f"URL:{e['url']}")
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-P1D",
                  f"DESCRIPTION:{_ics_escape('Mañana: ' + summary)}", "END:VALARM", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
