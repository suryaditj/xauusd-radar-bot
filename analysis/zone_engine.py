import numpy as np
import pandas as pd
from config.settings import (
    PIP_SIZE,
    MODE_PROFILES,
    MIN_DIST_PIPS,
    MAX_DIST_PIPS,
)
from data.twelvedata_client import fetch_mode_dataset
from analysis.formatter import format_locked_radar_message, format_no_zone_message


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def analyze_tf_context(df: pd.DataFrame) -> dict:
    data = df.copy().reset_index(drop=True)
    data["ema50"] = data["close"].ewm(span=50, adjust=False).mean()
    data["ema200"] = data["close"].ewm(span=200, adjust=False).mean()

    last_close = data["close"].iloc[-2]
    ema50 = data["ema50"].iloc[-2]
    ema200 = data["ema200"].iloc[-2]

    if last_close > ema50 > ema200:
        trend = "BULLISH 🟢"
    elif last_close < ema50 < ema200:
        trend = "BEARISH 🔴"
    else:
        trend = "SIDEWAYS ⚪"

    recent_high = data["high"].iloc[-17:-2].max()
    recent_low = data["low"].iloc[-17:-2].min()

    if last_close > recent_high:
        bos_status = "BOS Bullish"
    elif last_close < recent_low:
        bos_status = "BOS Bearish"
    else:
        bos_status = "Belum ada BOS"

    c1_high, c1_low = data["high"].iloc[-4], data["low"].iloc[-4]
    c3_high, c3_low = data["high"].iloc[-2], data["low"].iloc[-2]

    if c3_low > c1_high:
        fvg_status = "Bullish FVG"
    elif c3_high < c1_low:
        fvg_status = "Bearish FVG"
    else:
        fvg_status = ""

    return {
        "trend": trend,
        "bos": bos_status,
        "fvg": fvg_status,
    }


def evaluate_zone_mitigation(
    subsequent_df: pd.DataFrame,
    zone_type: str,
    proximal: float,
    distal: float,
) -> dict:
    zone_width = abs(proximal - distal)
    if zone_width == 0 or subsequent_df.empty:
        return {
            "status": "FRESH",
            "touch_count": 0,
            "max_penetration_pct": 0.0,
        }

    touch_count = 0
    max_penetration = 0.0
    currently_inside = False

    for _, row in subsequent_df.iterrows():
        if zone_type == "DEMAND":
            if row["low"] < distal:
                return {"status": "BROKEN", "touch_count": touch_count, "max_penetration_pct": 100.0}
            if row["low"] <= proximal:
                if not currently_inside:
                    touch_count += 1
                    currently_inside = True
                penetration = (proximal - row["low"]) / zone_width
                max_penetration = max(max_penetration, penetration)
            else:
                currently_inside = False
        else:
            if row["high"] > distal:
                return {"status": "BROKEN", "touch_count": touch_count, "max_penetration_pct": 100.0}
            if row["high"] >= proximal:
                if not currently_inside:
                    touch_count += 1
                    currently_inside = True
                penetration = (row["high"] - proximal) / zone_width
                max_penetration = max(max_penetration, penetration)
            else:
                currently_inside = False

    penetration_pct = round(max_penetration * 100, 1)
    if touch_count == 0:
        status = "FRESH"
    elif touch_count == 1 and penetration_pct < 75.0:
        status = "MITIGATED_1X"
    else:
        status = "EXHAUSTED"

    return {
        "status": status,
        "touch_count": touch_count,
        "max_penetration_pct": penetration_pct,
    }


