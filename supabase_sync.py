#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مزامنة تلقائية (best-effort) مع قاعدة بيانات Supabase الخارجية عبر REST API.

هذا الملف إضافي بالكامل ولا يغيّر أي منطق موجود في bot_file.py.
- يستخدم Supabase REST API (PostgREST) مع مفتاح anon — لا يحتاج psycopg2 ولا SUPABASE_DB_URL.
- إذا لم يتم ضبط SUPABASE_URL / SUPABASE_ANON_KEY، تتحول كل الدوال هنا إلى no-op بدون أي تأثير على البوت.
- كل عملية مزامنة تُنفَّذ في Thread منفصل (fire-and-forget) حتى لا تُبطئ أو توقف الاستجابة للمستخدم أبداً.
- أي خطأ في المزامنة يُسجَّل فقط في اللوج ولا يُرفع كاستثناء يوقف البوت.
- جلب البروكسي (fetch_proxy) متزامن لأن البوت يحتاجه فوراً عند الإرسال.
"""

import os
import json
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

import requests

logger = logging.getLogger(__name__)

# بيانات الاتصال — تُقرأ من متغيرات البيئة
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "").strip()

_enabled = bool(SUPABASE_URL and SUPABASE_ANON_KEY)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="supabase-sync")


def is_enabled() -> bool:
    return _enabled


def _headers(extra: dict = None) -> dict:
    h = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def _rest_url(table: str) -> str:
    return f"{SUPABASE_URL}/rest/v1/{table}"


def _run(fn, *args):
    """ينفّذ عملية المزامنة في الخلفية دون حجب البوت أبداً."""
    if not _enabled:
        return

    def _wrapped():
        try:
            fn(*args)
        except Exception as e:
            logger.warning(f"[Supabase Sync] فشلت عملية مزامنة: {e}")

    try:
        _executor.submit(_wrapped)
    except Exception as e:
        logger.warning(f"[Supabase Sync] تعذر جدولة المزامنة: {e}")


def _upsert(table, row: dict, conflict_cols):
    """upsert عبر REST: POST مع Prefer: resolution=merge-duplicates."""
    if not _enabled:
        return
    on_conflict = ",".join(conflict_cols)
    headers = _headers({
        "Prefer": "return=representation,resolution=merge-duplicates",
    })
    params = {"on_conflict": on_conflict}
    resp = requests.post(_rest_url(table), json=row, headers=headers, params=params, timeout=15)
    if resp.status_code not in (200, 201):
        logger.warning(f"[Supabase Sync] upsert {table} فشل: HTTP {resp.status_code} - {resp.text[:200]}")


def _delete(table, filters: dict):
    """حذف صفوف عبر REST: DELETE مع فلترة بمعاملات الرابط."""
    if not _enabled:
        return
    headers = _headers({"Prefer": "return=minimal"})
    params = []
    for col, val in filters.items():
        params.append(f"{col}=eq.{val}")
    query = "&".join(params)
    url = f"{_rest_url(table)}?{query}" if query else _rest_url(table)
    resp = requests.delete(url, headers=headers, timeout=15)
    if resp.status_code not in (200, 204):
        logger.warning(f"[Supabase Sync] delete {table} فشل: HTTP {resp.status_code} - {resp.text[:200]}")


def _fetch_rows(table, columns, filters: dict = None):
    """جلب صفوف متزامن من REST. يُرجع قائمة dicts."""
    if not _enabled:
        return []
    headers = _headers({"Accept": "application/json"})
    params = [f"select={','.join(columns)}"]
    if filters:
        for col, val in filters.items():
            params.append(f"{col}=eq.{val}")
    query = "&".join(params)
    url = f"{_rest_url(table)}?{query}"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return resp.json()
        logger.warning(f"[Supabase Sync] fetch {table} فشل: HTTP {resp.status_code} - {resp.text[:200]}")
        return []
    except Exception as e:
        logger.warning(f"[Supabase Sync] fetch {table} استثناء: {e}")
        return []


# ==================== المستخدمون ====================

def sync_user(user_id, username, name, banned, admin, allowed, created_at, total_requests):
    _run(_upsert, "users", {
        "user_id": user_id, "username": username, "name": name,
        "banned": banned, "admin": admin, "allowed": allowed,
        "created_at": created_at, "total_requests": total_requests,
    }, ["user_id"])


def sync_allowed_user(user_id, username, name, added_by, added_date):
    _run(_upsert, "allowed_users", {
        "user_id": user_id, "username": username, "name": name,
        "added_by": added_by, "added_date": added_date,
    }, ["user_id"])


def sync_allowed_user_delete(user_id):
    _run(_delete, "allowed_users", {"user_id": user_id})


def sync_user_platform(user_id, platform):
    _run(_upsert, "user_platform", {"user_id": user_id, "platform": platform}, ["user_id"])


# ==================== البروكسي ====================

def sync_proxy(user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date):
    _run(_upsert, "proxies", {
        "user_id": user_id, "proxy_type": proxy_type, "proxy_host": proxy_host,
        "proxy_port": proxy_port, "proxy_user": proxy_user, "proxy_pass": proxy_pass,
        "created_date": created_date,
    }, ["user_id"])


def sync_proxy_sync(user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date):
    """يكتب البروكسي إلى Supabase بشكل متزامن (فوري) — ينتظر حتى يكتمل الكتاب
    أو يفشل بدلاً من العمل في الخلفية. يُرجع True عند النجاح."""
    if not _enabled:
        return True
    try:
        _upsert("proxies",
                ["user_id", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass", "created_date"],
                [user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date],
                ["user_id"])
        return True
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل حفظ البروكسي بشكل متزامن: {e}")
        return False


def sync_proxy_delete(user_id):
    _run(_delete, "proxies", {"user_id": user_id})


def sync_proxy_delete_sync(user_id):
    """يحذف البروكسي من Supabase بشكل متزامن (فوري). يُرجع True عند النجاح."""
    if not _enabled:
        return True
    try:
        _delete("proxies", ["user_id"], [user_id])
        return True
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل حذف البروكسي بشكل متزامن: {e}")
        return False


def fetch_proxy(user_id):
    """يجلب بروكسي المستخدم من Supabase بشكل متزامن. يُرجع None إذا لم يوجد أو كانت المزامنة معطلة."""
    if not _enabled:
        return None
    rows = _fetch_rows("proxies", ["proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass"], {"user_id": user_id})
    if not rows:
        return None
    r = rows[0]
    return (r.get("proxy_type"), r.get("proxy_host"), r.get("proxy_port"), r.get("proxy_user"), r.get("proxy_pass"))


# ==================== مهام المزرعة ====================

def sync_farm_task(task_row: dict):
    _run(_upsert, "farm_tasks", task_row, ["task_name"])


# ==================== إحصائيات المستخدم ====================

def sync_user_stats(user_id, last_daily_reset, daily_requests, total_af, total_adj, total_singular):
    _run(_upsert, "user_stats", {
        "user_id": user_id, "last_daily_reset": last_daily_reset,
        "daily_requests": daily_requests,
        "total_af_requests": total_af, "total_adj_requests": total_adj,
        "total_singular_requests": total_singular,
    }, ["user_id"])


# ==================== المفضلة ====================

def sync_favorite(user_id, platform, game_id, game_name):
    _run(_upsert, "favorites", {
        "user_id": user_id, "platform": platform, "game_id": game_id,
        "game_name": game_name, "added_date": datetime.now().isoformat(),
    }, ["user_id", "platform", "game_id"])


def sync_favorite_delete(user_id, platform, game_id):
    _run(_delete, "favorites", {"user_id": user_id, "platform": platform, "game_id": game_id})


# ==================== ملفات المعرفات المحفوظة ====================

def sync_credential_file(user_id, platform, game_id, filename, data: dict):
    _run(_upsert, "credential_files", {
        "user_id": user_id, "platform": platform, "game_id": game_id,
        "filename": filename, "data": json.dumps(data, ensure_ascii=False),
        "created_date": datetime.now().isoformat(),
    }, ["user_id", "platform", "game_id", "filename"])


def sync_credential_file_delete(user_id, cred_id):
    """حذف ملف معرفات واحد من Supabase (best-effort)."""
    if not _enabled:
        return
    try:
        headers = _headers({"Prefer": "return=minimal"})
        url = f"{_rest_url('credential_files')}?id=eq.{cred_id}&user_id=eq.{user_id}"
        resp = requests.delete(url, headers=headers, timeout=15)
        if resp.status_code not in (200, 204):
            logger.warning(f"[Supabase Sync] حذف ملف المعرفات فشل: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل حذف ملف المعرفات: {e}")


# ==================== الألعاب/الأحداث المضافة من لوحة التحكم ====================

def sync_game_af(game_id, name, display_name, package, dev_key, emoji):
    _run(_upsert, "games_af", {
        "id": game_id, "name": name, "display_name": display_name,
        "package": package, "dev_key": dev_key, "emoji": emoji,
    }, ["id"])


def sync_game_adj(game_id, name, display_name, app_token, emoji):
    _run(_upsert, "games_adj", {
        "id": game_id, "name": name, "display_name": display_name,
        "app_token": app_token, "emoji": emoji,
    }, ["id"])


def sync_game_singular(game_id, name, display_name, package, app_key, emoji):
    _run(_upsert, "games_singular", {
        "id": game_id, "name": name, "display_name": display_name,
        "package": package, "app_key": app_key, "emoji": emoji,
    }, ["id"])


def sync_event_af(event_id, game_id, event_name, display_name, event_type, is_purchase):
    _run(_upsert, "events_af", {
        "id": event_id, "game_id": game_id, "event_name": event_name,
        "display_name": display_name, "event_type": event_type, "is_purchase": is_purchase,
    }, ["id"])


def sync_event_singular(event_id, game_id, event_name, display_name, event_type):
    _run(_upsert, "events_singular", {
        "id": event_id, "game_id": game_id, "event_name": event_name,
        "display_name": display_name, "event_type": event_type,
    }, ["id"])


def sync_event_adj(event_id, game_id, event_name, event_token, display_name, level_value):
    _run(_upsert, "events_adj", {
        "id": event_id, "game_id": game_id, "event_name": event_name,
        "event_token": event_token, "display_name": display_name, "level_value": level_value,
    }, ["id"])


# ==================== مجموعات الجدولة ====================

def sync_sched_group(group_row: dict):
    _run(_upsert, "sched_groups", group_row, ["id"])


def sync_sched_group_delete(group_id):
    _run(_delete, "sched_groups", {"id": group_id})


# ==================== استعادة البيانات من Supabase عند الإقلاع ====================

def restore_all(sqlite_conn):
    """
    يستعيد كل البيانات من Supabase إلى SQLite المحلي عند الإقلاع.
    يُستدعى بشكل متزامن قبل بدء البوت لضمان توفر البيانات.
    لا يمسح البيانات المحلية الموجودة — يستخدم INSERT OR IGNORE / INSERT OR REPLACE.
    """
    if not _enabled:
        logger.info("[Supabase Sync] المزامنة معطلة - تخطي استعادة البيانات")
        return

    cur = sqlite_conn.cursor()
    restored = 0

    # 1) المستخدمون
    rows = _fetch_rows("users", ["user_id", "username", "name", "last_use", "banned", "admin", "allowed", "created_at", "total_requests"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, name, last_use, banned, admin, allowed, created_at, total_requests) VALUES (?,?,?,?,?,?,?,?,?)",
            (r.get("user_id"), r.get("username"), r.get("name"), r.get("last_use"),
             r.get("banned", 0), r.get("admin", 0), r.get("allowed", 0),
             r.get("created_at"), r.get("total_requests", 0))
        )
    restored += len(rows)

    # 2) المستخدمون المسموحون
    rows = _fetch_rows("allowed_users", ["user_id", "username", "name", "added_by", "added_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO allowed_users (user_id, username, name, added_by, added_date) VALUES (?,?,?,?,?)",
            (r.get("user_id"), r.get("username"), r.get("name"), r.get("added_by"), r.get("added_date"))
        )
    restored += len(rows)

    # 3) منصة المستخدم
    rows = _fetch_rows("user_platform", ["user_id", "platform"])
    for r in rows:
        cur.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?,?)",
                    (r.get("user_id"), r.get("platform")))
    restored += len(rows)

    # 4) الألعاب (af)
    rows = _fetch_rows("games_af", ["id", "name", "display_name", "package", "dev_key", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_af (id, name, display_name, package, dev_key, emoji) VALUES (?,?,?,?,?,?)",
            (r.get("id"), r.get("name"), r.get("display_name"), r.get("package"), r.get("dev_key"), r.get("emoji"))
        )
    restored += len(rows)

    # 4b) الألعاب (singular)
    rows = _fetch_rows("games_singular", ["id", "name", "display_name", "package", "app_key", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_singular (id, name, display_name, package, app_key, emoji) VALUES (?,?,?,?,?,?)",
            (r.get("id"), r.get("name"), r.get("display_name"), r.get("package"), r.get("app_key"), r.get("emoji"))
        )
    restored += len(rows)

    # 4c) الألعاب (adj)
    rows = _fetch_rows("games_adj", ["id", "name", "display_name", "app_token", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_adj (id, name, display_name, app_token, emoji) VALUES (?,?,?,?,?)",
            (r.get("id"), r.get("name"), r.get("display_name"), r.get("app_token"), r.get("emoji"))
        )
    restored += len(rows)

    # 5) الأحداث (af)
    rows = _fetch_rows("events_af", ["id", "game_id", "event_name", "display_name", "event_type", "is_purchase"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_af (id, game_id, event_name, display_name, event_type, is_purchase) VALUES (?,?,?,?,?,?)",
            (r.get("id"), r.get("game_id"), r.get("event_name"), r.get("display_name"),
             r.get("event_type"), r.get("is_purchase", 0))
        )
    restored += len(rows)

    # 5b) الأحداث (singular)
    rows = _fetch_rows("events_singular", ["id", "game_id", "event_name", "display_name", "event_type"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_singular (id, game_id, event_name, display_name, event_type) VALUES (?,?,?,?,?)",
            (r.get("id"), r.get("game_id"), r.get("event_name"), r.get("display_name"), r.get("event_type"))
        )
    restored += len(rows)

    # 5c) الأحداث (adj)
    rows = _fetch_rows("events_adj", ["id", "game_id", "event_name", "event_token", "display_name", "level_value"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_adj (id, game_id, event_name, event_token, display_name, level_value) VALUES (?,?,?,?,?,?)",
            (r.get("id"), r.get("game_id"), r.get("event_name"), r.get("event_token"),
             r.get("display_name"), r.get("level_value"))
        )
    restored += len(rows)

    # 6) البروكسي
    rows = _fetch_rows("proxies", ["user_id", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass", "created_date", "last_used", "usage_count"])
    for r in rows:
        cur.execute(
            "INSERT OR REPLACE INTO proxies (user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date, last_used, usage_count) VALUES (?,?,?,?,?,?,?,?,?)",
            (r.get("user_id"), r.get("proxy_type"), r.get("proxy_host"), r.get("proxy_port"),
             r.get("proxy_user"), r.get("proxy_pass"), r.get("created_date"),
             r.get("last_used"), r.get("usage_count", 0))
        )
    restored += len(rows)

    # 7) مزرعة المهام
    farm_cols = [
        "task_name", "user_id", "platform", "game_id", "game_name",
        "start_level", "end_level", "total_days", "mode",
        "current_day", "current_level", "status", "created_date", "last_run",
        "aifa", "gaid", "uid", "af_uid", "gps_adid",
        "idfa", "idfv", "att_status", "completed_levels", "failed_attempts"
    ]
    rows = _fetch_rows("farm_tasks", farm_cols)
    placeholders = ",".join(["?"] * len(farm_cols))
    cols_sql = ", ".join(farm_cols)
    for r in rows:
        cur.execute(f"INSERT OR REPLACE INTO farm_tasks ({cols_sql}) VALUES ({placeholders})",
                    tuple(r.get(c) for c in farm_cols))
    restored += len(rows)

    # 8) إحصائيات المستخدم
    rows = _fetch_rows("user_stats", ["user_id", "last_daily_reset", "daily_requests", "total_af_requests", "total_adj_requests", "total_singular_requests"])
    for r in rows:
        cur.execute(
            "INSERT OR REPLACE INTO user_stats (user_id, last_daily_reset, daily_requests, total_af_requests, total_adj_requests, total_singular_requests) VALUES (?,?,?,?,?,?)",
            (r.get("user_id"), r.get("last_daily_reset"), r.get("daily_requests", 0),
             r.get("total_af_requests", 0), r.get("total_adj_requests", 0), r.get("total_singular_requests", 0))
        )
    restored += len(rows)

    # 9) المفضلة
    rows = _fetch_rows("favorites", ["user_id", "platform", "game_id", "game_name", "added_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO favorites (user_id, platform, game_id, game_name, added_date) VALUES (?,?,?,?,?)",
            (r.get("user_id"), r.get("platform"), r.get("game_id"), r.get("game_name"), r.get("added_date"))
        )
    restored += len(rows)

    # 10) ملفات المعرفات
    rows = _fetch_rows("credential_files", ["user_id", "platform", "game_id", "filename", "data", "created_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO credential_files (user_id, platform, game_id, filename, data, created_date) VALUES (?,?,?,?,?,?)",
            (r.get("user_id"), r.get("platform"), r.get("game_id"), r.get("filename"),
             r.get("data"), r.get("created_date"))
        )
    restored += len(rows)

    # 11) مجموعات الجدولة
    sched_cols = [
        "id", "user_id", "platform", "game_id", "game_name",
        "game_pkg", "game_key", "events_order", "interval_minutes",
        "gaid", "af_uid", "status", "created_date", "next_run"
    ]
    rows = _fetch_rows("sched_groups", sched_cols)
    sched_placeholders = ",".join(["?"] * len(sched_cols))
    sched_cols_sql = ", ".join(sched_cols)
    for r in rows:
        cur.execute(
            f"INSERT OR REPLACE INTO sched_groups ({sched_cols_sql}) VALUES ({sched_placeholders})",
            tuple(r.get(c) for c in sched_cols)
        )
    restored += len(rows)

    sqlite_conn.commit()
    logger.info(f"[Supabase Sync] تم استعادة {restored} صف من Supabase إلى SQLite")
