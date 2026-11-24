import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from config.settings import MODE_PROFILES
from analysis.zone_engine import run_full_analysis
from data.twelvedata_client import TwelveDataError

logger = logging.getLogger(__name__)

MODE_ACTIONS = {
    "new_intraday": "INTRADAY",
    "new_scalping": "SCALPING",
    "new_quick1": "QUICK_SCALP_1",
    "new_quick2": "QUICK_SCALP_2",
}

REFRESH_ACTIONS = {
    "refresh_intraday": "INTRADAY",
    "refresh_scalping": "SCALPING",
    "refresh_quick1": "QUICK_SCALP_1",
    "refresh_quick2": "QUICK_SCALP_2",
}

MODE_CALLBACK_SUFFIX = {
    "INTRADAY": "intraday",
    "SCALPING": "scalping",
    "QUICK_SCALP_1": "quick1",
    "QUICK_SCALP_2": "quick2",
}


def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📊 Intra Day (D1-H4-M15)", callback_data="new_intraday"),
            InlineKeyboardButton("⚡ Scalping (H1-M15-M5)", callback_data="new_scalping"),
        ],
        [
            InlineKeyboardButton("🔥 Quick Scalp 1 (M30-M15-M5)", callback_data="new_quick1"),
            InlineKeyboardButton("🚀 Quick Scalp 2 (M15-M5-M1)", callback_data="new_quick2"),
        ],
        [
            InlineKeyboardButton("📖 Aturan Main & Risiko", callback_data="show_rules"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_result_keyboard(current_mode: str) -> InlineKeyboardMarkup:
    suffix = MODE_CALLBACK_SUFFIX[current_mode]
    refresh_cb = f"refresh_{suffix}"

    other_modes = [
        ("INTRADAY", "📊 Intra Day", "new_intraday"),
        ("SCALPING", "⚡ Scalping", "new_scalping"),
        ("QUICK_SCALP_1", "🔥 Quick 1", "new_quick1"),
        ("QUICK_SCALP_2", "🚀 Quick 2", "new_quick2"),
    ]
    switch_buttons = [
        InlineKeyboardButton(label, callback_data=cb)
        for m_key, label, cb in other_modes
        if m_key != current_mode
    ]

    keyboard = [
        [
            InlineKeyboardButton("🔄 Refresh Data", callback_data=refresh_cb),
            switch_buttons[0],
        ],
        [
            switch_buttons[1],
            switch_buttons[2],
        ],
        [
            InlineKeyboardButton("🏠 Menu Utama", callback_data="menu_main"),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_rules_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📊 Intra Day", callback_data="new_intraday"),
            InlineKeyboardButton("⚡ Scalping", callback_data="new_scalping"),
        ],
        [
            InlineKeyboardButton("🔥 Quick Scalp 1", callback_data="new_quick1"),
            InlineKeyboardButton("🚀 Quick Scalp 2", callback_data="new_quick2"),
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
        "1. Pembagian 4 Mode Analisa",
        "• Intra Day (D1 → H4 → M15)      : SL 70 - 180 pips",
        "• Scalping (H1 → M15 → M5)       : SL 35 - 90 pips",
        "• Quick Scalp 1 (M30 → M15 → M5) : SL 25 - 65 pips",
        "• Quick Scalp 2 (M15 → M5 → M1)  : SL 15 - 35 pips (Wajib searah M15)",
        "",
        "2. Cara Membaca Status",
        "• ⏳ WAIT — PANTAU LIMIT : Harga masih mendekati zona. Pasang Limit Order di titik Deep 50% (tengah zona) untuk meredam fakeout.",
        "• 🟢/🔴 SINYAL BUY/SELL : Harga sudah menyentuh zona dan terkonfirmasi engulfing / rejection kuat di TF terkecil.",
        "",
        "3. Manajemen Lot & Stop Loss",
        "• Pada 0.01 lot XAUUSD, 10 pips = $1.00.",
        "• Quick Scalp 1 & 2 sensitif terhadap spread; gunakan hanya saat sesi aktif (14.00 - 22.00 WIB).",
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
            "Pilih mode analisa sesuai target profitmu:\n\n"
            "• 📊 Intra Day     : D1 → H4 → M15 (SL 70–180 pips)\n"
            "• ⚡ Scalping      : H1 → M15 → M5 (SL 35–90 pips)\n"
            "• 🔥 Quick Scalp 1 : M30 → M15 → M5 (SL 25–65 pips)\n"
            "• 🚀 Quick Scalp 2 : M15 → M5 → M1 (SL 15–35 pips)"
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

    if action in MODE_ACTIONS:
        mode = MODE_ACTIONS[action]
        profile = MODE_PROFILES[mode]
        label = profile["label"].upper()
        tf_label = " → ".join(profile["timeframes"])

        await _detach_old_buttons(query)
        active_msg = await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ MEMINDAI XAUUSD — MODE {label}\nMengambil data {tf_label} & menghitung zona valid...",
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

    if action in REFRESH_ACTIONS:
        mode = REFRESH_ACTIONS[action]
        profile = MODE_PROFILES[mode]
        label = profile["label"].upper()
        tf_label = " → ".join(profile["timeframes"])

        await query.edit_message_text(
            text=f"⏳ MEMPERBARUI DATA — MODE {label}\nMengambil data {tf_label} terbaru...",
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