def detect_snd_zones(df: pd.DataFrame, tf_name: str, max_base_candles: int = 3) -> list[dict]:
    if len(df) < 25:
        return []

    data = df.copy().reset_index(drop=True)
    data["atr"] = calculate_atr(data, 14)
    data["range"] = data["high"] - data["low"]
    data["body"] = (data["close"] - data["open"]).abs()
    data["body_ratio"] = np.where(data["range"] > 0, data["body"] / data["range"], 0.0)

    closed_len = len(data) - 1
    zones = []

    i = 15
    while i < closed_len - 2:
        found_zone = False
        for base_len in range(1, max_base_candles + 1):
            leg_out_idx = i + base_len
            if leg_out_idx >= closed_len:
                break

            base_slice = data.iloc[i:leg_out_idx]
            leg_out = data.iloc[leg_out_idx]
            leg_in = data.iloc[i - 1]

            is_valid_base = (
                (base_slice["body_ratio"] <= 0.45).all()
                and (base_slice["range"] <= 1.2 * base_slice["atr"]).all()
            )
            if not is_valid_base:
                continue

            is_strong_leg_out = (
                leg_out["body"] >= 1.5 * leg_out["atr"]
                and leg_out["body_ratio"] >= 0.60
            )
            if not is_strong_leg_out:
                continue

            is_bullish_out = leg_out["close"] > leg_out["open"]
            is_bullish_in = leg_in["close"] > leg_in["open"]

            if is_bullish_out:
                zone_type = "DEMAND"
                pattern = "RBR" if is_bullish_in else "DBR"
                proximal = float(base_slice[["open", "close"]].max().max())
                distal = float(min(base_slice["low"].min(), leg_out["low"]))
            else:
                zone_type = "SUPPLY"
                pattern = "DBD" if not is_bullish_in else "RBD"
                proximal = float(base_slice[["open", "close"]].min().min())
                distal = float(max(base_slice["high"].max(), leg_out["high"]))

            subsequent_data = data.iloc[leg_out_idx + 1 :]
            mitigation_info = evaluate_zone_mitigation(subsequent_data, zone_type, proximal, distal)

            if mitigation_info["status"] == "BROKEN":
                continue

            zones.append({
                "tf": tf_name,
                "type": zone_type,
                "pattern": pattern,
                "status": mitigation_info["status"],
                "touches": mitigation_info["touch_count"],
                "penetration_pct": mitigation_info["max_penetration_pct"],
                "proximal": round(proximal, 2),
                "distal": round(distal, 2),
            })
            i = leg_out_idx
            found_zone = True
            break

        if not found_zone:
            i += 1

    return zones


def check_ltf_confirmation(
    confirm_df: pd.DataFrame,
    zone_type: str,
    proximal: float,
    distal: float,
    current_price: float,
) -> bool:
    if len(confirm_df) < 5:
        return False

    recent = confirm_df.iloc[-4:-1]
    last_closed = confirm_df.iloc[-2]
    candle_range = last_closed["high"] - last_closed["low"]
    if candle_range <= 0:
        return False

    if zone_type == "DEMAND":
        in_or_near_zone = (distal <= current_price <= proximal + (3 * PIP_SIZE))
        touched_zone = (recent["low"].min() <= proximal) and (recent["low"].min() >= distal)
        lower_wick = min(last_closed["open"], last_closed["close"]) - last_closed["low"]
        bullish_reaction = (last_closed["close"] > last_closed["open"]) or (lower_wick / candle_range >= 0.50)
        return in_or_near_zone and touched_zone and bullish_reaction
    else:
        in_or_near_zone = (proximal - (3 * PIP_SIZE) <= current_price <= distal)
        touched_zone = (recent["high"].max() >= proximal) and (recent["high"].max() <= distal)
        upper_wick = last_closed["high"] - max(last_closed["open"], last_closed["close"])
        bearish_reaction = (last_closed["close"] < last_closed["open"]) or (upper_wick / candle_range >= 0.50)
        return in_or_near_zone and touched_zone and bearish_reaction


