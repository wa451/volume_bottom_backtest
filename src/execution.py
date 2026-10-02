"""Conservative daily OHLC exits; thresholds exclude transaction costs."""
import math


def good(value):
    return value is not None and math.isfinite(value) and value > 0


def find_exit(df, entry, p):
    price = df['Adj Open'].iloc[entry]
    if not good(price) or df.Volume.iloc[entry] <= 0:
        return {'trade_status': 'invalid_entry'}
    highest = price
    pending = None
    mode = p['exit_mode']
    limit = p['holding_period'] if mode in ('holding', 'legacy_close') else p['maximum_holding']
    ma = df['Adj Close'].rolling(p.get('ma_period', 20), min_periods=p.get('ma_period', 20)).mean() if mode == 'ma' else None
    for pos in range(entry, len(df)):
        row = df.iloc[pos]
        if not good(row['Adj Open']) or row.Volume <= 0:
            # Never infer a fill across unobserved sessions. Keep position open and
            # invalidate statistics rather than overlooking a possible stop hit.
            return {'trade_status': 'unresolved_data_gap', 'exit_reason': '保有中OHLC欠損・約定不明', 'gap_date': df.index[pos]}
        open_ = row['Adj Open']
        stop = price * (1 - p['stop_loss']) if p['stop_loss'] else None
        trail = highest * (1 - p.get('trailing_stop', .15)) if mode == 'trailing' else None
        threshold = max(x for x in (stop, trail) if x is not None) if stop is not None or trail is not None else None
        reason = 'trailing_stop' if trail is not None and (stop is None or trail > stop) else 'stop_loss'
        def result(fill, why, when='intraday'):
            return {'trade_status': 'complete', 'exit_position': pos, 'exit_date': df.index[pos], 'exit_price': float(fill), 'exit_reason': why, 'exit_timing': when, 'holding_days': pos - entry + (when != 'open')}
        if threshold is not None and open_ <= threshold:
            return result(open_, reason + '_gap', 'open')
        if pending:
            return result(open_, pending, 'open')
        if mode == 'fixed' and open_ >= price * (1 + p['take_profit']):
            return result(open_, 'take_profit_gap', 'open')
        if not all(good(row[k]) for k in ('Adj High', 'Adj Low', 'Adj Close')):
            return {'trade_status': 'unresolved_data_gap', 'exit_reason': '保有中OHLC欠損・約定不明', 'gap_date': df.index[pos]}
        if threshold is not None and row['Adj Low'] <= threshold:
            return result(threshold, reason)  # Stop before profit if both hit.
        if mode == 'fixed' and row['Adj High'] >= price * (1 + p['take_profit']):
            return result(price * (1 + p['take_profit']), 'take_profit')
        if mode == 'legacy_close' and pos == entry + limit:
            return result(row['Adj Close'], 'legacy_holding_close', 'close')
        highest = max(highest, row['Adj High'])  # Active from next session only.
        if mode != 'legacy_close' and pos - entry + 1 >= limit:
            pending = 'holding_period' if mode == 'holding' else 'maximum_holding'
        elif mode == 'ma' and row['Adj Close'] < ma.iloc[pos]:
            pending = 'moving_average'
    return {'trade_status': 'open_at_end', 'exit_reason': '期間末未決済'}
