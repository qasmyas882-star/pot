-- ==================================================================================
-- سكريبت SQL نهائي لإنشاء كل الجداول المطلوبة في قاعدة بيانات Supabase (Postgres)
-- شغّل هذا الملف كاملاً مرة واحدة في: Supabase Dashboard -> SQL Editor -> New query
-- ==================================================================================
-- ملاحظات مهمة:
-- 1) هذه الجداول هي نسخة مطابقة تماماً لبنية قاعدة بيانات SQLite المحلية في البوت (bot.db).
-- 2) الألعاب/الأحداث المُبرمجة في الكود (AF_GAMES / SINGULAR_GAMES / ADJ_GAMES) تبقى
--    Hardcoded في bot_file.py ولا تُمسح من Supabase — يستخدم البوت INSERT OR IGNORE.
-- 3) البوت يعمل بدون SUPABASE_DB_URL — المزامنة اختيارية تماماً.
-- 4) عند إعادة النشر (redeploy)، يستعيد البوت تلقائياً جميع البيانات من Supabase
--    (ألعاب/أحداث/مفضلة/ملفات معرفات/مجموعات جدولة) قبل بدء الاستقبال.
-- ==================================================================================

-- ==================== المستخدمون ====================
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    name TEXT,
    last_use TEXT,
    banned INTEGER DEFAULT 0,
    admin INTEGER DEFAULT 0,
    allowed INTEGER DEFAULT 0,
    created_at TEXT,
    total_requests INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS allowed_users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    name TEXT,
    added_by BIGINT,
    added_date TEXT
);

CREATE TABLE IF NOT EXISTS user_platform (
    user_id BIGINT PRIMARY KEY,
    platform TEXT DEFAULT 'android'
);

-- ==================== الألعاب المضافة يدوياً من لوحة تحكم الأدمن ====================

CREATE TABLE IF NOT EXISTS games_af (
    id BIGINT PRIMARY KEY,
    name TEXT UNIQUE,
    display_name TEXT,
    package TEXT,
    dev_key TEXT,
    emoji TEXT
);

CREATE TABLE IF NOT EXISTS games_singular (
    id BIGINT PRIMARY KEY,
    name TEXT UNIQUE,
    display_name TEXT,
    package TEXT,
    app_key TEXT,
    emoji TEXT
);

-- ملاحظة: games_adj لا يحتوي على عمود package (مختلف عن af و singular)
CREATE TABLE IF NOT EXISTS games_adj (
    id BIGINT PRIMARY KEY,
    name TEXT UNIQUE,
    display_name TEXT,
    app_token TEXT,
    emoji TEXT
);

-- ==================== الأحداث ====================

CREATE TABLE IF NOT EXISTS events_af (
    id BIGINT PRIMARY KEY,
    game_id BIGINT,
    event_name TEXT,
    display_name TEXT,
    event_type TEXT,
    is_purchase INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events_singular (
    id BIGINT PRIMARY KEY,
    game_id BIGINT,
    event_name TEXT,
    display_name TEXT,
    event_type TEXT
);

CREATE TABLE IF NOT EXISTS events_adj (
    id BIGINT PRIMARY KEY,
    game_id BIGINT,
    event_name TEXT,
    event_token TEXT,
    display_name TEXT,
    level_value INTEGER
);

-- ==================== البروكسي ====================
CREATE TABLE IF NOT EXISTS proxies (
    id SERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE,
    proxy_type TEXT,
    proxy_host TEXT,
    proxy_port INTEGER,
    proxy_user TEXT,
    proxy_pass TEXT,
    created_date TEXT,
    last_used TEXT,
    usage_count INTEGER DEFAULT 0
);

-- ==================== مهام المزرعة ====================
-- الأعمدة مطابقة تماماً للجدول المحلي في bot_file.py
CREATE TABLE IF NOT EXISTS farm_tasks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    task_name TEXT UNIQUE,
    platform TEXT,
    game_id INTEGER,
    game_name TEXT,
    start_level INTEGER,
    end_level INTEGER,
    total_days INTEGER,
    mode TEXT,
    current_day INTEGER,
    current_level INTEGER,
    status TEXT,
    created_date TEXT,
    last_run TEXT,
    aifa TEXT,
    gaid TEXT,
    uid TEXT,
    af_uid TEXT,
    gps_adid TEXT,
    idfa TEXT,
    idfv TEXT,
    att_status INTEGER,
    completed_levels INTEGER DEFAULT 0,
    failed_attempts INTEGER DEFAULT 0
);

-- ==================== إحصائيات المستخدم ====================
-- الأعمدة مطابقة تماماً للجدول المحلي في bot_file.py
CREATE TABLE IF NOT EXISTS user_stats (
    user_id BIGINT PRIMARY KEY,
    last_daily_reset TEXT,
    daily_requests INTEGER DEFAULT 0,
    total_af_requests INTEGER DEFAULT 0,
    total_adj_requests INTEGER DEFAULT 0,
    total_singular_requests INTEGER DEFAULT 0
);

