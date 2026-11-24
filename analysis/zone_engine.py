import numpy as np
import pandas as pd
from config.settings import (
    PIP_SIZE,
    LOOKBACK_BY_TF,
    SNR_PROXIMITY_PIPS,
    FVG_MIN_ATR_MULT,
    MODE_PROFILES,
    MIN_DIST_PIPS,
)
from data.twelvedata_client import fetch_mode_dataset
from analysis.formatter import format_locked_radar_message, format_no_zone_message


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def _prepare_window(df: pd.DataFrame, tf_name: str) -> pd.DataFrame:
    data = df.copy().reset_index(drop=True)
    data["ema50"] = data["close"].ewm(span=50, adjust=False).mean()
    data["ema200"] = data["close"].ewm(span=200, adjust=False).mean()
    data["atr"] = calculate_atr(data, 14)
    data["range"] = data["high"] - data["low"]
    data["body"] = (data["close"] - data["open"]).abs()
    data["body_ratio"] = np.where(data["range"] > 0, data["body"] / data["range"], 0.0)

    lookback = LOOKBACK_BY_TF.get(tf_name, 72)
    slice_len = lookback + 1
    if len(data) > slice_len:
        data = data.iloc[-slice_len:].reset_index(drop=True)
    return data


def detect_snr_levels(window: pd.DataFrame, fractal_span: int = 3) -> list[dict]:
    closed_len = len(window) - 1
    if closed_len < (fractal_span * 2 + 1):
        return []

    snr_levels: list[dict] = []
    for idx in range(fractal_span, closed_len - fractal_span):
        left_slice = window.iloc[idx - fractal_span : idx]
        right_slice = window.iloc[idx + 1 : idx + fractal_span + 1]

        curr_high = float(window["high"].iloc[idx])
        curr_low = float(window["low"].iloc[idx])

        if curr_high > float(left_slice["high"].max()) and curr_high >= float(right_slice["high"].max()):
            snr_levels.append({"type": "RESISTANCE", "price": round(curr_high, 2)})

        if curr_low < float(left_slice["low"].min()) and curr_low <= float(right_slice["low"].min()):
            snr_levels.append({"type": "SUPPORT", "price": round(curr_low, 2)})

    return snr_levels


def _check_snr_confluence(
    zone_type: str,
    proximal: float,
    distal: float,
    snr_levels: list[dict],
) -> tuple[bool, float | None]:
    target_snr_type = "SUPPORT" if zone_type == "DEMAND" else "RESISTANCE"
    max_gap = SNR_PROXIMITY_PIPS * PIP_SIZE
    low_bound = min(proximal, distal) - max_gap
    high_bound = max(proximal, distal) + max_gap

    best_snr: float | None = None
    best_dist = float("inf")

    for snr in snr_levels:
        if snr["type"] != target_snr_type:
            continue
        price = snr["price"]
        if low_bound <= price <= high_bound:
            dist = abs(price - proximal)
            if dist < best_dist:
                best_dist = dist
                best_snr = price

    return (best_snr is not None), best_snr


def evaluate_zone_mitigation(
    subsequent_df: pd.DataFrame,
    zone_type: str,
    proximal: float,
    distal: float,
) -> dict:
    zone_width = abs(proximal - distal)
    if zone_width <= 0 or subsequent_df.empty:
        return {
            "status": "FRESH",
            "touch_count": 0,
            "max_penetration_pct": 0.0,
        }

    touch_count = 0
    max_penetration = 0.0
    currently_inside = False

    closed_subsequent = subsequent_df.iloc[:-1] if len(subsequent_df) > 1 else subsequent_df.iloc[0:0]
    for _, row in closed_subsequent.iterrows():
        if zone_type == "DEMAND":
            if float(row["close"]) < distal:
                return {"status": "BROKEN", "touch_count": touch_count, "max_penetration_pct": 100.0}
        else:
            if float(row["close"]) > distal:
                return {"status": "BROKEN", "touch_count": touch_count, "max_penetration_pct": 100.0}

    for _, row in subsequent_df.iterrows():
        if zone_type == "DEMAND":
            if float(row["low"]) <= proximal:
                if not currently_inside:
                    touch_count += 1
                    currently_inside = True
                penetration = (proximal - float(row["low"])) / zone_width
                max_penetration = max(max_penetration, penetration)
            else:
                currently_inside = False
        else:
            if float(row["high"]) >= proximal:
                if not currently_inside:
                    touch_count += 1
                    currently_inside = True
                penetration = (float(row["high"]) - proximal) / zone_width
                max_penetration = max(max_penetration, penetration)
            else:
                currently_inside = False

    penetration_pct = round(min(max_penetration * 100.0, 100.0), 1)

    if touch_count == 0:
        status = "FRESH"
    elif touch_count == 1 and penetration_pct < 85.0:
        status = "MITIGATED_1X"
    else:
        status = "EXHAUSTED"

    return {
        "status": status,
        "touch_count": touch_count,
        "max_penetration_pct": penetration_pct,
    }


