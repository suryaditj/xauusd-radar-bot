import time
import requests
import pandas as pd
from config.settings import (
    TWELVE_DATA_API_KEY,
    SYMBOL,
    TF_TO_TWELVEDATA,
    CACHE_TTL_SECONDS,
)

BASE_URL = "https://api.twelvedata.com/time_series"
_CANDLE_CACHE: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}


class TwelveDataError(Exception):
    """Exception khusus untuk gangguan koneksi atau limit API Twelve Data."""
    pass


def fetch_candles(
    tf: str,
    outputsize: int = 220,
    cache_ttl: int = CACHE_TTL_SECONDS,
) -> pd.DataFrame:
    tf_upper = tf.upper()
    if tf_upper not in TF_TO_TWELVEDATA:
        raise ValueError(f"Timeframe tidak didukung: {tf}")

    if not TWELVE_DATA_API_KEY:
        raise TwelveDataError("TWELVE_DATA_API_KEY belum diatur di GitHub Secrets.")

    cache_key = (SYMBOL, tf_upper)
    now = time.time()

    if cache_key in _CANDLE_CACHE:
        cached_time, cached_df = _CANDLE_CACHE[cache_key]
        if (now - cached_time) < cache_ttl:
            return cached_df.copy()

    params = {
        "symbol": SYMBOL,
        "interval": TF_TO_TWELVEDATA[tf_upper],
        "outputsize": outputsize,
        "apikey": TWELVE_DATA_API_KEY,
        "format": "JSON",
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise TwelveDataError(f"Gagal terhubung ke server data ({tf_upper}): {exc}") from exc

    if payload.get("status") == "error":
        code = payload.get("code", 0)
        msg = payload.get("message", "Unknown API error")
        if code == 429:
            raise TwelveDataError(
                "Batas kuota gratis Twelve Data tercapai (8 request/menit). Tunggu 60 detik lalu coba lagi."
            )
        raise TwelveDataError(f"Error API Twelve Data ({code}): {msg}")

    values = payload.get("values")
    if not values or len(values) < 50:
        raise TwelveDataError(f"Data candle {tf_upper} kosong atau tidak mencukupi.")

    df = pd.DataFrame(values[::-1]).reset_index(drop=True)
    for col in ("open", "high", "low", "close"):
        df[col] = df[col].astype(float)

    df = df[["datetime", "open", "high", "low", "close"]]
    _CANDLE_CACHE[cache_key] = (now, df)
    return df.copy()


def fetch_mode_dataset(
    timeframes: list[str],
    cache_ttl: int = CACHE_TTL_SECONDS,
) -> dict[str, pd.DataFrame]:
    dataset: dict[str, pd.DataFrame] = {}
    for idx, tf in enumerate(timeframes):
        dataset[tf] = fetch_candles(tf, cache_ttl=cache_ttl)
        if idx < len(timeframes) - 1:
            time.sleep(0.4)
    return dataset