def evaluate_zone_setup(
    zone: dict,
    current_price: float,
    profile: dict,
    confirm_df: pd.DataFrame,
    all_zones: list[dict],
) -> dict | None:
    if zone["status"] not in ("FRESH", "MITIGATED_1X"):
        return None

    zone_type = zone["type"]
    proximal = zone["proximal"]
    distal = zone["distal"]

    # Pastikan posisi zona selaras dengan arah limit order (Demand di bawah harga, Supply di atas harga)
    is_confirmed = check_ltf_confirmation(confirm_df, zone_type, proximal, distal, current_price)

    if is_confirmed:
        limit_price = round(current_price, 2)
        dist_pips = 0.0
    else:
        if zone_type == "DEMAND" and proximal >= current_price:
            return None
        if zone_type == "SUPPLY" and proximal <= current_price:
            return None

        dist_pips = abs(current_price - proximal) / PIP_SIZE
        if not (MIN_DIST_PIPS <= dist_pips <= MAX_DIST_PIPS):
            return None

        # Deep Limit 50% untuk meredam fakeout di bibir zona
        limit_price = round((proximal + distal) / 2.0, 2)

    buffer_pips = profile["buffer_pips"]
    extra_buffer_pips = round(buffer_pips * 2.5, 1)

    if zone_type == "DEMAND":
        sl_min = round(distal - (buffer_pips * PIP_SIZE), 2)
        raw_sl_max = round(distal - (extra_buffer_pips * PIP_SIZE), 2)
    else:
        sl_min = round(distal + (buffer_pips * PIP_SIZE), 2)
        raw_sl_max = round(distal + (extra_buffer_pips * PIP_SIZE), 2)

    sl_min_pips = round(abs(limit_price - sl_min) / PIP_SIZE, 1)
    if not (profile["min_sl_pips"] <= sl_min_pips <= profile["max_sl_pips"]):
        return None

    raw_sl_max_pips = round(abs(limit_price - raw_sl_max) / PIP_SIZE, 1)
    clamped_max_pips = max(
        sl_min_pips + 10.0,
        min(raw_sl_max_pips, profile["max_sl_pips"]),
    )
    if clamped_max_pips > profile["max_sl_pips"]:
        clamped_max_pips = profile["max_sl_pips"]

    direction = 1 if zone_type == "DEMAND" else -1
    sl_max = round(limit_price - direction * (clamped_max_pips * PIP_SIZE), 2)

    # Susun TP 1 (Swing Liquidity), TP 2 & TP 3 (Zona Lawan / Proyeksi Bertingkat)
    recent_slice = confirm_df.iloc[-45:-1]
    if zone_type == "DEMAND":
        swing_candidates = recent_slice[
            recent_slice["high"] >= limit_price + (sl_min_pips * 1.2 * PIP_SIZE)
        ]["high"]
        tp1_price = round(float(swing_candidates.min()), 2) if not swing_candidates.empty else round(
            limit_price + (sl_min_pips * 1.5 * PIP_SIZE), 2
        )
        tp1_label = "Swing High"

        opposing = sorted(
            [
                z for z in all_zones
                if z["type"] == "SUPPLY"
                and z["status"] in ("FRESH", "MITIGATED_1X")
                and z["proximal"] > tp1_price + (15 * PIP_SIZE)
            ],
            key=lambda item: item["proximal"],
        )
    else:
        swing_candidates = recent_slice[
            recent_slice["low"] <= limit_price - (sl_min_pips * 1.2 * PIP_SIZE)
        ]["low"]
        tp1_price = round(float(swing_candidates.max()), 2) if not swing_candidates.empty else round(
            limit_price - (sl_min_pips * 1.5 * PIP_SIZE), 2
        )
        tp1_label = "Swing Low"

        opposing = sorted(
            [
                z for z in all_zones
                if z["type"] == "DEMAND"
                and z["status"] in ("FRESH", "MITIGATED_1X")
                and z["proximal"] < tp1_price - (15 * PIP_SIZE)
            ],
            key=lambda item: item["proximal"],
            reverse=True,
        )

    tp1_pips = abs(tp1_price - limit_price) / PIP_SIZE

    # Validasi TP 2 (Minimal RR 1:1.5 dari SL Minim dan strictly lebih jauh dari TP 1)
    min_tp2_pips = max(sl_min_pips * 1.5, tp1_pips + 25.0)
    if len(opposing) >= 1:
        wall_1 = opposing[0]
        wall_1_pips = abs(wall_1["proximal"] - limit_price) / PIP_SIZE
        if wall_1_pips < (sl_min_pips * 1.5):
            # Ruang gerak tercekik zona lawan yang terlalu dekat
            return None
        if wall_1_pips >= min_tp2_pips:
            tp2_price = round(wall_1["proximal"], 2)
            tp2_label = f"{wall_1['type'].title()} {wall_1['pattern']}"
        else:
            tp2_price = round(limit_price + direction * (min_tp2_pips * PIP_SIZE), 2)
            tp2_label = "Proyeksi RR"
    else:
        tp2_price = round(limit_price + direction * (min_tp2_pips * PIP_SIZE), 2)
        tp2_label = "Proyeksi RR"

    tp2_pips = abs(tp2_price - limit_price) / PIP_SIZE

    # Validasi TP 3 (Strictly lebih jauh dari TP 2)
    min_tp3_pips = tp2_pips + 35.0
    if len(opposing) >= 2:
        wall_2 = opposing[1]
        wall_2_pips = abs(wall_2["proximal"] - limit_price) / PIP_SIZE
        if wall_2_pips >= min_tp3_pips:
            tp3_price = round(wall_2["proximal"], 2)
            tp3_label = f"{wall_2['type'].title()} {wall_2['tf']}"
        else:
            tp3_price = round(limit_price + direction * (min_tp3_pips * PIP_SIZE), 2)
            tp3_label = "Proyeksi ATR"
    else:
        tp3_price = round(limit_price + direction * (min_tp3_pips * PIP_SIZE), 2)
        tp3_label = "Proyeksi ATR"

    return {
        "zone": zone,
        "is_confirmed": is_confirmed,
        "dist_pips": dist_pips,
        "limit_price": limit_price,
        "sl_min": sl_min,
        "sl_max": sl_max,
        "tp1": (tp1_label, tp1_price),
        "tp2": (tp2_label, tp2_price),
        "tp3": (tp3_label, tp3_price),
    }