def detect_unbroken_fvgs(
    window: pd.DataFrame,
    tf_name: str,
    snr_levels: list[dict],
) -> list[dict]:
    closed_len = len(window) - 1
    if closed_len < 5:
        return []

    fvgs: list[dict] = []
    for idx in range(2, closed_len):
        c1 = window.iloc[idx - 2]
        c2 = window.iloc[idx - 1]
        c3 = window.iloc[idx]

        atr_val = float(c2["atr"])
        if atr_val <= 0:
            continue

        if float(c3["low"]) > float(c1["high"]):
            gap_size = float(c3["low"]) - float(c1["high"])
            if gap_size < (FVG_MIN_ATR_MULT * atr_val):
                continue
            zone_type = "DEMAND"
            proximal = round(float(c3["low"]), 2)
            distal = round(float(c1["high"]), 2)
        elif float(c3["high"]) < float(c1["low"]):
            gap_size = float(c1["low"]) - float(c3["high"])
            if gap_size < (FVG_MIN_ATR_MULT * atr_val):
                continue
            zone_type = "SUPPLY"
            proximal = round(float(c3["high"]), 2)
            distal = round(float(c1["low"]), 2)
        else:
            continue

        subsequent_data = window.iloc[idx + 1 :]
        mitigation_info = evaluate_zone_mitigation(subsequent_data, zone_type, proximal, distal)

        if mitigation_info["status"] in ("BROKEN", "EXHAUSTED"):
            continue

        has_snr, snr_price = _check_snr_confluence(zone_type, proximal, distal, snr_levels)

        fvgs.append({
            "tf": tf_name,
            "kind": "FVG",
            "type": zone_type,
            "pattern": "FVG",
            "status": mitigation_info["status"],
            "touches": mitigation_info["touch_count"],
            "penetration_pct": mitigation_info["max_penetration_pct"],
            "proximal": proximal,
            "distal": distal,
            "has_snr_confluence": has_snr,
            "snr_price": snr_price,
            "has_fvg_confluence": True,
        })

    return fvgs


