import asyncio
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

from config.settings import TELEGRAM_BOT_TOKEN, SESSION_DURATION_MINUTES
from bot.handlers import get_main_menu_keyboard, handle_button_click

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    menu_text = (
        "🤖 XAUUSD RADAR — ZONE & TREND SCANNER\n\n"
        "Pilih mode analisa untuk memindai struktur pasar secara top-down:\n\n"
        "• ⚡ Scalping  : H1 → M15 → M5 (SL 35–90 pips)\n"
        "• 📊 Intra Day : D1 → H4 → M15 (SL 70–180 pips)"
    )
    await update.message.reply_text(
        text=menu_text,
        reply_markup=get_main_menu_keyboard(),
        parse_mode=None,
    )


async def run_session() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN belum diatur di GitHub Secrets.")

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_button_click))

    logger.info("Memulai sesi bot selama %d menit...", SESSION_DURATION_MINUTES)
    await app.initialize()
    await app.start()
    await app.updater.start_polling(drop_pending_updates=True)

    try:
        await asyncio.sleep(SESSION_DURATION_MINUTES * 60)
    finally:
        logger.info("Durasi sesi selesai. Menutup koneksi bot secara bersih...")
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


if __name__ == "__main__":
    asyncio.run(run_session())
