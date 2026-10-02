"""Cash-constrained, equal-budget portfolios; no future trade filtering."""
import numpy as np
import pandas as pd
from .execution import good


def trade_metrics(trades, curve, initial):
    nav = curve.equity.to_numpy(float)
    daily = pd.Series(np.r_[initial, nav]).pct_change().dropna()
    dd = nav / np.maximum.accumulate(np.r_[initial, nav])[1:] - 1
    closed = [t for t in trades if t['trade_status'] == 'complete']
    returns = np.array([t['return'] for t in closed])
    pnl = np.array([t['pnl'] for t in closed])
    wins, losses = returns[returns > 0], returns[returns < 0]
    sd = daily.std(ddof=1)
    downside = np.sqrt(np.mean(np.minimum(daily, 0) ** 2)) if len(daily) else 0
    total = nav[-1] / initial - 1 if len(nav) else 0
    cagr = (1 + total) ** (252 / len(nav)) - 1 if len(nav) and total > -1 else None
    def ratio(a, b):
        return float(a / b) if b and np.isfinite(b) else None
    streaks = {True: 0, False: 0}
    last, length = None, 0
    for ret in returns:
        positive = ret > 0
        if ret == 0:
            last, length = None, 0
            continue
        length = length + 1 if last == positive else 1
        streaks[positive] = max(streaks[positive], length)
        last = positive
    positive_pnl = pnl[pnl > 0]
    top = np.sort(positive_pnl)[-max(1, int(np.ceil(len(pnl) * .1))):]
    result = {'benchmark_coverage': float(curve.benchmark.notna().mean()), 'total_return': total, 'cagr': cagr, 'max_drawdown': float(dd.min()) if len(dd) else 0,
              'num_trades': len(closed), 'num_positions': len(trades), 'open_positions': sum(t['trade_status'] != 'complete' for t in trades),
              'win_rate': float(np.mean(returns > 0)) if len(returns) else None,
              'average_win': float(wins.mean()) if len(wins) else None, 'average_loss': float(losses.mean()) if len(losses) else None,
              'payoff_ratio': ratio(wins.mean() if len(wins) else 0, abs(losses.mean()) if len(losses) else 0),
              'profit_factor': ratio(positive_pnl.sum(), abs(pnl[pnl < 0].sum())),
              'sharpe_ratio': ratio(daily.mean() * np.sqrt(252), sd), 'sortino_ratio': ratio(daily.mean() * np.sqrt(252), downside),
              'average_holding_days': float(np.mean([t['holding_days'] for t in closed])) if closed else None,
              'expectancy': float(returns.mean()) if len(returns) else None, 'median_return': float(np.median(returns)) if len(returns) else None,
              'calmar_ratio': ratio(cagr or 0, abs(dd.min()) if len(dd) else 0), 'maximum_wins': streaks[True], 'maximum_losses': streaks[False],
              'top_10_profit_dependency': ratio(top.sum(), positive_pnl.sum()), 'profit_factor_no_losses': bool(len(positive_pnl) and not (pnl < 0).any())}
    return result