-- ==================== المفضلة ====================
-- الأعمدة مطابقة تماماً للجدول المحلي في bot_file.py
CREATE TABLE IF NOT EXISTS favorites (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    platform TEXT,
    game_id INTEGER,
    game_name TEXT,
    added_date TEXT,
    UNIQUE(user_id, platform, game_id)
);

-- ==================== ملفات المعرفات المحفوظة ====================
-- الأعمدة مطابقة تماماً للجدول المحلي في bot_file.py
CREATE TABLE IF NOT EXISTS credential_files (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    platform TEXT,
    game_id INTEGER,
    filename TEXT,
    data TEXT,
    created_date TEXT,
    UNIQUE(user_id, platform, game_id, filename)
);

-- ==================== مجموعات الجدولة ====================
-- الأعمدة مطابقة تماماً للجدول المحلي في bot_file.py
CREATE TABLE IF NOT EXISTS sched_groups (
    id BIGINT PRIMARY KEY,
    user_id BIGINT,
    platform TEXT,
    game_id INTEGER,
    game_name TEXT,
    game_pkg TEXT,
    game_key TEXT,
    events_order TEXT,
    interval_minutes INTEGER,
    gaid TEXT,
    af_uid TEXT,
    status TEXT DEFAULT 'active',
    created_date TEXT,
    next_run TEXT
);

-- ==================== فهارس لتحسين الأداء ====================
CREATE INDEX IF NOT EXISTS idx_users_allowed ON users(allowed);
CREATE INDEX IF NOT EXISTS idx_users_banned ON users(banned);
CREATE INDEX IF NOT EXISTS idx_farm_tasks_user ON farm_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_farm_tasks_status ON farm_tasks(status);
CREATE INDEX IF NOT EXISTS idx_events_af_game ON events_af(game_id);
CREATE INDEX IF NOT EXISTS idx_events_adj_game ON events_adj(game_id);
CREATE INDEX IF NOT EXISTS idx_events_singular_game ON events_singular(game_id);
CREATE INDEX IF NOT EXISTS idx_proxies_user ON proxies(user_id);
CREATE INDEX IF NOT EXISTS idx_user_platform ON user_platform(user_id);
CREATE INDEX IF NOT EXISTS idx_favorites_user ON favorites(user_id);
CREATE INDEX IF NOT EXISTS idx_credential_files_lookup ON credential_files(user_id, platform, game_id);
CREATE INDEX IF NOT EXISTS idx_sched_groups_user ON sched_groups(user_id);
CREATE INDEX IF NOT EXISTS idx_sched_groups_status ON sched_groups(status);

-- ==================== جداول نظام الاشتراكات (إضافة جديدة) ====================

CREATE TABLE IF NOT EXISTS subscriptions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT UNIQUE,
    plan TEXT,
    start_date TEXT,
    end_date TEXT,
    status TEXT DEFAULT 'active',
    approved_by BIGINT,
    approved_at TEXT
);

CREATE TABLE IF NOT EXISTS subscription_requests (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT,
    username TEXT,
    name TEXT,
    plan TEXT,
    plan_price TEXT,
    plan_days INTEGER,
    payment_method TEXT,
    proof_file_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at TEXT,
    admin_msg_id BIGINT,
    admin_chat_id BIGINT
);

CREATE TABLE IF NOT EXISTS payment_methods (
    id BIGSERIAL PRIMARY KEY,
    method_key TEXT UNIQUE,
    display_name TEXT,
    address TEXT,
    instructions TEXT,
    is_active INTEGER DEFAULT 1
);

-- بيانات افتراضية لطرق الدفع
INSERT INTO payment_methods (method_key, display_name, address, instructions, is_active)
VALUES
  ('sham_cash',     'شام كاش',     '', 'أرسل المبلغ على الرقم الموضح وأرسل صورة الإيصال.', 1),
  ('syriatel_cash', 'سيريتيل كاش', '', 'أرسل المبلغ على الرقم الموضح وأرسل صورة الإيصال.', 1),
  ('usdt_bep20',    'USDT BEP20',  '', 'أرسل المبلغ على العنوان الموضح وأرسل صورة الإيصال.', 1)
ON CONFLICT (method_key) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_subscriptions_user ON subscriptions(user_id);
CREATE INDEX IF NOT EXISTS idx_subscriptions_status ON subscriptions(status);
CREATE INDEX IF NOT EXISTS idx_sub_requests_user ON subscription_requests(user_id);
CREATE INDEX IF NOT EXISTS idx_sub_requests_status ON subscription_requests(status);
