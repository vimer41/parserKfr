import os
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from dotenv import load_dotenv
import database

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if BOT_TOKEN:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    # ── aliases ──────────────────────────────────────────────────────
    CAT_ALIAS = {
        'кроссовки': 'обувь', 'кросы': 'обувь', 'обувь': 'обувь',
        'одежда': 'одежда', 'шмот': 'одежда',
        'аксессуары': 'аксессуары', 'аксы': 'аксессуары', 'сумки': 'аксессуары',
    }
    CAT_E = {'обувь': '👟', 'одежда': '👕', 'аксессуары': '👜', 'другое': '📦'}

    # ═════════════════════════════════════════════════════════════════
    #  /start
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("start"))
    async def cmd_start(message: Message):
        database.register_user(message.chat.id)
        await message.answer(
            "👋 <b>Kufar Аналитик — анализатор спроса на бренды (BY)</b>\n\n"

            "📊 <b>Аналитика:</b>\n"
            "/report — спрос по всем брендам\n"
            "/report обувь|одежда|аксессуары — по категории\n"
            "/market [бренд] — полный разбор рынка\n"
            "/models [бренд] — самые популярные модели\n"
            "/prices [бренд] — мин / средняя / макс\n"
            "/top — самые быстропродающиеся бренды\n\n"

            "👥 <b>Конкуренты:</b>\n"
            "/sellers — топ продавцов (перекупщики)\n"
            "/sellers [бренд] — продавцы конкретного бренда\n\n"

            "💰 <b>Маржа:</b>\n"
            "/cost [бренд] [категория] [цена] — задать закупку\n"
            "/margin — расчёт маржи по категориям\n\n"

            "🔍 <b>Поиск:</b>\n"
            "/now [бренд] — свежие объявления прямо сейчас\n\n"

            "⚙️ <b>Управление:</b>\n"
            "/brands — отслеживаемые бренды\n"
            "/add [бренд]  ·  /remove [бренд]\n"
            "/filter [мин] [макс] — установить фильтр цен (напр: /filter 50 1500)\n\n"
            "🔔 Бот <b>сам</b> пришлёт уведомление при дефиците!",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="/report"), KeyboardButton(text="/top")],
                    [KeyboardButton(text="/sellers"), KeyboardButton(text="/margin")],
                    [KeyboardButton(text="/brands")]
                ],
                resize_keyboard=True
            )
        )

    # ═════════════════════════════════════════════════════════════════
    #  /report [категория]
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("report"))
    async def cmd_report(message: Message):
        args = message.text.split(maxsplit=1)
        cf = None; cl = "все категории"
        if len(args) > 1:
            raw = args[1].strip().lower()
            cf = CAT_ALIAS.get(raw, raw); cl = cf

        stats = database.get_analytics(days=7, category_filter=cf)

        if not stats:
            await message.answer(f"📊 Нет данных для «{cl}».")
            return

        t = f"📊 <b>Спрос ({cl}) за 7 дней:</b>\n\n"
        for s in stats:
            icon = "🟢" if s['sold_count'] > 5 else "🔹"
            t += f"{icon} <b>{s['brand']}</b>\n"
            t += f"   📦 В продаже: {s['active_count']}\n"
            if s['sold_count'] > 0:
                t += f"   ✅ Продано: {s['sold_count']} | ⏱ ~{s['avg_days']} дн.\n"
            else:
                t += f"   ⏳ Продаж пока нет\n"
            t += "\n"

        await message.answer(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /get_db — Скачать файл базы данных
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("get_db"))
    async def cmd_get_db(message: Message):
        from aiogram.types import FSInputFile
        import os
        
        # Можно раскомментировать строки ниже и вписать свой Telegram ID, 
        # чтобы никто чужой не смог скачать вашу базу.
        # if message.from_user.id != 123456789:  # Замените на ваш ID
        #     return

        # Путь к БД берём из вашего файла database.py
        db_path = database.DB_PATH
        
        if not os.path.exists(db_path):
            await message.answer("❌ Файл базы данных не найден на сервере.")
            return

        msg = await message.answer("⏳ Отправляю базу данных, подождите...")
        try:
            document = FSInputFile(db_path)
            await message.answer_document(document, caption="📦 Ваш файл базы данных (kufar_data.db)")
            await msg.delete()  # Удаляем сообщение "Отправляю..."
        except Exception as e:
            await msg.edit_text(f"❌ Ошибка при отправке файла: {e}")

    
    # ═════════════════════════════════════════════════════════════════
    #  /market [бренд]  —  полный разбор рынка
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("market"))
    async def cmd_market(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /market nike")
            return

        brand = args[1].strip()
        msg = await message.answer(f"⏳ Анализирую рынок «{brand}»…")

        m = database.get_market_analysis(brand)
        if m['total'] == 0:
            await msg.edit_text(f"Нет данных по «{brand}». Подождите, пока парсер соберёт объявления.")
            return

        total = m['total']

        def pct(n):
            return f"{n/total*100:.0f}%" if total else "0%"

        t = f"📊 <b>Рынок: {brand.capitalize()}</b>\n"
        t += f"📦 Всего объявлений: <b>{total}</b>\n\n"

        # Categories
        t += "<b>По категории:</b>\n"
        for cat, cnt in sorted(m['categories'].items(), key=lambda x: -x[1]):
            e = CAT_E.get(cat, '📦')
            t += f"  {e} {cat.capitalize()}: {cnt} ({pct(cnt)})\n"

        # Condition
        t += "\n<b>По состоянию:</b>\n"
        for cond, cnt in sorted(m['conditions'].items(), key=lambda x: -x[1]):
            e = "🆕" if cond == "новое" else "♻️" if cond == "б/у" else "❓"
            label = cond if cond else "не указано"
            t += f"  {e} {label.capitalize()}: {cnt} ({pct(cnt)})\n"

        # Origin
        t += "\n<b>По происхождению:</b>\n"
        t += f"  ✅ Оригинал: {m['originals']} ({pct(m['originals'])})\n"
        t += f"  🔄 Реплика/Копия: {m['replicas']} ({pct(m['replicas'])})\n"
        t += f"  ❓ Не указано: {m['unmarked']} ({pct(m['unmarked'])})\n"

        # Sellers
        t += "\n<b>Продавцы:</b>\n"
        t += f"  👤 Частники: {m['private_count']}\n"
        t += f"  🏪 Перекупщики (5+ объявл.): {m['reseller_count']}\n"

        if m['top_sellers']:
            t += "\n<b>Топ продавцов:</b>\n"
            for i, s in enumerate(m['top_sellers'][:5], 1):
                icon = "🏪" if s['is_company'] else "👤"
                t += f"  {i}. {icon} {s['name']} — {s['count']} объявл.\n"

        await msg.edit_text(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /top  —  самые быстропродающиеся
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("top"))
    async def cmd_top(message: Message):
        data = database.get_fastest_selling(days=7, limit=10)
        if not data:
            await message.answer("⏳ Пока недостаточно данных. Подождите 1-2 дня.")
            return

        t = "🏆 <b>Топ: самые быстрые продажи (7 дней):</b>\n\n"
        for i, d in enumerate(data, 1):
            t += f"{i}. <b>{d['brand']} {d['model']}</b> — ~{d['avg_days']} дн. ({d['sold']} продано)\n"

        t += "\n<i>Чем меньше дней — тем горячее спрос!</i>"
        await message.answer(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /models [бренд]  — статистика по конкретным моделям
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("models"))
    async def cmd_models(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /models nike")
            return
        brand = args[1].strip()
        stats = database.get_models_stats(brand)
        
        if not stats:
            await message.answer(f"Пока нет данных по моделям для «{brand}».")
            return

        t = f"👟 <b>Топ моделей {brand.capitalize()}:</b>\n\n"
        for s in stats[:15]:
            icon = "🔥" if s['sold_count'] > 2 else "🔹"
            t += f"{icon} <b>{s['model'].capitalize()}</b>\n"
            t += f"   📦 В продаже: {s['active_count']} | ✅ Продано: {s['sold_count']}\n"
        
        await message.answer(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /sellers [бренд]
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("sellers"))
    async def cmd_sellers(message: Message):
        args = message.text.split(maxsplit=1)
        brand = args[1].strip() if len(args) > 1 else None

        sellers = database.get_top_sellers(brand=brand, min_ads=3)
        if not sellers:
            await message.answer("Продавцов с 3+ объявлениями не найдено.")
            return

        label = f"«{brand.capitalize()}»" if brand else "все бренды"
        t = f"👥 <b>Топ продавцов ({label}):</b>\n\n"
        for i, s in enumerate(sellers, 1):
            icon = "🏪" if s['is_company'] else "👤"
            name_link = f"<a href='https://www.kufar.by/user/{s['seller_id']}'>{s['name']}</a>"
            t += f"{i}. {icon} <b>{name_link}</b> — {s['count']} объявл. (<i>Чаще всего: {s['top_item']}</i>)\n"

        t += "\n<i>🏪 = ИП/компания, 👤 = частник</i>"
        await message.answer(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /now [бренд]
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("now"))
    async def cmd_now(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /now nike")
            return

        brand = args[1].strip()
        msg = await message.answer(f"⏳ Ищу свежие объявления «{brand}»…")

        import parser
        ads = parser.parse_brand(brand, max_pages=1)
        if not ads:
            await msg.edit_text(f"Ничего не найдено для «{brand}».")
            return

        priced = sorted([a for a in ads if a['price'] > 0],
                        key=lambda x: x['price'], reverse=True)

        t = f"🔥 <b>{brand.capitalize()} — найдено {len(ads)} шт.</b>\n\n"
        for ad in priced[:10]:
            e = CAT_E.get(ad.get('category', ''), '📦')
            cond = "🆕" if ad.get('condition') == "новое" else "♻️" if ad.get('condition') == "б/у" else ""
            tag = ""
            if 'оригинал' in ad.get('tags', ''):
                tag = " ✅ориг"
            elif 'реплика' in ad.get('tags', ''):
                tag = " 🔄копия"

            title = ad['title'][:45]
            t += f"{e}{cond} <a href='{ad['url']}'>{title}</a> — <b>{ad['price']:.0f} BYN</b>{tag}\n"

        await msg.edit_text(t, parse_mode="HTML", disable_web_page_preview=True)

    # ═════════════════════════════════════════════════════════════════
    #  /prices [бренд]
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("prices"))
    async def cmd_prices(message: Message):
        args = message.text.split(maxsplit=1)
        brand = args[1].strip() if len(args) > 1 else None
        stats = database.get_price_stats(brand=brand)
        if not stats:
            await message.answer("Нет данных по ценам.")
            return

        t = "💰 <b>Анализ цен:</b>\n\n"
        
        if brand:
            mp = database.get_most_purchased_model(brand)
            if mp:
                t += f"🔥 <b>Самая покупаемая модель:</b> {mp.capitalize()}\n\n"

        for s in stats:
            model_label = f"{s['brand']} {s['model']}".strip()
            min_ad, max_ad = database.get_min_max_ads(s['brand_lower'], s['model'].lower() if s['model'] else '')
            
            t += f"🔹 <b>{model_label}</b> ({s['total']} объявл.)\n"
            
            if min_ad:
                t += f"   Мин: <a href='{min_ad[1]}'>{min_ad[0]:.0f} BYN</a>\n"
            else:
                t += f"   Мин: {s['min_price']:.0f} BYN\n"
                
            t += f"   Средняя: {s['avg_price']:.0f} BYN\n"
            
            if max_ad:
                t += f"   Макс: <a href='{max_ad[1]}'>{max_ad[0]:.0f} BYN</a>\n"
            else:
                t += f"   Макс: {s['max_price']:.0f} BYN\n"

            # Quick link to 1688
            bq = model_label.lower().replace(' ', '+')
            t += f"   🔗 <a href='https://s.1688.com/selloffer/offer_search.htm?keywords={bq}'>Поиск на 1688</a>\n\n"

        await message.answer(t, parse_mode="HTML", disable_web_page_preview=True)

    # ═════════════════════════════════════════════════════════════════
    #  /cost, /margin
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("cost"))
    async def cmd_cost(message: Message):
        parts = message.text.split()
        if len(parts) < 3:
            await message.answer(
                "<b>Использование:</b>\n"
                "<code>/cost nike 3xl 20</code> — закупка Nike 3xl = 20 BYN\n"
                "<code>/cost balenciaga runner 10</code> — закупка Balenciaga runner = 10 BYN\n"
                "<code>/cost nike 15</code> — закупка Nike (на все) = 15 BYN\n",
                parse_mode="HTML")
            return

        brand = parts[1].lower()

        try:
            price = float(parts[-1])
        except ValueError:
            await message.answer("Цена должна быть числом в конце.")
            return

        # Если передана модель (всё, что между брендом и ценой)
        model = " ".join(parts[2:-1]).lower()
        
        database.set_purchase_price(brand, price, model=model)
        if model:
            await message.answer(f"✅ Закупка «{brand.capitalize()} {model.capitalize()}» = {price:.0f} BYN")
        else:
            await message.answer(f"✅ Закупка «{brand.capitalize()}» (все модели) = {price:.0f} BYN")

    @dp.message(Command("margin"))
    async def cmd_margin(message: Message):
        costs = database.get_all_costs()
        if not costs:
            await message.answer(
                "Сначала задайте закупку:\n"
                "<code>/cost nike 3xl 200</code>",
                parse_mode="HTML"); return

        t = "📈 <b>Маржа (Куфар − Закупка):</b>\n\n"
        for c in costs:
            model_label = c['model'].capitalize() if c['model'] else 'все модели'
            ps = database.get_price_stats(
                brand=c['brand'],
                model_filter=c['model'] if c['model'] else None)
            
            if ps:
                s = ps[0]
                m = s['avg_price'] - c['price']
                p = (m / c['price'] * 100) if c['price'] > 0 else 0
                t += (f"🔹 <b>{c['brand'].capitalize()}</b> ({model_label})\n"
                      f"   Закупка: {c['price']:.0f} BYN\n"
                      f"   Ср. Куфар: {s['avg_price']:.0f} BYN\n"
                      f"   💰 Маржа: <b>{m:.0f} BYN ({p:.0f}%)</b>\n"
                      f"   Диапазон: {s['min_price']:.0f}–{s['max_price']:.0f} BYN\n\n")

        t += "<i>Маржа = Ср. цена Куфар − Ваша закупка</i>"
        await message.answer(t, parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  /brands, /add, /remove
    # ═════════════════════════════════════════════════════════════════
    @dp.message(Command("brands"))
    async def cmd_brands(message: Message):
        brands = database.get_active_brands()
        costs = database.get_all_costs()
        if not brands:
            await message.answer("Список пуст."); return
        t = "🔍 <b>Отслеживаемые бренды:</b>\n\n"
        for b in brands:
            # Find costs for this brand
            brand_costs = [c for c in costs if c['brand'] == b]
            if brand_costs:
                extras = []
                for c in brand_costs:
                    model_label = c['model'] if c['model'] else 'все'
                    extras.append(f"{model_label}={c['price']:.0f}")
                t += f"• {b.capitalize()} ({', '.join(extras)})\n"
            else:
                t += f"• {b.capitalize()}\n"
        await message.answer(t, parse_mode="HTML")

    @dp.message(Command("add"))
    async def cmd_add(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /add [бренд]"); return
        b = args[1].strip()
        await message.answer(f"✅ «{b}» добавлен." if database.add_brand(b)
                             else f"⚠️ «{b}» уже есть.")

    @dp.message(Command("remove"))
    async def cmd_remove(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Использование: /remove [бренд]"); return
        b = args[1].strip()
        database.remove_brand(b)
        await message.answer(f"🗑 «{b}» удалён.")

    @dp.message(Command("filter"))
    async def cmd_filter(message: Message):
        args = message.text.split()
        if len(args) != 3:
            await message.answer("Использование: /filter [мин_цена] [макс_цена]\nНапример: <code>/filter 50 1500</code>", parse_mode="HTML")
            return
        try:
            min_p = float(args[1])
            max_p = float(args[2])
        except ValueError:
            await message.answer("Цены должны быть числами!")
            return
        
        database.set_price_filter(min_p, max_p)
        await message.answer(f"✅ Фильтр цен обновлен: ищем товары от <b>{min_p:.0f}</b> до <b>{max_p:.0f}</b> BYN.", parse_mode="HTML")

    # ═════════════════════════════════════════════════════════════════
    #  Deficit notifications (called from scheduler)
    # ═════════════════════════════════════════════════════════════════
    async def send_deficit_alerts():
        alerts = database.get_deficit_alerts()
        if not alerts: return
        users = database.get_notification_users()
        if not users: return
        for a in alerts:
            t = (f"⚡ <b>Внимание! Возможный дефицит!</b>\n\n"
                 f"Бренд: <b>{a['brand']} {a['model']}</b>\n"
                 f"Продано за {a['sold_days']} дн: {a['sold_count']} шт.\n"
                 f"Осталось: {a['active_count']} шт.\n\n"
                 f"🔥 Раскупают быстрее, чем появляются новые!")
            for cid in users:
                try:
                    await bot.send_message(cid, t, parse_mode="HTML")
                except Exception as e:
                    logging.error(f"Alert to {cid} failed: {e}")

    async def send_analytics_report():
        import analytics
        from aiogram.types import FSInputFile
        
        users = database.get_notification_users()
        if not users: return
        
        try:
            text_summary = analytics.generate_text_summary()
            excel_file = analytics.generate_excel_report()
            document = FSInputFile(excel_file)
            
            for cid in users:
                try:
                    await bot.send_message(cid, text_summary, parse_mode="Markdown")
                    await bot.send_document(cid, document)
                except Exception as e:
                    logging.error(f"Failed to send analytics report to {cid}: {e}")
        except Exception as e:
            logging.error(f"Failed to generate analytics report: {e}")

    async def start_bot():
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