def simulate(candidates, prices, sessions, settings, costs, benchmark=None):
    initial, maximum = settings['initial_capital'], settings['max_positions']
    cash, previous_nav = initial, initial
    active, completed, rows = {}, [], []
    ignored = {'capacity_or_duplicate': 0, 'invalid_open': 0, 'cash': 0}
    by_date = {}
    for trade in candidates:
        by_date.setdefault(pd.Timestamp(trade['entry_date']), []).append(trade)
    if not candidates:
        curve = pd.DataFrame({'date': sessions, 'equity': initial, 'cash': initial, 'positions': 0, 'benchmark': np.nan, 'drawdown': 0.})
        if benchmark is not None:
            quotes = benchmark.reindex(sessions)
            base = quotes['Adj Open'].iloc[0]
            if good(base):
                curve['benchmark'] = (quotes['Adj Close'] / base * initial).to_numpy()
        metrics = trade_metrics([], curve, initial)
        metrics.update(data_gap_marks=0, unresolved_positions=0, metrics_valid=True, **ignored)
        return metrics, curve, []
    buy = (1 + costs['slippage_rate']) * (1 + costs['buy_cost_rate'])
    sell = (1 - costs['slippage_rate']) * (1 - costs['sell_cost_rate'])
    benchmark_base = benchmark.at[sessions[0], 'Adj Open'] if benchmark is not None and sessions[0] in benchmark.index else None
    if not good(benchmark_base):
        benchmark_base = None
    data_gaps = 0
    def close(ticker, position):
        nonlocal cash
        trade = position['trade']
        proceeds = position['quantity'] * trade['exit_price'] * sell
        cash += proceeds
        trade = {**trade, 'entry_price': position['fill'], 'exit_price': trade['exit_price'] * sell, 'invested': position['invested'], 'pnl': proceeds - position['invested'], 'return': proceeds / position['invested'] - 1, 'quantity_adjusted': position['quantity']}
        completed.append(trade)
        del active[ticker]
    for date in sessions:
        # Opening exits release cash before opening entries. Intraday/close exit
        # cash is unavailable to entries at that same day's open.
        for ticker, position in list(active.items()):
            t = position['trade']
            if t.get('exit_date') == date and t.get('exit_timing') == 'open':
                close(ticker, position)
        budget = previous_nav / maximum
        for t in sorted(by_date.get(date, []), key=lambda t: (t['ticker'], t['signal_date'])):
            ticker = t['ticker']
            if ticker in active or len(active) >= maximum:
                ignored['capacity_or_duplicate'] += 1
                continue
            if not good(t['entry_price']):
                ignored['invalid_open'] += 1
                continue
            invested = min(cash, budget)
            if invested <= 1e-8:
                ignored['cash'] += 1
                continue
            fill = t['entry_price'] * buy
            active[ticker] = {'trade': dict(t), 'quantity': invested / fill, 'invested': invested, 'fill': fill, 'last_mark': t['entry_price']}
            cash -= invested
        for ticker, position in list(active.items()):
            if position['trade'].get('exit_date') == date:
                close(ticker, position)
        equity = cash
        for ticker, position in active.items():
            quote = prices[ticker]
            mark = quote.at[date, 'Adj Close'] if date in quote.index else None
            if good(mark):
                position['last_mark'] = mark
            else:
                data_gaps += 1
            equity += position['quantity'] * position['last_mark']
        b = None
        if benchmark is not None and date in benchmark.index:
            mark = benchmark.at[date, 'Adj Close']
            if good(mark):
                if benchmark_base:
                    b = initial * mark / benchmark_base
        rows.append({'date': date, 'equity': equity, 'cash': cash, 'positions': len(active), 'benchmark': b})
        previous_nav = equity
    for ticker, position in active.items():
        t = position['trade']
        end_mark = position['last_mark']
        # A future exit is not used to choose investments or count a closed trade.
        completed.append({**t, 'exit_date': None, 'exit_price': None, 'exit_reason': '保有中OHLC欠損・約定不明' if t['trade_status'] == 'unresolved_data_gap' else '期間末未決済',
                          'trade_status': 'unresolved_data_gap' if t['trade_status'] == 'unresolved_data_gap' else 'open_at_end',
                          'entry_price': position['fill'], 'holding_days': len(sessions[sessions >= t['entry_date']]), 'return': None, 'pnl': None,
                          'unrealized_pnl': position['quantity'] * end_mark - position['invested'], 'invested': position['invested'], 'quantity_adjusted': position['quantity']})
    completed.sort(key=lambda t: (str(t.get('exit_date') or sessions[-1]), t['ticker']))
    curve = pd.DataFrame(rows)
    curve['drawdown'] = curve.equity / np.maximum.accumulate(np.r_[initial, curve.equity.to_numpy()])[1:] - 1
    metrics = trade_metrics(completed, curve, initial)
    unresolved = sum(t['trade_status'] == 'unresolved_data_gap' for t in completed)
    metrics.update(data_gap_marks=data_gaps, unresolved_positions=unresolved, metrics_valid=not (data_gaps or unresolved), **ignored)
    if not metrics['metrics_valid']:
        for key in ('total_return', 'cagr', 'max_drawdown', 'sharpe_ratio', 'sortino_ratio', 'calmar_ratio'):
            metrics[key] = None
    return metrics, curve, completed