def detect_snd_zones(
    window: pd.DataFrame,
    tf_name: str,
    snr_levels: list[dict],
    fvg_zones: list[dict],
    max_base_candles: int = 3,
) -> list[dict]:
    closed_len = len(window) - 1
    if closed_len < 15:
        return []

    zones: list[dict] = []
    i = 1

    while i < closed_len - 2:
        found_zone = False
        for base_len in range(1, max_base_candles + 1):
            leg_out_idx = i + base_len
            if leg_out_idx >= closed_len:
                break

            base_slice = window.iloc[i:leg_out_idx]
            leg_out = window.iloc[leg_out_idx]
            leg_in = window.iloc[i - 1]

            is_valid_base = (
                (base_slice["body_ratio"] <= 0.45).all()
                and (base_slice["range"] <= 1.2 * base_slice["atr"]).all()
            )
            if not is_valid_base:
                continue

            is_strong_leg_out = (
                float(leg_out["body"]) >= 1.5 * float(leg_out["atr"])
                and float(leg_out["body_ratio"]) >= 0.60
            )
            if not is_strong_leg_out:
                continue

            is_bullish_out = float(leg_out["close"]) > float(leg_out["open"])
            is_bullish_in = float(leg_in["close"]) > float(leg_in["open"])

            if is_bullish_out:
                zone_type = "DEMAND"
                pattern = "RBR" if is_bullish_in else "DBR"
                proximal = round(float(base_slice[["open", "close"]].max().max()), 2)
                distal = round(float(min(base_slice["low"].min(), leg_out["low"])), 2)
            else:
                zone_type = "SUPPLY"
                pattern = "DBD" if not is_bullish_in else "RBD"
                proximal = round(float(base_slice[["open", "close"]].min().min()), 2)
                distal = round(float(max(base_slice["high"].max(), leg_out["high"])), 2)

            subsequent_data = window.iloc[leg_out_idx + 1 :]
            mitigation_info = evaluate_zone_mitigation(subsequent_data, zone_type, proximal, distal)

            if mitigation_info["status"] in ("BROKEN", "EXHAUSTED"):
                continue

            has_snr, snr_price = _check_snr_confluence(zone_type, proximal, distal, snr_levels)

            pad = 15.0 * PIP_SIZE
            z_low = min(proximal, distal) - pad
            z_high = max(proximal, distal) + pad
            has_fvg = any(
                f["type"] == zone_type
                and not (max(f["proximal"], f["distal"]) < z_low or min(f["proximal"], f["distal"]) > z_high)
                for f in fvg_zones
            )

            zones.append({
                "tf": tf_name,
                "kind": "SND",
                "type": zone_type,
                "pattern": pattern,
                "status": mitigation_info["status"],
                "touches": mitigation_info["touch_count"],
                "penetration_pct": mitigation_info["max_penetration_pct"],
                "proximal": proximal,
                "distal": distal,
                "has_snr_confluence": has_snr,
                "snr_price": snr_price,
                "has_fvg_confluence": has_fvg,
            })
            i = leg_out_idx
            found_zone = True
            break

        if not found_zone:
            i += 1

    return zones


def analyze_tf_context(window: pd.DataFrame, active_fvgs: list[dict]) -> dict:
    last_close = float(window["close"].iloc[-2])
    ema50 = float(window["ema50"].iloc[-2])
    ema200 = float(window["ema200"].iloc[-2])

    if last_close > ema50 > ema200:
        trend = "BULLISH 🟢"
    elif last_close < ema50 < ema200:
        trend = "BEARISH 🔴"
    else:
        trend = "SIDEWAYS ⚪"

    recent_high = float(window["high"].iloc[-17:-2].max())
    recent_low = float(window["low"].iloc[-17:-2].min())

    if last_close > recent_high:
        bos_status = "BOS Bullish"
    elif last_close < recent_low:
        bos_status = "BOS Bearish"
    else:
        bos_status = "Belum ada BOS"

    bull_fvgs = [f for f in active_fvgs if f["type"] == "DEMAND"]
    bear_fvgs = [f for f in active_fvgs if f["type"] == "SUPPLY"]

    if bull_fvgs and bear_fvgs:
        fvg_status = f"FVG Aktif ({len(bull_fvgs)}B/{len(bear_fvgs)}S)"
    elif bull_fvgs:
        fvg_status = f"Bullish FVG ({len(bull_fvgs)})"
    elif bear_fvgs:
        fvg_status = f"Bearish FVG ({len(bear_fvgs)})"
    else:
        fvg_status = ""

    return {
        "trend": trend,
        "bos": bos_status,
        "fvg": fvg_status,
    }


