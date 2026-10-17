"""Small, deterministic indicator implementations used by FeatureSet V0/V1 Core."""

from __future__ import annotations

from typing import cast

import numpy as np
import pandas as pd


def sma[FrameLike: (pd.Series, pd.DataFrame)](values: FrameLike, window: int) -> FrameLike:
    return values.rolling(window=window, min_periods=window).mean()


def ema[FrameLike: (pd.Series, pd.DataFrame)](values: FrameLike, span: int) -> FrameLike:
    return values.ewm(span=span, adjust=False, min_periods=span).mean()


def cross_flags[FrameLike: (pd.Series, pd.DataFrame)](
    short: FrameLike, long: FrameLike
) -> tuple[FrameLike, FrameLike]:
    valid = short.notna() & long.notna() & short.shift(1).notna() & long.shift(1).notna()
    golden = ((short > long) & (short.shift(1) <= long.shift(1))).astype(float).where(valid)
    dead = ((short < long) & (short.shift(1) >= long.shift(1))).astype(float).where(valid)
    return golden, dead


def days_since_event[FrameLike: (pd.Series, pd.DataFrame)](flag: FrameLike) -> FrameLike:
    """Trading-row count since the most recent true event; missing before the first."""
    if isinstance(flag, pd.DataFrame):
        data = flag.to_numpy(dtype=float)
        result = np.full(data.shape, np.nan, dtype=float)
        wide_elapsed = np.full(data.shape[1], -1, dtype="int64")
        for position, row in enumerate(data):
            valid = ~np.isnan(row)
            event = valid & (row == 1)
            wide_elapsed[event] = 0
            wide_elapsed[valid & ~event & (wide_elapsed >= 0)] += 1
            known = valid & (wide_elapsed >= 0)
            result[position, known] = wide_elapsed[known]
        return pd.DataFrame(result, index=flag.index, columns=flag.columns)
    result = np.full(len(flag), np.nan, dtype=float)
    elapsed: int | None = None
    for position, value in enumerate(flag.to_numpy(dtype=float)):
        if pd.isna(value):
            continue
        if value == 1:
            elapsed = 0
        elif elapsed is not None:
            elapsed += 1
        if elapsed is not None:
            result[position] = float(elapsed)
    return pd.Series(result, index=flag.index, dtype=float)


def macd[FrameLike: (pd.Series, pd.DataFrame)](
    close: FrameLike, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[FrameLike, FrameLike, FrameLike]:
    fast_line = ema(close, fast)
    slow_line = ema(close, slow)
    value = fast_line - slow_line
    signal_line = ema(value, signal)
    return value, signal_line, value - signal_line


def _wilder_average[FrameLike: (pd.Series, pd.DataFrame)](
    values: FrameLike, period: int
) -> FrameLike:
    if isinstance(values, pd.DataFrame):
        if period <= 0:
            raise ValueError("Matrix Wilder period must be positive")
        data = values.astype(float).to_numpy()
        result = np.full(data.shape, np.nan, dtype=float)
        seeds = np.full(data.shape[1], len(data), dtype="int64")
        previous = np.zeros(data.shape[1], dtype=float)
        for column in range(data.shape[1]):
            positions = np.flatnonzero(~np.isnan(data[:, column]))
            if len(positions) < period:
                continue
            seed = int(positions[period - 1])
            seeds[column] = seed
            # Preserve the original one-column NumPy mean and operation order.
            previous[column] = float(np.mean(data[positions[:period], column]))
            result[seed, column] = previous[column]
        for position, row in enumerate(data):
            active = (position > seeds) & ~np.isnan(row)
            previous[active] = ((period - 1) * previous[active] + row[active]) / period
            result[position, active] = previous[active]
        return pd.DataFrame(result, index=values.index, columns=values.columns)
    data = values.astype(float).to_numpy()
    result = np.full(data.shape, np.nan, dtype=float)
    valid_positions = np.flatnonzero(~np.isnan(data))
    if len(valid_positions) < period:
        return pd.Series(result, index=values.index, dtype=float)
    seed_positions = valid_positions[:period]
    seed_index = int(seed_positions[-1])
    previous = float(np.mean(data[seed_positions]))
    result[seed_index] = previous
    for index in range(seed_index + 1, len(data)):
        value = data[index]
        if np.isnan(value):
            continue
        previous = ((period - 1) * previous + value) / period
        result[index] = previous
    return pd.Series(result, index=values.index, dtype=float)


def rsi[FrameLike: (pd.Series, pd.DataFrame)](close: FrameLike, period: int = 14) -> FrameLike:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    average_gain = _wilder_average(gain, period)
    average_loss = _wilder_average(loss, period)
    relative_strength = average_gain / average_loss
    value = 100 - (100 / (1 + relative_strength))
    value = value.mask((average_loss == 0) & (average_gain > 0), 100.0)
    return value.mask((average_loss == 0) & (average_gain == 0), 50.0)


def bollinger[FrameLike: (pd.Series, pd.DataFrame)](
    close: FrameLike, window: int = 20, standard_deviations: float = 2.0
) -> tuple[FrameLike, FrameLike, FrameLike, FrameLike, FrameLike]:
    middle = sma(close, window)
    deviation = close.rolling(window=window, min_periods=window).std(ddof=0)
    upper = middle + standard_deviations * deviation
    lower = middle - standard_deviations * deviation
    width = (upper - lower) / middle
    percent_b = (close - lower) / (upper - lower)
    percent_b = percent_b.mask((upper - lower) == 0, 0.5)
    return middle, upper, lower, percent_b, width


def true_range[FrameLike: (pd.Series, pd.DataFrame)](
    high: FrameLike, low: FrameLike, close: FrameLike
) -> FrameLike:
    previous_close = close.shift(1)
    if isinstance(close, pd.DataFrame):
        result = cast(
            pd.DataFrame,
            np.fmax(
                np.fmax(high - low, (high - previous_close).abs()),
                (low - previous_close).abs(),
            ),
        )
        if not result.empty:
            result.iloc[0] = np.nan
        return result
    components = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()], axis=1
    )
    result = components.max(axis=1, skipna=True)
    if not result.empty:
        result.iloc[0] = np.nan
    return result


