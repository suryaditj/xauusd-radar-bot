from datetime import datetime, timezone, timedelta
from config.settings import PIP_SIZE

WIB = timezone(timedelta(hours=7))


def _clean_inline_text(text: str) -> str:
    return " ".join(str(text).split())


def _get_wib_timestamp() -> str:
    return datetime.now(WIB).strftime("%H:%M:%S WIB")


def format_locked_radar_message(
    mode: str,
    tf_order: list[str],
    current_price: float,
    tf_summaries: dict,
    active_tf: str,
    zone: dict,
    limit_price: float,
    sl_min: float,
    sl_max: float,
    tp1: tuple[str, float],
    tp2: tuple[str, float],
    tp3: tuple[str, float],
    alasan_entry: str,
    waspadai: str,
    is_confirmed: bool = False,
) -> str:
    is_demand = zone["type"] == "DEMAND"

    if is_confirmed:
        header_icon = "🟢" if is_demand else "🔴"
        side_label = "BUY" if is_demand else "SELL"
        status_text = f"{header_icon} SINYAL : {side_label}"
        entry_label = "Entry Area"
    else:
        header_icon = "🟡"
        side_label = "BUY LIMIT" if is_demand else "SELL LIMIT"
        status_text = f"⏳ WAIT — PANTAU {side_label}"
        entry_label = "Buy Limit " if is_demand else "Sell Limit"

    sl_min_pips = round(abs(limit_price - sl_min) / PIP_SIZE)
    sl_max_pips = round(abs(limit_price - sl_max) / PIP_SIZE)

    tp1_pips = round(abs(tp1[1] - limit_price) / PIP_SIZE)
    tp2_pips = round(abs(tp2[1] - limit_price) / PIP_SIZE)
    tp3_pips = round(abs(tp3[1] - limit_price) / PIP_SIZE)

    trend_lines = []
    for tf in tf_order:
        info = tf_summaries.get(tf, {"trend": "SIDEWAYS ⚪", "bos": "Belum ada BOS", "fvg": ""})
        extra = f" | {info['fvg']}" if info.get("fvg") else ""
        trend_lines.append(f"• {tf:<3} : {info['trend']} | {info['bos']}{extra}")

    tp1_tag = f"({tp1[0]})"
    tp2_tag = f"({tp2[0]})"
    tp3_tag = f"({tp3[0]})"

    lines = [
        f"{header_icon} XAUUSD — MULTI-TF RADAR & ZONA",
        f"Mode : {mode} ({' → '.join(tf_order)})",
        f"Harga Saat Ini : {current_price:.2f}",
        "",
        "🧭 Peta Kondisi Market (Info Tren)",
        *trend_lines,
        "",
        f"🔎 Sumber Zona Aktif : TF {active_tf}",
        f"📢 STATUS : {status_text}",
        f"📦 Pola   : {zone['type']} {zone['pattern']} ({zone['status']})",
        "",
        f"📍 {entry_label} : {limit_price:.2f}",
        f"🛡 SL         : {sl_min:.2f} - {sl_max:.2f} ({sl_min_pips} - {sl_max_pips} pips)",
        "",
        "🎯 Target Profit",
        f"• TP 1 {tp1_tag:<16}: {tp1[1]:.2f} (+{tp1_pips} pips)",
        f"• TP 2 {tp2_tag:<16}: {tp2[1]:.2f} (+{tp2_pips} pips)",
        f"• TP 3 {tp3_tag:<16}: {tp3[1]:.2f} (+{tp3_pips} pips)",
        "",
        f"💡 Alasan Entry : {_clean_inline_text(alasan_entry)}",
        "",
        f"⚠️ Waspadai : {_clean_inline_text(waspadai)}",
        "",
        f"🕒 Update : {_get_wib_timestamp()}",
    ]

    return "\n".join(lines)


def format_no_zone_message(
    mode: str,
    tf_order: list[str],
    current_price: float,
    tf_summaries: dict,
    min_dist_pips: float = 15.0,
    max_dist_pips: float = 200.0,
    max_sl_pips: float = 90.0,
) -> str:
    trend_lines = []
    for tf in tf_order:
        info = tf_summaries.get(tf, {"trend": "SIDEWAYS ⚪", "bos": "Belum ada BOS", "fvg": ""})
        extra = f" | {info['fvg']}" if info.get("fvg") else ""
        trend_lines.append(f"• {tf:<3} : {info['trend']} | {info['bos']}{extra}")

    dist_range_str = f"{int(min_dist_pips)}-{int(max_dist_pips)} pips"
    lines = [
        "⚪ XAUUSD — MULTI-TF RADAR & ZONA",
        f"Mode : {mode} ({' → '.join(tf_order)})",
        f"Harga Saat Ini : {current_price:.2f}",
        "",
        "🧭 Peta Kondisi Market (Info Tren)",
        *trend_lines,
        "",
        f"🔎 Sumber Zona Aktif : Tidak ditemukan ({' / '.join(tf_order)})",
        "📢 STATUS : ⚪ WAIT — BELUM ADA ZONA VALID",
        "",
        f"💡 Alasan Entry : Belum ada zona Supply/Demand/FVG segar dalam koridor {dist_range_str} dengan batas SL maks {int(max_sl_pips)} pips.",
        "",
        "⚠️ Waspadai : Jangan memaksakan entry di tengah area tanpa struktur; tunggu pembentukan base dan leg-out baru.",
        "",
        f"🕒 Update : {_get_wib_timestamp()}",
    ]

    return "\n".join(lines)
