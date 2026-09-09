#!/usr/bin/env python3
import base64
import csv
import html
import io
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PHOTOS = DATA / "photos"
DB = DATA / "contacts.sqlite3"
INDEX = ROOT / "index.html"
DRIVE_EXPORT = Path(os.environ.get(
    "DRIVE_EXPORT_DIR",
    "/Users/doc9/Library/CloudStorage/GoogleDrive-yohai.shraga@gmail.com/My Drive/דף קשר גן נגה",
))
MAX_BODY = 18 * 1024 * 1024

DATA.mkdir(exist_ok=True)
PHOTOS.mkdir(exist_ok=True)


def connect():
    db = sqlite3.connect(DB)
    db.execute(
        """CREATE TABLE IF NOT EXISTS contacts (
        id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
        child_first TEXT NOT NULL, child_last TEXT NOT NULL,
        birth_date TEXT NOT NULL, group_name TEXT NOT NULL,
        address TEXT NOT NULL, parent1 TEXT NOT NULL, phone1 TEXT NOT NULL,
        parent2 TEXT NOT NULL, phone2 TEXT NOT NULL, photo_file TEXT NOT NULL
        )"""
    )
    db.commit()
    return db


def rows():
    with connect() as db:
        db.row_factory = sqlite3.Row
        return db.execute("SELECT * FROM contacts ORDER BY created_at DESC").fetchall()


def export_to_drive():
    DRIVE_EXPORT.mkdir(parents=True, exist_ok=True)
    drive_photos = DRIVE_EXPORT / "תמונות"
    drive_photos.mkdir(exist_ok=True)
    for photo in PHOTOS.iterdir():
        if photo.is_file():
            shutil.copy2(photo, drive_photos / photo.name)
    target = DRIVE_EXPORT / "דף קשר גן נגה.csv"
    temp = target.with_suffix(".csv.tmp")
    with temp.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["שם הילד/ה", "שם משפחה", "תאריך לידה", "קבוצה", "כתובת", "הורה 1", "טלפון 1", "הורה 2", "טלפון 2", "תמונה", "תאריך מילוי"])
        for r in rows():
            photo_name = Path(r["photo_file"]).name
            writer.writerow([r[k] for k in ("child_first", "child_last", "birth_date", "group_name", "address", "parent1", "phone1", "parent2", "phone2")] + [f"תמונות/{photo_name}", r["created_at"]])
    temp.replace(target)


def safe_text(value, limit=200):
    return str(value or "").strip()[:limit]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.now().isoformat(timespec='seconds')}] {self.address_string()} {fmt % args}", flush=True)

    def send_bytes(self, status, body, content_type, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def is_local(self):
        return self.client_address[0] in {"127.0.0.1", "::1"}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send_bytes(200, INDEX.read_bytes(), "text/html; charset=utf-8")
        elif path == "/health":
            self.send_bytes(200, b'{"ok":true}', "application/json")
        elif path == "/admin":
            if not self.is_local():
                return self.send_bytes(404, b"Not found", "text/plain")
            items = rows()
            table = "".join(
                "<tr>" + "".join(f"<td>{html.escape(str(r[k]))}</td>" for k in (
                    "child_first", "child_last", "birth_date", "group_name", "address",
                    "parent1", "phone1", "parent2", "phone2", "created_at"
                )) + "</tr>" for r in items
            )
            page = f"""<!doctype html><html lang=he dir=rtl><meta charset=utf-8>
            <meta name=viewport content='width=device-width,initial-scale=1'><title>מאגר דף קשר</title>
            <style>body{{font-family:Arial;margin:24px;color:#23332d}}a{{display:inline-block;padding:12px 18px;background:#2e765a;color:white;border-radius:10px;text-decoration:none;margin-bottom:18px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border:1px solid #ddd;padding:8px;text-align:right}}th{{background:#f3f5f4}}</style>
            <h1>מאגר דף קשר</h1><p>{len(items)} רשומות</p><a href=/export.csv>הורדת Excel / CSV</a>
            <table><thead><tr><th>שם</th><th>משפחה</th><th>תאריך לידה</th><th>קבוצה</th><th>כתובת</th><th>הורה 1</th><th>טלפון 1</th><th>הורה 2</th><th>טלפון 2</th><th>נוצר</th></tr></thead><tbody>{table}</tbody></table>"""
            self.send_bytes(200, page.encode(), "text/html; charset=utf-8")
        elif path == "/export.csv":
            if not self.is_local():
                return self.send_bytes(404, b"Not found", "text/plain")
            out = io.StringIO()
            writer = csv.writer(out)
            writer.writerow(["שם הילד/ה", "שם משפחה", "תאריך לידה", "קבוצה", "כתובת", "הורה 1", "טלפון 1", "הורה 2", "טלפון 2", "קובץ תמונה", "תאריך מילוי"])
            for r in rows():
                writer.writerow([r[k] for k in ("child_first", "child_last", "birth_date", "group_name", "address", "parent1", "phone1", "parent2", "phone2", "photo_file", "created_at")])
            body = ("\ufeff" + out.getvalue()).encode("utf-8")
            self.send_bytes(200, body, "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="kindergarten-contacts.csv"'})
        else:
            self.send_bytes(404, b"Not found", "text/plain")

    def do_POST(self):
        if self.path != "/submit":
            return self.send_bytes(404, b"Not found", "text/plain")
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ValueError("invalid size")
            payload = json.loads(self.rfile.read(length))
            required = ["firstName", "lastName", "birthDate", "group", "address", "parent1", "phone1", "parent2", "phone2", "photo"]
            if any(not safe_text(payload.get(k), 20_000_000) for k in required):
                raise ValueError("missing fields")
            if payload["group"] not in {"yellow", "blue"}:
                raise ValueError("invalid group")
            match = re.match(r"^data:image/(jpeg|png|webp);base64,(.+)$", payload["photo"], re.S)
            if not match:
                raise ValueError("invalid photo")
            ext = {"jpeg": "jpg", "png": "png", "webp": "webp"}[match.group(1)]
            raw = base64.b64decode(match.group(2), validate=True)
            if len(raw) > 12 * 1024 * 1024:
                raise ValueError("photo too large")
            record_id = uuid.uuid4().hex
            photo_name = f"{record_id}.{ext}"
            (PHOTOS / photo_name).write_bytes(raw)
            values = (
                record_id, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                safe_text(payload["firstName"]), safe_text(payload["lastName"]), safe_text(payload["birthDate"], 20),
                "צהובים" if payload["group"] == "yellow" else "כחולים", safe_text(payload["address"], 300),
                safe_text(payload["parent1"]), safe_text(payload["phone1"], 40), safe_text(payload["parent2"]),
                safe_text(payload["phone2"], 40), f"photos/{photo_name}"
            )
            with connect() as db:
                db.execute("INSERT INTO contacts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", values)
                db.commit()
            export_to_drive()
            self.send_bytes(201, json.dumps({"ok": True, "id": record_id}).encode(), "application/json")
        except Exception as exc:
            self.send_bytes(400, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")


if __name__ == "__main__":
    connect().close()
    ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("PORT", "8787"))), Handler).serve_forever()