def check_ltf_confirmation(
    confirm_window: pd.DataFrame,
    zone_type: str,
    proximal: float,
    distal: float,
    current_price: float,
    is_quick_scalp: bool = False,
) -> bool:
    if len(confirm_window) < 6:
        return False

    recent = confirm_window.iloc[-4:-1]
    prev_closed = confirm_window.iloc[-3]
    last_closed = confirm_window.iloc[-2]

    candle_range = float(last_closed["high"]) - float(last_closed["low"])
    if candle_range <= 0:
        return False

    near_pad = (6 * PIP_SIZE) if is_quick_scalp else (3 * PIP_SIZE)
    wick_thresh = 0.45 if is_quick_scalp else 0.55

    if zone_type == "DEMAND":
        in_or_near_zone = distal <= current_price <= proximal + near_pad
        touched_zone = (float(recent["low"].min()) <= proximal + near_pad) and (
            float(recent["low"].min()) >= distal - (2 * PIP_SIZE)
        )
        bullish_engulf = float(last_closed["close"]) > float(prev_closed["high"])
        lower_wick = min(float(last_closed["open"]), float(last_closed["close"])) - float(last_closed["low"])
        strong_rejection = (float(last_closed["close"]) > float(last_closed["open"])) and (
            lower_wick / candle_range >= wick_thresh
        )
        return in_or_near_zone and touched_zone and (bullish_engulf or strong_rejection)
    else:
        in_or_near_zone = proximal - near_pad <= current_price <= distal
        touched_zone = (float(recent["high"].max()) >= proximal - near_pad) and (
            float(recent["high"].max()) <= distal + (2 * PIP_SIZE)
        )
        bearish_engulf = float(last_closed["close"]) < float(prev_closed["low"])
        upper_wick = float(last_closed["high"]) - max(float(last_closed["open"]), float(last_closed["close"]))
        strong_rejection = (float(last_closed["close"]) < float(last_closed["open"])) and (
            upper_wick / candle_range >= wick_thresh
        )
        return in_or_near_zone and touched_zone and (bearish_engulf or strong_rejection)


def _compute_confluence_score(zone: dict) -> int:
    score = 1
    if zone["kind"] == "SND":
        if zone.get("has_snr_confluence"):
            score += 2
        if zone.get("has_fvg_confluence"):
            score += 1
    elif zone["kind"] == "FVG":
        if zone.get("has_snr_confluence"):
            score += 1
    return score


