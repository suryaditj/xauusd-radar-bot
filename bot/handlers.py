import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from analysis.zone_engine import run_full_analysis
from data.twelvedata_client import TwelveDataError

logger = logging.getLogger(__name__)


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("⚡ Scalping (H1-M15-M5)", callback_data="new_scalping"),
            InlineKeyboardButton("📊 Intra Day (D1-H4-M15)", callback_data="new_intraday"),
        ],
        [
            InlineKeyboardButton("📖 Aturan Main & Risiko", callback_data="show_rules"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_result_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    if current_mode == "SCALPING":
        refresh_cb = "refresh_scalping"
        switch_btn = InlineKeyboardButton("🔀 Pindah Intra Day", callback_data="new_intraday")
    else:
        refresh_cb = "refresh_intraday"
        switch_btn = InlineKeyboardButton("🔀 Pindah Scalping", callback_data="new_scalping")

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh Data", callback_data=refresh_cb),
            switch_btn,
        ],
        [
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_rules_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("⚡ Mulai Scalping", callback_data="new_scalping"),
            InlineKeyboardButton("📊 Mulai Intra Day", callback_data="new_intraday"),
        ],
        [
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


async def _detach_old_buttons(query) -> None:
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except BadRequest:
        pass


def _get_rules_text() -> str:
    lines = [
        "📖 ATURAN MAIN & MANAJEMEN RISIKO XAUUSD",
        "",
        "1. Pembagian Mode Analisa",
        "• Scalping (H1 → M15 → M5) : Filter SL 35 - 90 pips",
        "• Intra Day (D1 → H4 → M15) : Filter SL 70 - 180 pips",
        "",
        "2. Cara Membaca Status",
        "• ⏳ WAIT — PANTAU LIMIT : Harga masih berjarak 15 - 200 pips dari zona. Pasang Limit Order di titik Deep 50% (tengah zona) untuk meredam fakeout.",
        "• 🟢/🔴 SINYAL BUY/SELL : Harga sudah menyentuh zona dan terkonfirmasi candle reaksi di TF terkecil.",
        "",
        "3. Manajemen Lot & Stop Loss",
        "• Pada 0.01 lot XAUUSD, 10 pips = $1.00.",
        "• Pilih SL Minim (ketat) atau SL Maks (aman) sesuai batas risiko 1% - 2% saldo akun.",
        "• Jika rugi pada 0.01 lot masih melebihi batas risikomu, SKIP sinyal tersebut.",
        "",
        "4. Jam Efektif & Filter Berita",
        "• Fokuskan eksekusi pada sesi London hingga awal New York (14.00 - 22.00 WIB).",
        "• Hindari entry baru 15 menit sebelum dan sesudah rilis berita besar AS (CPI, NFP, FOMC).",
    ]
    return "\n".join(lines)


async def handle_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None:
        return

    action = query.data
    chat_id = update.effective_chat.id
    await query.answer()

    if action == "menu_main":
        await _detach_old_buttons(query)
        menu_text = (
            "🤖 XAUUSD RADAR — ZONE & TREND SCANNER\n\n"
            "Pilih mode analisa untuk memindai struktur pasar secara top-down:\n\n"
            "• ⚡ Scalping  : H1 → M15 → M5 (SL 35–90 pips)\n"
            "• 📊 Intra Day : D1 → H4 → M15 (SL 70–180 pips)"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=menu_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode=None,
        )
        return

    if action == "show_rules":
        await _detach_old_buttons(query)
        await context.bot.send_message(
            chat_id=chat_id,
            text=_get_rules_text(),
            reply_markup=get_rules_keyboard(),
            parse_mode=None,
        )
        return

    if action in ("new_scalping", "new_intraday"):
        mode = "SCALPING" if action == "new_scalping" else "INTRADAY"
        tf_label = "H1 → M15 → M5" if mode == "SCALPING" else "D1 → H4 → M15"

        await _detach_old_buttons(query)
        active_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ MEMINDAI XAUUSD — MODE {mode}\nMengambil data {tf_label} & menghitung zona valid...",
            parse_mode=None,
        )

        try:
            hasil_teks = await asyncio.to_thread(run_full_analysis, mode)
        except TwelveDataError as err:
            hasil_teks = f"⚠️ GANGGUAN DATA MARKET\n\n{err}"
        except Exception as exc:
            logger.exception("Error tidak terduga saat analisa %s", mode)
            hasil_teks = f"⚠️ TERJADI KESALAHAN SISTEM\n\nDetail: {exc}"

        await active_msg.edit_text(
            text=hasil_teks,
            reply_markup=get_result_keyboard(mode),
            parse_mode=None,
            disable_web_page_preview=True,
        )
        return

    if action in ("refresh_scalping", "refresh_intraday"):
        mode = "SCALPING" if action == "refresh_scalping" else "INTRADAY"
        tf_label = "H1 → M15 → M5" if mode == "SCALPING" else "D1 → H4 → M15"

        await query.edit_message_text(
            text=f"⏳ MEMPERBARUI DATA — MODE {mode}\nMengambil data {tf_label} terbaru...",
            reply_markup=None,
            parse_mode=None,
        )

        try:
            hasil_teks = await asyncio.to_thread(run_full_analysis, mode)
        except TwelveDataError as err:
            hasil_teks = f"⚠️ GANGGUAN DATA MARKET\n\n{err}"
        except Exception as exc:
            logger.exception("Error tidak terduga saat refresh %s", mode)
            hasil_teks = f"⚠️ TERJADI KESALAHAN SISTEM\n\nDetail: {exc}"

        try:
            await query.edit_message_text(
                text=hasil_teks,
                reply_markup=get_result_keyboard(mode),
                parse_mode=None,
                disable_web_page_preview=True,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
