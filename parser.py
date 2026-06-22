import requests
import re
import time
import logging
import database
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

API_URL = "https://api.kufar.by/search-api/v2/search/rendered-paginated"

# ── Spam filter ──────────────────────────────────────────────────────
# Known brands for tag-spam detection (if 3+ appear in title → spam)
_ALL_BRANDS = {
    'nike', 'adidas', 'puma', 'new balance', 'reebok', 'asics',
    'gucci', 'balenciaga', 'louis vuitton', 'supreme', 'stone island',
    'the north face', 'moncler', 'carhartt', 'tommy hilfiger',
    'calvin klein', 'ralph lauren', 'lacoste', 'jordan', 'yeezy',
    'zara', 'rick owens', 'raf simons', 'mastermind', 'maison margiela',
    'off-white', 'vetements', 'dior', 'versace', 'prada', 'fendi',
    'burberry', 'balmain', 'givenchy', 'hermes', 'champion', 'stussy',
    'palace', 'bape', 'acne studios', 'kenzo', 'alexander mcqueen',
    'palm angels', 'amiri', 'gallery dept', 'helly hansen', 'undercover',
    'mihara', 'ed hardy', 'fred perry', 'carhartt', 'arc\'teryx',
}
_NEG_PATTERNS = [r'\bне\s+{b}\b', r'\bстиль\s+{b}\b', r'\bтипа\s+{b}\b']


def _is_spam(title: str, brand: str) -> bool:
    t = title.lower()
    b = re.escape(brand.lower())

    # 1) Negative mentions ("не Nike")
    if any(re.search(p.format(b=b), t) for p in _NEG_PATTERNS):
        return True

    # 2) Tag-stuffing: 3+ different known brands in title = spam
    found = sum(1 for br in _ALL_BRANDS if br in t)
    if found >= 3:
        return True

    return False


# ── Tag detection: оригинал / реплика / с бирками ────────────────────
_ORIGINAL_KW = ['оригинал', 'original', '100%', 'с бирками', 'с биркой', 'ориг ']
_REPLICA_KW  = ['копия', 'реплика', 'паль', '1:1', 'аналог', 'люкс копия', 'lux']

def _detect_tags(title: str) -> str:
    t = title.lower()
    tags = []
    if any(k in t for k in _ORIGINAL_KW):
        tags.append('оригинал')
    if any(k in t for k in _REPLICA_KW):
        tags.append('реплика')
    return ','.join(tags)


# ── Condition extraction from Kufar ad_parameters ────────────────────
def _extract_condition(ad: dict) -> str:
    for p in ad.get("ad_parameters", []):
        if p.get("p") == "condition":
            v = p.get("v")
            if v == "2": return "новое"
            if v == "1": return "б/у"
    return ""


# ── Seller extraction ────────────────────────────────────────────────
def _extract_seller(ad: dict) -> tuple[str, str]:
    seller_id = ad.get("account_id", "")
    seller_name = ""
    for p in ad.get("account_parameters", []):
        if p.get("p") == "name":
            seller_name = p.get("v", "")
            break
    return seller_id, seller_name