def atr[FrameLike: (pd.Series, pd.DataFrame)](
    high: FrameLike, low: FrameLike, close: FrameLike, period: int = 14
) -> FrameLike:
    return _wilder_average(true_range(high, low, close), period)


def directional_movement[FrameLike: (pd.Series, pd.DataFrame)](
    high: FrameLike, low: FrameLike, close: FrameLike, period: int = 14
) -> tuple[FrameLike, FrameLike, FrameLike]:
    upward = high.diff()
    downward = -low.diff()
    plus_dm = upward.where((upward > downward) & (upward > 0), 0.0)
    minus_dm = downward.where((downward > upward) & (downward > 0), 0.0)
    plus_dm.iloc[0] = np.nan
    minus_dm.iloc[0] = np.nan
    average_true_range = atr(high, low, close, period)
    plus_di = 100 * _wilder_average(plus_dm, period) / average_true_range
    minus_di = 100 * _wilder_average(minus_dm, period) / average_true_range
    denominator = plus_di + minus_di
    dx = 100 * (plus_di - minus_di).abs() / denominator
    dx = dx.mask(denominator == 0, 0.0)
    adx = _wilder_average(dx, period)
    return plus_di, minus_di, adx


def obv[FrameLike: (pd.Series, pd.DataFrame)](close: FrameLike, volume: FrameLike) -> FrameLike:
    difference = close.diff()
    direction = difference.gt(0).astype(float) - difference.lt(0).astype(float)
    cumulative = (direction * volume).cumsum()
    if isinstance(close, pd.DataFrame):
        return cumulative.astype(float)
    return pd.Series(cumulative, index=close.index, dtype=float)


def mfi[FrameLike: (pd.Series, pd.DataFrame)](
    high: FrameLike, low: FrameLike, close: FrameLike, volume: FrameLike, period: int = 14
) -> FrameLike:
    typical_price = (high + low + close) / 3
    raw_flow = typical_price * volume
    direction = typical_price.diff()
    positive = raw_flow.where(direction > 0, 0.0)
    negative = raw_flow.where(direction < 0, 0.0)
    positive.iloc[0] = np.nan
    negative.iloc[0] = np.nan
    positive_sum = positive.rolling(period, min_periods=period).sum()
    negative_sum = negative.rolling(period, min_periods=period).sum()
    ratio = positive_sum / negative_sum
    value = 100 - 100 / (1 + ratio)
    value = value.mask((negative_sum == 0) & (positive_sum > 0), 100.0)
    return value.mask((negative_sum == 0) & (positive_sum == 0), 50.0)
