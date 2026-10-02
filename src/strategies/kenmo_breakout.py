from .base import Strategy, financial_mask
import pandas as pd


class Breakout(Strategy):
    def entry_signals(self, frame, p, data):
        mask = pd.Series(True, index=frame.index)
        if p['high_enabled']:
            high = frame['Adj High'].shift(1).rolling(p['high_period'], min_periods=p['high_period']).max()
            mask &= frame['Adj Close'].gt(high)
        if p['volume_enabled']:
            mask &= frame.strategy_volume_ratio.ge(p['volume_ratio'])
        return mask & financial_mask(frame, p, data)


STRATEGY = Breakout('kenmo_breakout', 'Kenmo Breakout', '過去高値と出来高増加に追随。財務条件は取得時点以後だけ利用。', ('prices', 'historical_shares', 'optional_fundamentals'), {'high_period': [120, 180, 252], 'volume_ratio': [1, 1.5, 2]})