def evaluate_zone_setup(
    zone: dict,
    current_price: float,
    profile: dict,
    confirm_window: pd.DataFrame,
    all_zones: list[dict],
    htf_trend: str,
) -> dict | None:
    if zone["status"] not in ("FRESH", "MITIGATED_1X"):
        return None

    zone_type = zone["type"]
    proximal = zone["proximal"]
    distal = zone["distal"]
    min_dist_pips = profile.get("min_dist_pips", MIN_DIST_PIPS)
    max_dist_pips = profile["max_dist_pips"]
    is_quick_scalp = profile.get("is_quick_scalp", False)

    is_counter_trend = (
        (zone_type == "DEMAND" and "BEARISH" in htf_trend)
        or (zone_type == "SUPPLY" and "BULLISH" in htf_trend)
    )
    if profile.get("strict_trend", False) and is_counter_trend:
        return None
    if is_counter_trend and zone["status"] != "FRESH":
        return None

    is_confirmed = check_ltf_confirmation(
        confirm_window,
        zone_type,
        proximal,
        distal,
        current_price,
        is_quick_scalp=is_quick_scalp,
    )

    if is_confirmed:
        limit_price = round(current_price, 2)
        dist_pips = 0.0
    else:
        if zone_type == "DEMAND" and proximal >= current_price:
            return None
        if zone_type == "SUPPLY" and proximal <= current_price:
            return None

        dist_pips = abs(current_price - proximal) / PIP_SIZE
        if not (min_dist_pips <= dist_pips <= max_dist_pips):
            return None

        # Pada Quick Scalp saat pullback, gunakan entry lebih dekat ke bibir/75% area agar tidak tertinggal pantulan
        if is_quick_scalp:
            limit_price = round((proximal * 0.75) + (distal * 0.25), 2)
        else:
            limit_price = round((proximal + distal) / 2.0, 2)

    buffer_pips = profile["buffer_pips"]
    direction = 1 if zone_type == "DEMAND" else -1

    struct_sl = distal - direction * (buffer_pips * PIP_SIZE)
    struct_sl_pips = round(abs(limit_price - struct_sl) / PIP_SIZE, 1)

    if struct_sl_pips > profile["max_sl_pips"]:
        return None

    effective_min_pips = max(struct_sl_pips, profile["min_sl_pips"])
    sl_min = round(limit_price - direction * (effective_min_pips * PIP_SIZE), 2)

    extra_buffer_pips = round(buffer_pips * 2.5, 1)
    raw_max_pips = max(effective_min_pips + 5.0, struct_sl_pips + extra_buffer_pips)
    clamped_max_pips = min(raw_max_pips, profile["max_sl_pips"])
    sl_max = round(limit_price - direction * (clamped_max_pips * PIP_SIZE), 2)

    recent_slice = confirm_window.iloc[-45:-1]
    if zone_type == "DEMAND":
        swing_candidates = recent_slice[
            recent_slice["high"] >= limit_price + (effective_min_pips * 1.1 * PIP_SIZE)
        ]["high"]
        default_tp1_pips = 30.0 if is_quick_scalp else (effective_min_pips * 1.5)
        tp1_price = (
            round(float(swing_candidates.min()), 2)
            if not swing_candidates.empty
            else round(limit_price + (default_tp1_pips * PIP_SIZE), 2)
        )
        tp1_label = "Swing High"

        opposing = sorted(
            [
                z for z in all_zones
                if z["type"] == "SUPPLY"
                and z["status"] in ("FRESH", "MITIGATED_1X")
                and z["proximal"] > tp1_price + (8 * PIP_SIZE)
            ],
            key=lambda item: item["proximal"],
        )
    else:
        swing_candidates = recent_slice[
            recent_slice["low"] <= limit_price - (effective_min_pips * 1.1 * PIP_SIZE)
        ]["low"]
        default_tp1_pips = 30.0 if is_quick_scalp else (effective_min_pips * 1.5)
        tp1_price = (
            round(float(swing_candidates.max()), 2)
            if not swing_candidates.empty
            else round(limit_price - (default_tp1_pips * PIP_SIZE), 2)
        )
        tp1_label = "Swing Low"

        opposing = sorted(
            [
                z for z in all_zones
                if z["type"] == "DEMAND"
                and z["status"] in ("FRESH", "MITIGATED_1X")
                and z["proximal"] < tp1_price - (8 * PIP_SIZE)
            ],
            key=lambda item: item["proximal"],
            reverse=True,
        )

    tp1_pips = abs(tp1_price - limit_price) / PIP_SIZE

    if is_quick_scalp:
        min_tp2_pips = max(40.0, tp1_pips + 10.0)
        wall_guard_mult = 1.05
    else:
        min_tp2_pips = max(effective_min_pips * 1.5, tp1_pips + 15.0)
        wall_guard_mult = 1.4

    if len(opposing) >= 1:
        wall_1 = opposing[0]
        wall_1_pips = abs(wall_1["proximal"] - limit_price) / PIP_SIZE
        if wall_1_pips < (effective_min_pips * wall_guard_mult):
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

    step_tp3 = 12.0 if is_quick_scalp else max(15.0, effective_min_pips * 0.8)
    min_tp3_pips = max(50.0 if is_quick_scalp else 0.0, tp2_pips + step_tp3)
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
        "confluence_score": _compute_confluence_score(zone),
        "is_confirmed": is_confirmed,
        "dist_pips": round(dist_pips, 1),
        "limit_price": limit_price,
        "sl_min": sl_min,
        "sl_max": sl_max,
        "tp1": (tp1_label, tp1_price),
        "tp2": (tp2_label, tp2_price),
        "tp3": (tp3_label, tp3_price),
    }


