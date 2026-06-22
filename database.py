import sqlite3
import datetime
import os
import json

DB_PATH = os.path.join(os.path.dirname(__file__), 'kufar_data.db')

# ── Kufar category codes → simplified ────────────────────────────────
CATEGORY_MAP = {
    "19010": "одежда",      # Мужская одежда
    "8010":  "одежда",      # Женская одежда
    "6010":  "одежда",      # Детская одежда
    "19020": "обувь",       # Мужская обувь
    "8100":  "обувь",       # Женская обувь
    "6020":  "обувь",       # Детская обувь
    "19030": "аксессуары",  # Мужские аксессуары
    "8200":  "аксессуары",  # Женские аксессуары
    "6030":  "аксессуары",  # Детские аксессуары
}

# ── DB helpers ───────────────────────────────────────────────────────

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    conn = _conn()
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS brands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        is_active BOOLEAN DEFAULT 1,
        purchase_price REAL DEFAULT 0
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS ads (
        ad_id        TEXT PRIMARY KEY,
        brand        TEXT NOT NULL,
        title        TEXT,
        price        REAL,
        url          TEXT,
        category     TEXT DEFAULT '',
        condition    TEXT DEFAULT '',
        seller_id    TEXT DEFAULT '',
        seller_name  TEXT DEFAULT '',
        is_company   BOOLEAN DEFAULT 0,
        tags         TEXT DEFAULT '',
        model        TEXT DEFAULT '',
        first_seen   TIMESTAMP NOT NULL,
        last_seen    TIMESTAMP NOT NULL,
        status       TEXT DEFAULT 'active'
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        chat_id INTEGER PRIMARY KEY,
        notifications_enabled BOOLEAN DEFAULT 1
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS daily_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ad_id TEXT NOT NULL,
        date DATE NOT NULL,
        views INTEGER DEFAULT 0,
        favorites INTEGER DEFAULT 0,
        UNIQUE(ad_id, date)
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS costs (
        brand TEXT,
        model TEXT,
        price REAL,
        PRIMARY KEY (brand, model)
    )''')

    conn.commit()

    # ── Migration: add columns that might be missing ──
    for stmt in [
        "ALTER TABLE ads ADD COLUMN category    TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN condition    TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN seller_id    TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN seller_name  TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN is_company   BOOLEAN DEFAULT 0",
        "ALTER TABLE ads ADD COLUMN tags         TEXT DEFAULT ''",
        "ALTER TABLE ads ADD COLUMN model        TEXT DEFAULT ''",
        "ALTER TABLE brands ADD COLUMN purchase_price REAL DEFAULT 0",
    ]:
        try:
            cur.execute(stmt)
            conn.commit()
        except sqlite3.OperationalError:
            pass

    # ── Default brands ──
    cur.execute("SELECT count(*) FROM brands")
    if cur.fetchone()[0] == 0:
        for b in [
            # Спорт
            'nike', 'adidas', 'puma', 'new balance', 'reebok',
            # Люкс / стритвир
            'gucci', 'balenciaga', 'louis vuitton', 'supreme', 'stone island',
            'the north face', 'moncler', 'carhartt',
            # Премиум масс-маркет
            'tommy hilfiger', 'calvin klein', 'ralph lauren', 'lacoste',
            # Обувь
            'jordan', 'yeezy',
            # Масс-маркет
            'zara',
        ]:
            cur.execute("INSERT OR IGNORE INTO brands (name) VALUES (?)", (b,))
        conn.commit()

    conn.close()


# ═════════════════════════════════════════════════════════════════════
#  Users
# ═════════════════════════════════════════════════════════════════════

def register_user(chat_id):
    conn = _conn()
    conn.execute("INSERT OR IGNORE INTO users (chat_id) VALUES (?)", (chat_id,))
    conn.commit()
    conn.close()

def get_notification_users():
    conn = _conn()
    ids = [r[0] for r in conn.execute(
        "SELECT chat_id FROM users WHERE notifications_enabled=1").fetchall()]
    conn.close()
    return ids


# ═════════════════════════════════════════════════════════════════════
#  Brands
# ═════════════════════════════════════════════════════════════════════

def add_brand(name):
    conn = _conn()
    try:
        conn.execute("INSERT INTO brands (name) VALUES (?)", (name.lower(),))
        conn.commit(); return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def remove_brand(name):
    conn = _conn()
    conn.execute("DELETE FROM brands WHERE name=?", (name.lower(),))
    conn.commit(); conn.close()

def get_active_brands():
    conn = _conn()
    out = [r[0] for r in conn.execute(
        "SELECT name FROM brands WHERE is_active=1").fetchall()]
    conn.close(); return out

def set_purchase_price(brand: str, price: float, model: str = ''):
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO costs (brand, model, price) VALUES (?, ?, ?)",
        (brand.lower(), model.lower(), price)
    )
    conn.commit()
    conn.close()

def get_purchase_price(brand, model=''):
    """Get purchase price for brand+model. Falls back to brand default."""
    conn = _conn()
    # Try exact match first
    row = conn.execute(
        "SELECT price FROM costs WHERE brand=? AND model=?",
        (brand.lower(), model.lower())).fetchone()
    if row:
        conn.close(); return row[0]
    # Fallback to brand default (model='')
    row = conn.execute(
        "SELECT price FROM costs WHERE brand=? AND model=''",
        (brand.lower(),)).fetchone()
    conn.close()
    return row[0] if row else 0

def get_all_costs():
    conn = _conn()
    rows = conn.execute("SELECT brand, model, price FROM costs").fetchall()
    conn.close()
    return [{'brand': r[0], 'model': r[1], 'price': r[2]} for r in rows]


# ═════════════════════════════════════════════════════════════════════
#  Ads CRUD
# ═════════════════════════════════════════════════════════════════════

def upsert_ad(*, ad_id, brand, title, price, url,
              category='', condition='', seller_id='',
              seller_name='', is_company=False, tags='', model=''):
    conn = _conn()
    now = datetime.datetime.now()
    exists = conn.execute("SELECT 1 FROM ads WHERE ad_id=?", (ad_id,)).fetchone()

    if exists:
        conn.execute('''UPDATE ads SET last_seen=?, price=?, category=?,
                        condition=?, seller_id=?, seller_name=?,
                        is_company=?, tags=?, model=?, status='active'
                        WHERE ad_id=?''',
                     (now, price, category, condition, seller_id,
                      seller_name, is_company, tags, model, ad_id))
    else:
        conn.execute('''INSERT INTO ads
            (ad_id,brand,title,price,url,category,condition,
             seller_id,seller_name,is_company,tags,model,first_seen,last_seen,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'active')''',
            (ad_id, brand, title, price, url, category, condition,
             seller_id, seller_name, is_company, tags, model, now, now))

    conn.commit(); conn.close()

def get_active_ads_by_brand(brand):
    conn = _conn()
    ids = [r[0] for r in conn.execute(
        "SELECT ad_id FROM ads WHERE brand=? AND status='active'",
        (brand,)).fetchall()]
    conn.close(); return ids

def mark_ad_inactive(ad_id):
    conn = _conn()
    conn.execute("UPDATE ads SET status='inactive', last_seen=? WHERE ad_id=?",
                 (datetime.datetime.now(), ad_id))
    conn.commit(); conn.close()

def insert_daily_stats(ad_id, views, favorites):
    conn = _conn()
    today = datetime.date.today().isoformat()
    conn.execute('''
        INSERT OR REPLACE INTO daily_stats (ad_id, date, views, favorites)
        VALUES (?, ?, ?, ?)
    ''', (ad_id, today, views, favorites))
    conn.commit()
    conn.close()


# ═════════════════════════════════════════════════════════════════════
#  Analytics: Supply / Demand
# ═════════════════════════════════════════════════════════════════════

def get_analytics(days=7, category_filter=None):
    conn = _conn()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    cat = " AND category=?" if category_filter else ""
    p_act = [category_filter] if category_filter else []
    p_sold = [cutoff] + p_act

    active = {r[0]: r[1] for r in conn.execute(
        f"SELECT brand, count(*) FROM ads WHERE status='active'{cat} GROUP BY brand",
        p_act).fetchall()}

    sold = {r[0]: (r[1], r[2]) for r in conn.execute(
        f"""SELECT brand, count(*),
            avg(julianday(last_seen)-julianday(first_seen))
            FROM ads WHERE status='inactive' AND last_seen>=?{cat}
            GROUP BY brand""", p_sold).fetchall()}

    conn.close()

    out = []
    for b in set(active) | set(sold):
        sc, ad = sold.get(b, (0, 0))
        out.append({
            'brand': b.capitalize(), 'brand_lower': b,
            'sold_count': sc,
            'avg_days': round(ad, 1) if ad else 0,
            'active_count': active.get(b, 0),
        })
    out.sort(key=lambda x: (x['avg_days'] == 0, x['avg_days'], -x['active_count']))
    return out


# ═════════════════════════════════════════════════════════════════════
#  Analytics: Models
# ═════════════════════════════════════════════════════════════════════

def get_models_stats(brand):
    """Stats grouped by specific models for a brand."""
    conn = _conn()
    b = brand.lower()

    active = {r[0]: r[1] for r in conn.execute(
        "SELECT model, count(*) FROM ads WHERE status='active' AND brand=? AND model!='' GROUP BY model",
        (b,)).fetchall()}

    cutoff = datetime.datetime.now() - datetime.timedelta(days=7)
    sold = {r[0]: r[1] for r in conn.execute(
        "SELECT model, count(*) FROM ads WHERE status='inactive' AND brand=? AND model!='' AND last_seen>=? GROUP BY model",
        (b, cutoff)).fetchall()}

    conn.close()

    out = []
    for m in set(active) | set(sold):
        out.append({
            'model': m,
            'active_count': active.get(m, 0),
            'sold_count': sold.get(m, 0)
        })
    out.sort(key=lambda x: (-x['sold_count'], -x['active_count']))
    return out


# ═════════════════════════════════════════════════════════════════════
#  Prices & Costs
# ═════════════════════════════════════════════════════════════════════

def get_price_stats(brand=None, model_filter=None):
    conn = _conn()
    q = """SELECT brand, model, count(*) as c, 
           min(price), avg(price), max(price) 
           FROM ads WHERE status='active' AND price>0"""
    params = []
    if brand:
        q += " AND brand=?"
        params.append(brand.lower())
    if model_filter:
        q += " AND model=?"
        params.append(model_filter.lower())
        
    q += " GROUP BY brand, model HAVING c >= 1 ORDER BY c DESC LIMIT 20"
    
    rows = conn.execute(q, params).fetchall()
    conn.close()
    
    return [{
        'brand': r[0].capitalize(),
        'brand_lower': r[0],
        'model': r[1].capitalize() if r[1] else "",
        'total': r[2],
        'min_price': r[3],
        'avg_price': r[4],
        'max_price': r[5]
    } for r in rows]

def get_min_max_ads(brand, model=''):
    conn = _conn()
    min_ad = conn.execute("SELECT price, url, title FROM ads WHERE brand=? AND model=? AND status='active' AND price>0 ORDER BY price ASC LIMIT 1", (brand.lower(), model.lower())).fetchone()
    max_ad = conn.execute("SELECT price, url, title FROM ads WHERE brand=? AND model=? AND status='active' AND price>0 ORDER BY price DESC LIMIT 1", (brand.lower(), model.lower())).fetchone()
    conn.close()
    return min_ad, max_ad

def get_most_purchased_model(brand):
    conn = _conn()
    top = conn.execute("SELECT model, count(*) as c FROM ads WHERE brand=? AND status='inactive' AND model!='' GROUP BY model ORDER BY c DESC LIMIT 1", (brand.lower(),)).fetchone()
    conn.close()
    return top[0] if top else None


# ═════════════════════════════════════════════════════════════════════
#  Analytics: Market breakdown (condition, tags, sellers)
# ═════════════════════════════════════════════════════════════════════

def get_market_analysis(brand):
    """Full market snapshot for a brand."""
    conn = _conn()
    b = brand.lower()

    total = conn.execute(
        "SELECT count(*) FROM ads WHERE brand=? AND status='active'", (b,)).fetchone()[0]

    # By category
    cats = {r[0]: r[1] for r in conn.execute(
        "SELECT category, count(*) FROM ads WHERE brand=? AND status='active' GROUP BY category",
        (b,)).fetchall()}

    # By condition
    conds = {r[0]: r[1] for r in conn.execute(
        "SELECT condition, count(*) FROM ads WHERE brand=? AND status='active' GROUP BY condition",
        (b,)).fetchall()}

    # By tags (original vs replica)
    originals = conn.execute(
        "SELECT count(*) FROM ads WHERE brand=? AND status='active' AND tags LIKE '%оригинал%'",
        (b,)).fetchone()[0]
    replicas = conn.execute(
        "SELECT count(*) FROM ads WHERE brand=? AND status='active' AND tags LIKE '%реплика%'",
        (b,)).fetchone()[0]

    # Sellers: private vs resellers (5+ ads)
    sellers = conn.execute(
        """SELECT seller_id, seller_name, is_company, count(*) as cnt
           FROM ads WHERE brand=? AND status='active' AND seller_id!=''
           GROUP BY seller_id ORDER BY cnt DESC""", (b,)).fetchall()

    reseller_count = sum(1 for s in sellers if s[3] >= 5)
    private_count = len(sellers) - reseller_count

    conn.close()

    return {
        'total': total,
        'categories': dict(cats),
        'conditions': dict(conds),
        'originals': originals,
        'replicas': replicas,
        'unmarked': total - originals - replicas,
        'reseller_count': reseller_count,
        'private_count': private_count,
        'top_sellers': [{'name': s[1], 'is_company': s[2], 'count': s[3]}
                        for s in sellers[:10]],
    }


def get_top_sellers(brand=None, min_ads=3):
    """Top sellers across all brands or for a specific brand."""
    conn = _conn()
    if brand:
        rows = conn.execute(
            """SELECT seller_id, seller_name, is_company, count(*) as cnt
               FROM ads WHERE brand=? AND status='active' AND seller_id!=''
               GROUP BY seller_id HAVING cnt>=? ORDER BY cnt DESC LIMIT 15""",
            (brand.lower(), min_ads)).fetchall()
    else:
        rows = conn.execute(
            """SELECT seller_id, seller_name, is_company, count(*) as cnt
               FROM ads WHERE status='active' AND seller_id!=''
               GROUP BY seller_id HAVING cnt>=? ORDER BY cnt DESC LIMIT 15""",
            (min_ads,)).fetchall()

    res = []
    for r in rows:
        seller_id = r[0]
        
        # Get top item for this seller
        top_item_row = conn.execute("""
            SELECT brand, model, count(*) as item_count 
            FROM ads 
            WHERE seller_id=? 
            GROUP BY brand, model 
            ORDER BY item_count DESC 
            LIMIT 1
        """, (seller_id,)).fetchone()
        
        top_item_str = "Разное"
        if top_item_row:
            b, m, c = top_item_row
            b = b.capitalize() if b else ""
            m = m.capitalize() if m else ""
            if b and m:
                top_item_str = f"{b} {m}"
            elif b:
                top_item_str = f"{b}"
                
        res.append({
            'seller_id': seller_id,
            'name': r[1] or "Пользователь",
            'is_company': r[2],
            'count': r[3],
            'top_item': top_item_str
        })
        
    conn.close()
    return res


def get_fastest_selling(days=7, limit=10):
    """Models with shortest average time-to-sell."""
    conn = _conn()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    rows = conn.execute("""
        SELECT brand, model, count(*) as sold,
               avg(julianday(last_seen)-julianday(first_seen)) as avg_d
        FROM ads WHERE status='inactive' AND last_seen>=? AND model!=''
        GROUP BY brand, model HAVING sold>=1
        ORDER BY avg_d ASC LIMIT ?
    """, (cutoff, limit)).fetchall()
    conn.close()
    return [{'brand': r[0].capitalize(), 'model': r[1].capitalize(), 'sold': r[2],
             'avg_days': round(r[3], 1) if r[3] else 0} for r in rows]


# ═════════════════════════════════════════════════════════════════════
#  Deficit detection
# ═════════════════════════════════════════════════════════════════════

def get_deficit_alerts(sold_days=3, sold_threshold=2, active_threshold=10):
    """Detect deficit on specific models."""
    conn = _conn()
    cutoff = datetime.datetime.now() - datetime.timedelta(days=sold_days)
    sold = { (r[0], r[1]): r[2] for r in conn.execute(
        "SELECT brand, model, count(*) FROM ads WHERE status='inactive' AND last_seen>=? AND model!='' GROUP BY brand, model HAVING count(*)>=?",
        (cutoff, sold_threshold)).fetchall()}
    active = { (r[0], r[1]): r[2] for r in conn.execute(
        "SELECT brand, model, count(*) FROM ads WHERE status='active' AND model!='' GROUP BY brand, model").fetchall()}

    conn.close()

    alerts = []
    for (b, m), sc in sold.items():
        # Sanity: if 50+ "sold" in 3 days, it's a data artifact
        if sc > 50:
            continue
        ac = active.get((b, m), 0)
        if ac < active_threshold or sc > ac:
            alerts.append({'brand': b.capitalize(), 'model': m.capitalize(), 'sold_count': sc,
                           'active_count': ac, 'sold_days': sold_days})
    return alerts