def _build_dynamic_notes(
    mode: str,
    trend_tf: str,
    active_tf: str,
    zone: dict,
    tf_summaries: dict,
    tp1: tuple[str, float],
    tp2: tuple[str, float],
) -> tuple[str, str]:
    is_demand = zone["type"] == "DEMAND"
    arah_teks = "pantulan naik" if is_demand else "pantulan turun"
    htf_trend = tf_summaries.get(trend_tf, {}).get("trend", "SIDEWAYS ⚪")
    active_info = tf_summaries.get(active_tf, {})

    alasan_parts = [f"zona {zone['type']} {zone['pattern']} ({zone['status']}) di {active_tf}"]
    if "BOS" in active_info.get("bos", ""):
        alasan_parts.append(f"didukung {active_info['bos']}")
    if active_info.get("fvg"):
        alasan_parts.append(f"area {active_info['fvg']}")

    alasan_entry = f"Menunggu {arah_teks} dari {', '.join(alasan_parts)}."

    waspada_list = []
    if "SIDEWAYS" in htf_trend:
        waspada_list.append(f"tren utama {trend_tf} masih Sideways (momentum belum searah penuh)")
    elif (is_demand and "BEARISH" in htf_trend) or (not is_demand and "BULLISH" in htf_trend):
        waspada_list.append(f"posisi melawan tren {trend_tf} ({htf_trend}) — wajib disiplin SL")

    if zone["status"] == "MITIGATED_1X":
        waspada_list.append(
            f"zona sudah tersentuh 1x (penetrasi {zone['penetration_pct']}%), rawan sapuan ekor"
        )

    waspada_list.append(
        f"amankan sebagian profit di TP 1 ({tp1[1]:.2f}) sebelum harga menyentuh {tp2[0]} di {tp2[1]:.2f}"
    )
    waspadai = "; ".join(waspada_list)
    waspadai = waspadai[0].upper() + waspadai[1:] + "."

    return alasan_entry, waspadai


def run_full_analysis(mode: str) -> str:
    mode_upper = mode.upper()
    profile = MODE_PROFILES[mode_upper]
    tf_order = profile["timeframes"]

    dataset = fetch_mode_dataset(tf_order)
    current_price = float(dataset[tf_order[-1]]["close"].iloc[-1])

    tf_summaries: dict[str, dict] = {}
    all_zones: list[dict] = []

    for tf in tf_order:
        df = dataset[tf]
        tf_summaries[tf] = analyze_tf_context(df)
        all_zones.extend(detect_snd_zones(df, tf))

    confirm_df = dataset[profile["confirm_tf"]]
    selected_setup = None
    selected_tf = None

    # Cascade pemindaian zona dari TF lebih besar ke TF lebih kecil
    for tf in profile["zone_tfs"]:
        tf_zones = [z for z in all_zones if z["tf"] == tf]
        valid_candidates = []
        for z in tf_zones:
            evaluated = evaluate_zone_setup(z, current_price, profile, confirm_df, all_zones)
            if evaluated is not None:
                valid_candidates.append(evaluated)

        if valid_candidates:
            # Prioritaskan sinyal terkonfirmasi, lalu jarak terdekat ke harga saat ini
            valid_candidates.sort(key=lambda item: (not item["is_confirmed"], item["dist_pips"]))
            selected_setup = valid_candidates[0]
            selected_tf = tf
            break

    if selected_setup is None or selected_tf is None:
        return format_no_zone_message(mode_upper, tf_order, current_price, tf_summaries)

    alasan_entry, waspadai = _build_dynamic_notes(
        mode=mode_upper,
        trend_tf=profile["trend_tf"],
        active_tf=selected_tf,
        zone=selected_setup["zone"],
        tf_summaries=tf_summaries,
        tp1=selected_setup["tp1"],
        tp2=selected_setup["tp2"],
    )

    return format_locked_radar_message(
        mode=mode_upper,
        tf_order=tf_order,
        current_price=current_price,
        tf_summaries=tf_summaries,
        active_tf=selected_tf,
        zone=selected_setup["zone"],
        limit_price=selected_setup["limit_price"],
        sl_min=selected_setup["sl_min"],
        sl_max=selected_setup["sl_max"],
        tp1=selected_setup["tp1"],
        tp2=selected_setup["tp2"],
        tp3=selected_setup["tp3"],
        alasan_entry=alasan_entry,
        waspadai=waspadai,
        is_confirmed=selected_setup["is_confirmed"],
    )
