import os

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "").strip()
SESSION_DURATION_MINUTES = int(os.getenv("SESSION_DURATION_MINUTES", "60"))

SYMBOL = "XAU/USD"
PIP_SIZE = 0.10

TF_TO_TWELVEDATA = {
    "D1": "1day",
    "H4": "4h",
    "H1": "1h",
    "M30": "30min",
    "M15": "15min",
    "M5": "5min",
    "M1": "1min",
}

LOOKBACK_BY_TF = {
    "D1": 30,    # ~1.5 bulan
    "H4": 45,    # ~7.5 hari perdagangan
    "H1": 72,    # ~3 hari perdagangan
    "M30": 96,   # ~2 hari perdagangan
    "M15": 96,   # ~24 jam
    "M5": 120,   # ~10 jam
    "M1": 150,   # ~2.5 jam
}

SNR_PROXIMITY_PIPS = 20.0
FVG_MIN_ATR_MULT = 0.8

MODE_PROFILES = {
    "INTRADAY": {
        "label": "Intra Day",
        "timeframes": ["D1", "H4", "M15"],
        "trend_tf": "D1",
        "zone_tfs": ["D1", "H4", "M15"],
        "confirm_tf": "M15",
        "min_sl_pips": 70.0,
        "max_sl_pips": 180.0,
        "buffer_pips": 10.0,
        "min_dist_pips": 15.0,
        "max_dist_pips": 450.0,
        "cache_ttl": 45,
        "strict_trend": False,
        "is_quick_scalp": False,
    },
    "SCALPING": {
        "label": "Scalping",
        "timeframes": ["H1", "M15", "M5"],
        "trend_tf": "H1",
        "zone_tfs": ["H1", "M15", "M5"],
        "confirm_tf": "M5",
        "min_sl_pips": 35.0,
        "max_sl_pips": 90.0,
        "buffer_pips": 5.0,
        "min_dist_pips": 15.0,
        "max_dist_pips": 300.0,
        "cache_ttl": 45,
        "strict_trend": False,
        "is_quick_scalp": False,
    },
    "QUICK_SCALP_1": {
        "label": "Quick Scalp 1",
        "timeframes": ["M30", "M15", "M5"],
        "trend_tf": "M30",
        "zone_tfs": ["M30", "M15", "M5"],
        "confirm_tf": "M5",
        "min_sl_pips": 30.0,
        "max_sl_pips": 50.0,
        "buffer_pips": 4.0,
        "min_dist_pips": 5.0,
        "max_dist_pips": 300.0,
        "cache_ttl": 15,
        "strict_trend": False,
        "is_quick_scalp": True,
    },
    "QUICK_SCALP_2": {
        "label": "Quick Scalp 2",
        "timeframes": ["M15", "M5", "M1"],
        "trend_tf": "M15",
        "zone_tfs": ["M15", "M5"],
        "confirm_tf": "M1",
        "min_sl_pips": 30.0,
        "max_sl_pips": 50.0,
        "buffer_pips": 3.0,
        "min_dist_pips": 5.0,
        "max_dist_pips": 300.0,
        "cache_ttl": 15,
        "strict_trend": False,
        "is_quick_scalp": True,
    },
}

CACHE_TTL_SECONDS = 45
MIN_DIST_PIPS = 15.0
MAX_DIST_PIPS = 450.0