def _build_dynamic_notes(
    trend_tf: str,
    active_tf: str,
    zone: dict,
    tf_summaries: dict,
    dist_pips: float,
    tp1: tuple[str, float],
    tp2: tuple[str, float],
) -> tuple[str, str]:
    is_demand = zone["type"] == "DEMAND"
    arah_teks = "pantulan naik" if is_demand else "pantulan turun"
    htf_trend = tf_summaries.get(trend_tf, {}).get("trend", "SIDEWAYS ⚪")
    active_info = tf_summaries.get(active_tf, {})

    if zone["kind"] == "FVG":
        base_desc = f"FVG {zone['type']} unbroken ({zone['status']}) di {active_tf}"
    else:
        base_desc = f"zona {zone['type']} {zone['pattern']} ({zone['status']}) di {active_tf}"

    alasan_parts = [base_desc]

    if zone.get("has_snr_confluence") and zone.get("snr_price") is not None:
        alasan_parts.append(f"berimpit dengan SNR di {zone['snr_price']:.2f} (konfluensi kuat)")
    if zone["kind"] == "SND" and zone.get("has_fvg_confluence"):
        alasan_parts.append("didukung FVG unbroken")
    if active_info.get("bos", "").startswith("BOS "):
        alasan_parts.append(f"terkonfirmasi {active_info['bos']}")

    alasan_entry = f"Menunggu {arah_teks} pada {', '.join(alasan_parts)}."

    waspada_list = []
    if dist_pips >= 200.0:
        waspada_list.append(
            f"jarak zona masih cukup jauh ({round(dist_pips)} pips), pantau reaksi candle saat harga tiba agar tidak tertembus momentum berita"
        )
    if "SIDEWAYS" in htf_trend:
        waspada_list.append(f"tren utama {trend_tf} masih Sideways (momentum belum searah penuh)")
    elif (is_demand and "BEARISH" in htf_trend) or (not is_demand and "BULLISH" in htf_trend):
        waspada_list.append(f"posisi melawan tren {trend_tf} ({htf_trend}) — wajib disiplin SL")

    if zone["status"] == "MITIGATED_1X":
        waspada_list.append(
            f"area sudah tersentuh 1x (penetrasi {zone['penetration_pct']}%), rawan sapuan ekor"
        )

    waspada_list.append(
        f"amankan sebagian profit di TP 1 ({tp1[1]:.2f}) sebelum harga menyentuh {tp2[0]} di {tp2[1]:.2f}"
    )
    waspadai = "; ".join(waspada_list)
    waspadai = waspadai[0].upper() + waspadai[1:] + "."

    return alasan_entry, waspadai


def run_full_analysis(mode: str) -> str:
    mode_key = mode.upper()
    profile = MODE_PROFILES[mode_key]
    mode_label = profile.get("label", mode_key).upper()
    tf_order = profile["timeframes"]
    ttl_seconds = profile.get("cache_ttl", 45)

    dataset = fetch_mode_dataset(tf_order, ttl_seconds=ttl_seconds)
    windows: dict[str, pd.DataFrame] = {}
    for tf in tf_order:
        windows[tf] = _prepare_window(dataset[tf], tf)

    current_price = float(windows[tf_order[-1]]["close"].iloc[-1])

    tf_summaries: dict[str, dict] = {}
    all_zones: list[dict] = []

    for tf in tf_order:
        win = windows[tf]
        snr_levels = detect_snr_levels(win)
        fvg_zones = detect_unbroken_fvgs(win, tf, snr_levels)
        snd_zones = detect_snd_zones(win, tf, snr_levels, fvg_zones)

        tf_summaries[tf] = analyze_tf_context(win, fvg_zones)
        all_zones.extend(snd_zones)
        all_zones.extend(fvg_zones)

    confirm_window = windows[profile["confirm_tf"]]
    htf_trend = tf_summaries.get(profile["trend_tf"], {}).get("trend", "SIDEWAYS ⚪")
    selected_setup = None
    selected_tf = None

    for tf in profile["zone_tfs"]:
        tf_zones = [z for z in all_zones if z["tf"] == tf]
        valid_candidates = []
        for z in tf_zones:
            evaluated = evaluate_zone_setup(
                z, current_price, profile, confirm_window, all_zones, htf_trend
            )
            if evaluated is not None:
                valid_candidates.append(evaluated)

        if valid_candidates:
            valid_candidates.sort(
                key=lambda item: (
                    not item["is_confirmed"],
                    -item["confluence_score"],
                    item["zone"]["status"] != "FRESH",
                    item["dist_pips"],
                )
            )
            selected_setup = valid_candidates[0]
            selected_tf = tf
            break

    if selected_setup is None or selected_tf is None:
        return format_no_zone_message(mode_label, tf_order, current_price, tf_summaries)

    alasan_entry, waspadai = _build_dynamic_notes(
        trend_tf=profile["trend_tf"],
        active_tf=selected_tf,
        zone=selected_setup["zone"],
        tf_summaries=tf_summaries,
        dist_pips=selected_setup["dist_pips"],
        tp1=selected_setup["tp1"],
        tp2=selected_setup["tp2"],
    )

    return format_locked_radar_message(
        mode=mode_label,
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