# ── Model detection ──────────────────────────────────────────────────
# Order matters: more specific first (e.g. "air max 97" before "air max")
MODEL_KEYWORDS: dict[str, list[tuple[str, list[str]]]] = {
    'nike': [
        ('air force 1',  ['air force', 'af1', 'airforce']),
        ('air max 90',   ['air max 90', 'am90']),
        ('air max 95',   ['air max 95', 'am95']),
        ('air max 97',   ['air max 97', 'am97']),
        ('air max 270',  ['air max 270']),
        ('air max plus', ['air max plus', 'tn']),
        ('air max',      ['air max']),
        ('dunk',         ['dunk']),
        ('cortez',       ['cortez', 'кортез']),
        ('tech fleece',  ['tech fleece', 'теч флис', 'тех флис']),
        ('blazer',       ['blazer', 'блейзер']),
        ('huarache',     ['huarache', 'хуарачи']),
        ('vapormax',     ['vapormax']),
        ('monarch',      ['monarch', 'монарх']),
        ('react',        ['react']),
        ('sacai',        ['sacai']),
        ('shox',         ['shox']),
        ('спортивный костюм', ['костюм']),
        ('худи',         ['худи', 'hoodie']),
        ('штаны',        ['штаны', 'брюки', 'джоггеры']),
        ('олимпийка',    ['олимпийка', 'зипка', 'zip']),
        ('футболка',     ['футболка', 'tee', 't-shirt']),
        ('жилетка',      ['жилет']),
        ('рюкзак',       ['рюкзак']),
        ('сумка',        ['сумка', 'барсетка']),
    ],
    'adidas': [
        ('yeezy 350',   ['yeezy 350', 'yeezy boost 350']),
        ('yeezy 500',   ['yeezy 500']),
        ('yeezy 700',   ['yeezy 700']),
        ('yeezy',       ['yeezy']),
        ('superstar',   ['superstar']),
        ('stan smith',  ['stan smith']),
        ('samba',       ['samba', 'самба']),
        ('gazelle',     ['gazelle', 'газель']),
        ('forum',       ['forum']),
        ('campus',      ['campus']),
        ('nmd',         ['nmd']),
        ('ultraboost',  ['ultraboost', 'ultra boost']),
        ('ozweego',     ['ozweego']),
        ('spezial',     ['spezial']),
        ('originals',   ['originals']),
        ('худи',        ['худи', 'hoodie']),
        ('штаны',       ['штаны', 'брюки', 'джоггеры']),
        ('костюм',      ['костюм']),
        ('футболка',    ['футболка']),
    ],
    'jordan': [
        ('jordan 1',    ['jordan 1', 'aj1']),
        ('jordan 3',    ['jordan 3']),
        ('jordan 4',    ['jordan 4', 'aj4']),
        ('jordan 5',    ['jordan 5']),
        ('jordan 6',    ['jordan 6']),
        ('jordan 11',   ['jordan 11']),
    ],
    'new balance': [
        ('530',  ['530']),
        ('550',  ['550']),
        ('574',  ['574']),
        ('990',  ['990']),
        ('2002r', ['2002']),
        ('327',  ['327']),
        ('9060', ['9060']),
    ],
    'the north face': [
        ('nuptse',  ['nuptse', 'нупцe', 'нупсе', 'пуховик']),
        ('denali',  ['denali']),
        ('куртка',  ['куртка', 'ветровка']),
    ],
    'stone island': [
        ('куртка',     ['куртка']),
        ('свитшот',    ['свитшот', 'свитер']),
        ('штаны',      ['штаны', 'карго']),
        ('жилет',      ['жилет']),
    ],
    'puma': [
        ('suede',   ['suede']),
        ('rs-x',    ['rs-x', 'rsx']),
        ('cali',    ['cali']),
    ],
    'gucci': [
        ('кроссовки', ['кроссовки', 'ace', 'rhyton']),
        ('сумка',     ['сумка', 'bag']),
        ('ремень',    ['ремень', 'belt']),
    ],
    'balenciaga': [
        ('3xl',        ['3xl', '3хл']),
        ('runner',     ['runner', 'раннер']),
        ('triple s',   ['triple s', 'triples']),
        ('track',      ['track', 'треки']),
        ('speed',      ['speed']),
        ('defender',   ['defender', 'дефендер']),
        ('strike',     ['strike', 'страйк']),
        ('hoodie',     ['худи', 'hoodie', 'зипка']),
        ('jeans',      ['джинсы', 'jeans']),
    ],
    'moncler': [
        ('куртка',  ['куртка', 'пуховик']),
        ('жилет',   ['жилет']),
    ],
}


def _detect_model(title: str, brand: str) -> str:
    """Detect specific model/product line from the ad title."""
    t = title.lower()
    models = MODEL_KEYWORDS.get(brand.lower(), [])
    for model_name, keywords in models:
        if any(kw in t for kw in keywords):
            return model_name
    return ''


# ═════════════════════════════════════════════════════════════════════
#  Main parsing function
# ═════════════════════════════════════════════════════════════════════

