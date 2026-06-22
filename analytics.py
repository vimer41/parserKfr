import sqlite3
import pandas as pd
import datetime
import os
import database

DB_PATH = database.DB_PATH

def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def generate_analytics_data():
    conn = _conn()
    
    ads_query = "SELECT ad_id, title, url, price, brand, first_seen FROM ads WHERE status='active'"
    ads = conn.execute(ads_query).fetchall()
    
    golden_vein_data = []
    hidden_potential_data = []
    
    now = datetime.datetime.now()
    
    for ad in ads:
        ad_id = ad["ad_id"]
        stats = conn.execute("SELECT views, favorites, date FROM daily_stats WHERE ad_id=? ORDER BY date DESC", (ad_id,)).fetchall()
        if not stats:
            continue
            
        latest_views = stats[0]["views"]
        latest_favs = stats[0]["favorites"]
        
        old_views = latest_views
        if len(stats) > 2:
            old_views = stats[2]["views"] # approx 2 days ago
            
        try:
            first_seen = datetime.datetime.fromisoformat(ad["first_seen"])
        except ValueError:
            # fallback if stored improperly
            first_seen = now - datetime.timedelta(days=1)
            
        days_alive = max(1, (now - first_seen).days)
        
        views_per_day = latest_views / days_alive
        growth_rate = (latest_views - old_views) / 2
        fav_rate = (latest_favs / latest_views * 100) if latest_views > 0 else 0
        
        item = {
            "ID": ad_id,
            "Бренд": ad["brand"].capitalize(),
            "Название": ad["title"],
            "Цена (BYN)": ad["price"],
            "Дней висит": days_alive,
            "Просмотры": latest_views,
            "Избранное": latest_favs,
            "Просмотров/день": round(views_per_day, 1),
            "Импульс (рост)": round(growth_rate, 1),
            "Конверсия в желание (%)": round(fav_rate, 1),
            "Ссылка": ad["url"]
        }
        
        if fav_rate >= 10:
            golden_vein_data.append(item)
            
        if fav_rate >= 10 and days_alive >= 14:
            hidden_potential_data.append(item)
            
    golden_vein_data.sort(key=lambda x: x["Импульс (рост)"], reverse=True)
    golden_vein_data = golden_vein_data[:20]
    
    model_query = """
    SELECT brand, model,
           COUNT(*) as sold_count,
           AVG(julianday(last_seen) - julianday(first_seen)) as avg_days_to_sell,
           AVG(price) as avg_price
    FROM ads 
    WHERE status='inactive' AND model != ''
    GROUP BY brand, model
    ORDER BY sold_count DESC
    """
    model_stats = conn.execute(model_query).fetchall()
    model_data = []
    for b in model_stats:
        model_data.append({
            "Бренд": b["brand"].capitalize(),
            "Модель": b["model"].capitalize(),
            "Продано шт.": b["sold_count"],
            "Ср. время продажи (дней)": round(b["avg_days_to_sell"] or 0, 1),
            "Ср. цена (BYN)": round(b["avg_price"] or 0, 2)
        })
        
    conn.close()
    
    return golden_vein_data, model_data, hidden_potential_data


def generate_excel_report(filepath="kufar_report.xlsx"):
    golden_vein, model_data, hidden_potential = generate_analytics_data()
    
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df1 = pd.DataFrame(golden_vein)
        if df1.empty:
            df1 = pd.DataFrame(columns=["Нет данных по этим критериям"])
        df1.to_excel(writer, sheet_name="Золотая жила (Топ 20)", index=False)
        
        df2 = pd.DataFrame(model_data)
        if df2.empty:
            df2 = pd.DataFrame(columns=["Нет проданных товаров"])
        df2.to_excel(writer, sheet_name="Анализ моделей", index=False)
        
        df3 = pd.DataFrame(hidden_potential)
        if df3.empty:
            df3 = pd.DataFrame(columns=["Нет товаров с высоким потенциалом"])
        df3.to_excel(writer, sheet_name="Скрытый потенциал", index=False)
        
    return filepath

def generate_text_summary():
    golden_vein, brand_data, hidden_potential = generate_analytics_data()
    
    lines = ["📊 *Аналитика Куфара (Сводка)*\n"]
    
    if golden_vein:
        lines.append("🔥 *Топ-3 товара (Золотая жила)*:")
        for i, item in enumerate(golden_vein[:3], 1):
            lines.append(f"{i}. [{item['Бренд']}] {item['Название']} — {item['Цена (BYN)']} BYN")
            lines.append(f"   📈 Импульс: {item['Импульс (рост)']}, Конверсия: {item['Конверсия в желание (%)']}%")
            lines.append(f"   🔗 {item['Ссылка']}")
    else:
        lines.append("🔥 *Золотая жила*: Подходящих товаров пока нет.")
        
    lines.append("\n💡 Подробности и скрытый потенциал смотрите в Excel-файле!")
    return "\n".join(lines)

if __name__ == "__main__":
    generate_excel_report()
    print("Report generated.")
