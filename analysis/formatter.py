import re
from datetime import datetime, timezone, timedelta
from config.settings import PIP_SIZE

WIB = timezone(timedelta(hours=7))
LINE = "━━━━━━━━━━━━━━━━━━"

PATTERN_TEXT = {
    "RBR": "[RBR] lanjut naik",
    "DBR": "[DBR] berbalik naik",
    "DBD": "[DBD] lanjut turun",
    "RBD": "[RDB] berbalik turun",
    "FVG": "[FVG] celah harga",
    "V-REV": "pembalikan tajam",
}

STATUS_TEXT = {
    "FRESH": "belum pernah disentuh",
    "MITIGATED_1X": "sudah disentuh 1x",
}


def _get_wib_timestamp() -> str:
    return datetime.now(WIB).strftime("%H:%M:%S WIB")


def _trend_text(trend: str) -> str:
    if "BULLISH" in trend:
        return "Bullish 🟢"
    if "BEARISH" in trend:
        return "Bearish 🔴"
    return "Sideways ↔️"


def _bos_text(bos: str) -> str:
    if "Bullish" in bos:
        return "Bullish, tembus ke atas"
    if "Bearish" in bos:
        return "Bearish, tembus ke bawah"
    return "Sideways, belum ada tembusan"


def _fvg_text(fvg: str) -> str:
    if not fvg:
        return ""
    nums = re.findall(r"\d+", fvg)
    if fvg.startswith("FVG Aktif") and len(nums) >= 2:
        return f"celah harga naik {nums[0]} / turun {nums[1]}"
    if fvg.startswith("Bullish") and nums:
        return f"celah harga naik ({nums[0]})"
    if fvg.startswith("Bearish") and nums:
        return f"celah harga turun ({nums[0]})"
    return ""


def _trend_lines(tf_order: list[str], tf_summaries: dict) -> list[str]:
    lines = []
    for tf in tf_order:
        info = tf_summaries.get(tf, {"trend": "SIDEWAYS ↔️", "bos": "", "fvg": ""})
        parts = [_trend_text(info["trend"]), _bos_text(info.get("bos", ""))]
        fvg = _fvg_text(info.get("fvg", ""))
        if fvg:
            parts.append(fvg)
        lines.append(f"• {tf:<3} : {parts[0]}  ({', '.join(parts[1:])})")
    return lines


def _zone_text(zone: dict) -> str:
    area = "Area beli" if zone["type"] == "DEMAND" else "Area jual"
    pola = PATTERN_TEXT.get(zone["pattern"], zone["pattern"])
    status = STATUS_TEXT.get(zone["status"], zone["status"])
    return f"{area}, {pola} ({status})"


def _simple_reason(reason: str) -> str:
    if reason.startswith("jarak") and ">" in reason:
        return "terlalu jauh dari harga"
    if reason.startswith("jarak") and "<" in reason:
        return "terlalu dekat dengan harga"
    if reason.startswith("Demand di atas"):
        return "area beli sudah ada di atas harga"
    if reason.startswith("Supply sudah"):
        return "area jual sudah dilewati harga"
    if reason.startswith("lawan tren"):
        return "melawan arah tren"
    return reason


def _bullets(text: str) -> list[str]:
    return [f"• {item.strip()}" for item in str(text).split("\n") if item.strip()]


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
        icon = "🟢" if is_demand else "🔴"
        status_text = f"{icon} {'BUY' if is_demand else 'SELL'}"
        entry_label = "Entry"
    else:
        icon = "🟡"
        status_text = f"⏳ WAIT — pantau {'Buy' if is_demand else 'Sell'} Limit"
        entry_label = "Buy Limit" if is_demand else "Sell Limit"

    sl_min_pips = round(abs(limit_price - sl_min) / PIP_SIZE)
    sl_max_pips = round(abs(limit_price - sl_max) / PIP_SIZE)
    if round(sl_min, 2) == round(sl_max, 2):
        sl_text = f"{sl_min:.2f} ({sl_min_pips} pips)"
    else:
        sl_text = f"{sl_min:.2f} - {sl_max:.2f} ({sl_min_pips}-{sl_max_pips} pips)"

    tp_lines = []
    for n, tp in enumerate((tp1, tp2, tp3), start=1):
        pips = round(abs(tp[1] - limit_price) / PIP_SIZE)
        tp_lines.append(f"• TP {n} : {tp[1]:.2f} (+{pips} pips)")

    lines = [
        f"{icon} XAUUSD — ANALISA ZONA",
        f"⚡ Mode : {mode.title()} ({' → '.join(tf_order)})",
        f"💰 Harga sekarang : {current_price:.2f}",
        LINE,
        "🧭 ARAH MARKET",
        *_trend_lines(tf_order, tf_summaries),
        LINE,
        f"📢 SINYAL : {status_text}",
        f"🔎 Zona dari : {active_tf}",
        f"📦 Jenis : {_zone_text(zone)}",
        "",
        f"📍 {entry_label} : {limit_price:.2f}",
        f"🛡 SL : {sl_text}",
        "",
        "🎯 TARGET PROFIT",
        *tp_lines,
        LINE,
        "💡 ALASAN",
        str(alasan_entry).strip(),
        "",
        "⚠️ WASPADA",
        *_bullets(waspadai),
        LINE,
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
    max_sl_pips: float = 100.0,
    nearest_reject: dict | None = None,
) -> str:
    alasan = (
        f"Belum ada zona baru yang cocok dalam jarak {int(min_dist_pips)}-{int(max_dist_pips)} pips "
        f"dari harga untuk mode {mode.title()}."
    )
    if nearest_reject is not None:
        area = "Area BUY" if nearest_reject["type"] == "DEMAND" else "Area SELL"
        pola = PATTERN_TEXT.get(nearest_reject["pattern"], nearest_reject["pattern"])
        alasan += (
            f"\nZona terdekat: {area} {pola} ({nearest_reject['tf']}) di "
            f"{nearest_reject['proximal']:.2f}, {nearest_reject['dist_pips']:.0f} pips dari harga. "
            f"Tidak dipakai karena {_simple_reason(nearest_reject['reason'])}."
        )

    lines = [
        "🪙 XAUUSD — RADAR ZONA",
        f"⚡ Mode : {mode.title()} ({' → '.join(tf_order)})",
        f"💰 Harga sekarang : {current_price:.2f}",
        LINE,
        "🧭 ARAH MARKET",
        *_trend_lines(tf_order, tf_summaries),
        LINE,
        "📢 Status : 🟡 TUNGGU — belum ada zona yang cocok",
        "",
        "💡 ALASAN",
        alasan,
        "",
        "⚠️ WASPADA",
        "• Jangan entry di tengah area tanpa struktur, tunggu zona baru terbentuk.",
        LINE,
        f"🕒 Update : {_get_wib_timestamp()}",
    ]
    return "\n".join(lines)