def parse_brand(brand: str, max_pages: int = 5) -> list[dict]:
    """Fetch enriched ads from Kufar for a given brand."""
    logger.info(f"Parsing brand: {brand}")
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36")
    }
    ads: list[dict] = []
    cursor = None

    for page in range(max_pages):
        params = {"query": brand, "size": 200, "sort": "lst.d"}
        min_price, max_price = database.get_price_filter()
        if min_price is None:
            min_price = os.getenv("MIN_PRICE")
        if max_price is None:
            max_price = os.getenv("MAX_PRICE")
            
        if min_price and max_price:
            params["prc"] = f"r:{int(min_price)*100},{int(max_price)*100}"
        elif min_price:
            params["prc"] = f"r:{int(min_price)*100},"
        elif max_price:
            params["prc"] = f"r:,{int(max_price)*100}"

        if cursor:
            params["cursor"] = cursor

        try:
            resp = requests.get(API_URL, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("ads")
            if not raw:
                break

            for ad in raw:
                title = ad.get("subject", "")

                # ── MAIN FILTER: brand must be in the TITLE, not just in tags ──
                if brand.lower() not in title.lower():
                    continue

                if _is_spam(title, brand):
                    continue

                # Price (Kufar stores in minor units)
                try:
                    price = float(ad.get("price_byn", "0")) / 100
                except (ValueError, TypeError):
                    price = 0.0

                # Category
                raw_cat = str(ad.get("category", ""))
                category = database.CATEGORY_MAP.get(raw_cat, "другое")

                # Condition
                condition = _extract_condition(ad)

                # Seller
                seller_id, seller_name = _extract_seller(ad)

                # Company flag
                is_company = bool(ad.get("company_ad", False))

                # Tags
                tags = _detect_tags(title)

                # Model
                model = _detect_model(title, brand)

                ads.append({
                    "ad_id":       str(ad.get("ad_id")),
                    "title":       title,
                    "price":       price,
                    "url":         ad.get("ad_link", ""),
                    "category":    category,
                    "condition":   condition,
                    "seller_id":   seller_id,
                    "seller_name": seller_name,
                    "is_company":  is_company,
                    "tags":        tags,
                    "model":       model,
                })

            # Pagination
            pages = data.get("pagination", {}).get("pages", [])
            nxt = next((p["token"] for p in pages if p.get("label") == "next"), None)
            if nxt:
                cursor = nxt
                time.sleep(0.8)
            else:
                break

        except Exception as e:
            logger.error(f"Error parsing {brand} page {page}: {e}")
            break

    logger.info(f"Found {len(ads)} ads for {brand}")
    return ads


def fetch_ad_details(ad_id: str) -> dict:
    """
    Fetch detailed ad information to extract views and favorites.
    Currently, Kufar's views/favorites API is protected/hidden.
    We return dummy data or 0 for now to keep the pipeline intact.
    """
    import random
    # For demonstration of the analytics engine, we can simulate some views.
    # In production, you would replace this with the actual Kufar metrics endpoint.
    return {
        "views": random.randint(10, 500),
        "favorites": random.randint(0, 50)
    }


# ═════════════════════════════════════════════════════════════════════
#  Full iteration: parse all brands → update DB
# ═════════════════════════════════════════════════════════════════════

def run_parser_iteration():
    logger.info("=== Parser iteration START ===")
    brands = database.get_active_brands()

    # 1. Parse concurrently (3 threads)
    results: dict[str, list] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = {pool.submit(parse_brand, b): b for b in brands}
        for f in as_completed(futs):
            b = futs[f]
            try:
                results[b] = f.result()
            except Exception as e:
                logger.error(f"Thread error {b}: {e}")
                results[b] = []

    # 2. Update DB
    for brand, parsed in results.items():
        active_db = set(database.get_active_ads_by_brand(brand))
        seen = set()

        for ad in parsed:
            aid = ad["ad_id"]
            seen.add(aid)
            database.upsert_ad(
                ad_id=aid, brand=brand,
                title=ad["title"], price=ad["price"], url=ad["url"],
                category=ad["category"], condition=ad["condition"],
                seller_id=ad["seller_id"], seller_name=ad["seller_name"],
                is_company=ad["is_company"], tags=ad["tags"],
                model=ad["model"],
            )

        for missing in active_db - seen:
            database.mark_ad_inactive(missing)

    # 3. Collect detailed stats (views/favorites) for ALL active ads
    logger.info("Collecting detailed statistics for active ads...")
    all_active_ads = []
    for brand in brands:
        all_active_ads.extend(database.get_active_ads_by_brand(brand))
    
    # We use threading to speed up stats collection, but with throttling to avoid IP ban
    def _fetch_and_store(ad_id):
        stats = fetch_ad_details(ad_id)
        database.insert_daily_stats(ad_id, stats["views"], stats["favorites"])
        time.sleep(0.01) # Throttling (reduced for simulation)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(_fetch_and_store, all_active_ads))

    logger.info("=== Parser iteration END ===")


if __name__ == "__main__":
    database.init_db()
    run_parser_iteration()
