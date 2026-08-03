#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
مزامنة تلقائية (best-effort) مع قاعدة بيانات Supabase/Postgres خارجية.

هذا الملف إضافي بالكامل ولا يغيّر أي منطق موجود في bot_file.py.
- إذا لم يتم ضبط SUPABASE_DB_URL، تتحول كل الدوال هنا إلى no-op بدون أي تأثير على البوت.
- كل عملية مزامنة تُنفَّذ في Thread منفصل (fire-and-forget) حتى لا تُبطئ أو توقف الاستجابة للمستخدم أبداً.
- أي خطأ في المزامنة يُسجَّل فقط في اللوج ولا يُرفع كاستثناء يوقف البوت.
"""

import os
import json
import logging
import threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL", "").strip()

_enabled = bool(SUPABASE_DB_URL)
psycopg2 = None

if _enabled:
    try:
        import psycopg2 as _psycopg2
        psycopg2 = _psycopg2
    except ImportError:
        _enabled = False
        logger.warning("[Supabase Sync] مكتبة psycopg2 غير مثبتة - تم تعطيل المزامنة التلقائية مع Supabase")

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="supabase-sync")
_conn_lock = threading.Lock()
_conn = None


def is_enabled() -> bool:
    return _enabled


def _get_conn():
    global _conn
    if not _enabled:
        return None
    with _conn_lock:
        if _conn is None or getattr(_conn, "closed", 1):
            try:
                _conn = psycopg2.connect(SUPABASE_DB_URL, connect_timeout=10)
                _conn.autocommit = True
            except Exception as e:
                logger.warning(f"[Supabase Sync] فشل الاتصال بـ Supabase: {e}")
                _conn = None
        return _conn


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


def _upsert(table, columns, values, conflict_cols):
    conn = _get_conn()
    if not conn:
        return
    cols_sql = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(values))
    update_cols = [c for c in columns if c not in conflict_cols]
    conflict_sql = ", ".join(conflict_cols)
    if update_cols:
        update_sql = ", ".join([f"{c}=EXCLUDED.{c}" for c in update_cols])
        sql = (f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
               f"ON CONFLICT ({conflict_sql}) DO UPDATE SET {update_sql}")
    else:
        sql = (f"INSERT INTO {table} ({cols_sql}) VALUES ({placeholders}) "
               f"ON CONFLICT ({conflict_sql}) DO NOTHING")
    with conn.cursor() as cur:
        cur.execute(sql, values)


def _delete(table, where_cols, where_values):
    conn = _get_conn()
    if not conn:
        return
    where_sql = " AND ".join([f"{c}=%s" for c in where_cols])
    sql = f"DELETE FROM {table} WHERE {where_sql}"
    with conn.cursor() as cur:
        cur.execute(sql, where_values)


# ==================== المستخدمون ====================

def sync_user(user_id, username, name, banned, admin, allowed, created_at, total_requests):
    _run(_upsert, "users",
         ["user_id", "username", "name", "banned", "admin", "allowed", "created_at", "total_requests"],
         [user_id, username, name, banned, admin, allowed, created_at, total_requests],
         ["user_id"])


def sync_allowed_user(user_id, username, name, added_by, added_date):
    _run(_upsert, "allowed_users",
         ["user_id", "username", "name", "added_by", "added_date"],
         [user_id, username, name, added_by, added_date],
         ["user_id"])


def sync_allowed_user_delete(user_id):
    _run(_delete, "allowed_users", ["user_id"], [user_id])


def sync_user_platform(user_id, platform):
    _run(_upsert, "user_platform", ["user_id", "platform"], [user_id, platform], ["user_id"])


# ==================== البروكسي ====================

def sync_proxy(user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date):
    _run(_upsert, "proxies",
         ["user_id", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass", "created_date"],
         [user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date],
         ["user_id"])


def sync_proxy_delete(user_id):
    _run(_delete, "proxies", ["user_id"], [user_id])


def fetch_proxy(user_id):
    """يجلب بروكسي المستخدم من Supabase بشكل متزامن. يُرجع None إذا لم يوجد أو كانت المزامنة معطلة."""
    conn = _get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass FROM proxies WHERE user_id = %s",
                (user_id,)
            )
            return cur.fetchone()
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل جلب البروكسي: {e}")
        return None


# ==================== مهام المزرعة ====================

def sync_farm_task(task_row: dict):
    columns = list(task_row.keys())
    values = [task_row[c] for c in columns]
    _run(_upsert, "farm_tasks", columns, values, ["task_name"])


# ==================== إحصائيات المستخدم ====================

def sync_user_stats(user_id, last_daily_reset, daily_requests, total_af, total_adj, total_singular):
    _run(_upsert, "user_stats",
         ["user_id", "last_daily_reset", "daily_requests", "total_af_requests", "total_adj_requests", "total_singular_requests"],
         [user_id, last_daily_reset, daily_requests, total_af, total_adj, total_singular],
         ["user_id"])


# ==================== المفضلة ====================

def sync_favorite(user_id, platform, game_id, game_name):
    _run(_upsert, "favorites",
         ["user_id", "platform", "game_id", "game_name", "added_date"],
         [user_id, platform, game_id, game_name, datetime.now().isoformat()],
         ["user_id", "platform", "game_id"])


def sync_favorite_delete(user_id, platform, game_id):
    _run(_delete, "favorites", ["user_id", "platform", "game_id"], [user_id, platform, game_id])


# ==================== ملفات المعرفات المحفوظة ====================

def sync_credential_file(user_id, platform, game_id, filename, data: dict):
    _run(_upsert, "credential_files",
         ["user_id", "platform", "game_id", "filename", "data", "created_date"],
         [user_id, platform, game_id, filename, json.dumps(data, ensure_ascii=False), datetime.now().isoformat()],
         ["user_id", "platform", "game_id", "filename"])


def sync_credential_file_delete(user_id, cred_id):
    """حذف ملف معرفات واحد من Supabase (best-effort)."""
    conn = _get_conn()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM credential_files WHERE id = %s AND user_id = %s", (cred_id, user_id))
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل حذف ملف المعرفات: {e}")


# ==================== الألعاب/الأحداث المضافة من لوحة التحكم ====================
# ملاحظة: لا تُستخدم هذه الدوال أبداً مع الألعاب المُبرمجة الأساسية
# (AF_GAMES / SINGULAR_GAMES / ADJ_GAMES) - فقط مع الألعاب/الأحداث التي يضيفها
# الأدمن يدوياً من لوحة التحكم، حسب طلب المستخدم الصريح.

def sync_game_af(game_id, name, display_name, package, dev_key, emoji):
    _run(_upsert, "games_af",
         ["id", "name", "display_name", "package", "dev_key", "emoji"],
         [game_id, name, display_name, package, dev_key, emoji],
         ["id"])


def sync_game_adj(game_id, name, display_name, app_token, emoji):
    _run(_upsert, "games_adj",
         ["id", "name", "display_name", "app_token", "emoji"],
         [game_id, name, display_name, app_token, emoji],
         ["id"])


def sync_game_singular(game_id, name, display_name, package, app_key, emoji):
    _run(_upsert, "games_singular",
         ["id", "name", "display_name", "package", "app_key", "emoji"],
         [game_id, name, display_name, package, app_key, emoji],
         ["id"])


def sync_event_af(event_id, game_id, event_name, display_name, event_type, is_purchase):
    _run(_upsert, "events_af",
         ["id", "game_id", "event_name", "display_name", "event_type", "is_purchase"],
         [event_id, game_id, event_name, display_name, event_type, is_purchase],
         ["id"])


def sync_event_singular(event_id, game_id, event_name, display_name, event_type):
    _run(_upsert, "events_singular",
         ["id", "game_id", "event_name", "display_name", "event_type"],
         [event_id, game_id, event_name, display_name, event_type],
         ["id"])


def sync_event_adj(event_id, game_id, event_name, event_token, display_name, level_value):
    _run(_upsert, "events_adj",
         ["id", "game_id", "event_name", "event_token", "display_name", "level_value"],
         [event_id, game_id, event_name, event_token, display_name, level_value],
         ["id"])


# ==================== مجموعات الجدولة ====================

def sync_sched_group(group_row: dict):
    columns = list(group_row.keys())
    values = [group_row[c] for c in columns]
    _run(_upsert, "sched_groups", columns, values, ["id"])


def sync_sched_group_delete(group_id):
    _run(_delete, "sched_groups", ["id"], [group_id])


# ==================== استعادة البيانات من Supabase عند الإقلاع ====================

def _fetch_all(table, columns):
    """يجلب كل الصفوف من جدول في Supabase (متزامن)."""
    conn = _get_conn()
    if not conn:
        return []
    cols_sql = ", ".join(columns)
    sql = f"SELECT {cols_sql} FROM {table}"
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        return rows
    except Exception as e:
        logger.warning(f"[Supabase Sync] فشل جلب البيانات من {table}: {e}")
        return []


def restore_all(sqlite_conn):
    """
    يستعيد كل البيانات من Supabase إلى SQLite المحلي عند الإقلاع.
    يُستدعى بشكل متزامن قبل بدء البوت لضمان توفر البيانات.
    لا يمسح البيانات المحلية الموجودة — يستخدم INSERT OR IGNORE.
    """
    if not _enabled:
        logger.info("[Supabase Sync] المزامنة معطلة - تخطي استعادة البيانات")
        return

    cur = sqlite_conn.cursor()
    restored = 0

    # 1) المستخدمون — جميع الأعمدة بما فيها last_use
    rows = _fetch_all("users", ["user_id", "username", "name", "last_use", "banned", "admin", "allowed", "created_at", "total_requests"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO users (user_id, username, name, last_use, banned, admin, allowed, created_at, total_requests) VALUES (?,?,?,?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 2) المستخدمون المسموحون — جميع الأعمدة
    rows = _fetch_all("allowed_users", ["user_id", "username", "name", "added_by", "added_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO allowed_users (user_id, username, name, added_by, added_date) VALUES (?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 3) منصة المستخدم
    rows = _fetch_all("user_platform", ["user_id", "platform"])
    for r in rows:
        cur.execute("INSERT OR IGNORE INTO user_platform (user_id, platform) VALUES (?,?)", r)
    restored += len(rows)

    # 4) الألعاب (af)
    rows = _fetch_all("games_af", ["id", "name", "display_name", "package", "dev_key", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_af (id, name, display_name, package, dev_key, emoji) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 4b) الألعاب (singular)
    rows = _fetch_all("games_singular", ["id", "name", "display_name", "package", "app_key", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_singular (id, name, display_name, package, app_key, emoji) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 4c) الألعاب (adj) — بدون عمود package لأن games_adj لا يحتوي عليه
    rows = _fetch_all("games_adj", ["id", "name", "display_name", "app_token", "emoji"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO games_adj (id, name, display_name, app_token, emoji) VALUES (?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 5) الأحداث (af)
    rows = _fetch_all("events_af", ["id", "game_id", "event_name", "display_name", "event_type", "is_purchase"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_af (id, game_id, event_name, display_name, event_type, is_purchase) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 5b) الأحداث (singular)
    rows = _fetch_all("events_singular", ["id", "game_id", "event_name", "display_name", "event_type"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_singular (id, game_id, event_name, display_name, event_type) VALUES (?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 5c) الأحداث (adj)
    rows = _fetch_all("events_adj", ["id", "game_id", "event_name", "event_token", "display_name", "level_value"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO events_adj (id, game_id, event_name, event_token, display_name, level_value) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 6) البروكسي — جميع الأعمدة بما فيها last_used و usage_count
    rows = _fetch_all("proxies", ["user_id", "proxy_type", "proxy_host", "proxy_port", "proxy_user", "proxy_pass", "created_date", "last_used", "usage_count"])
    for r in rows:
        cur.execute(
            "INSERT OR REPLACE INTO proxies (user_id, proxy_type, proxy_host, proxy_port, proxy_user, proxy_pass, created_date, last_used, usage_count) VALUES (?,?,?,?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 7) مزرعة المهام — جميع الأعمدة مطابقة للجدول المحلي
    farm_cols = [
        "task_name", "user_id", "platform", "game_id", "game_name",
        "start_level", "end_level", "total_days", "mode",
        "current_day", "current_level", "status", "created_date", "last_run",
        "aifa", "gaid", "uid", "af_uid", "gps_adid",
        "idfa", "idfv", "att_status", "completed_levels", "failed_attempts"
    ]
    rows = _fetch_all("farm_tasks", farm_cols)
    placeholders = ",".join(["?"] * len(farm_cols))
    cols_sql = ", ".join(farm_cols)
    for r in rows:
        cur.execute(f"INSERT OR REPLACE INTO farm_tasks ({cols_sql}) VALUES ({placeholders})", r)
    restored += len(rows)

    # 8) إحصائيات المستخدم — أعمدة مطابقة للجدول المحلي
    rows = _fetch_all("user_stats", [
        "user_id", "last_daily_reset", "daily_requests",
        "total_af_requests", "total_adj_requests", "total_singular_requests"
    ])
    for r in rows:
        cur.execute(
            "INSERT OR REPLACE INTO user_stats (user_id, last_daily_reset, daily_requests, total_af_requests, total_adj_requests, total_singular_requests) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 9) المفضلة — أعمدة مطابقة للجدول المحلي
    rows = _fetch_all("favorites", ["user_id", "platform", "game_id", "game_name", "added_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO favorites (user_id, platform, game_id, game_name, added_date) VALUES (?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 10) ملفات المعرفات — أعمدة مطابقة للجدول المحلي
    rows = _fetch_all("credential_files", ["user_id", "platform", "game_id", "filename", "data", "created_date"])
    for r in rows:
        cur.execute(
            "INSERT OR IGNORE INTO credential_files (user_id, platform, game_id, filename, data, created_date) VALUES (?,?,?,?,?,?)",
            r
        )
    restored += len(rows)

    # 11) مجموعات الجدولة — أعمدة مطابقة للجدول المحلي
    sched_cols = [
        "id", "user_id", "platform", "game_id", "game_name",
        "game_pkg", "game_key", "events_order", "interval_minutes",
        "gaid", "af_uid", "status", "created_date", "next_run"
    ]
    rows = _fetch_all("sched_groups", sched_cols)
    sched_placeholders = ",".join(["?"] * len(sched_cols))
    sched_cols_sql = ", ".join(sched_cols)
    for r in rows:
        cur.execute(
            f"INSERT OR REPLACE INTO sched_groups ({sched_cols_sql}) VALUES ({sched_placeholders})",
            r
        )
    restored += len(rows)

    sqlite_conn.commit()
    logger.info(f"[Supabase Sync] تم استعادة {restored} صف من Supabase إلى SQLite")
