from .base import Strategy, financial_mask
import pandas as pd


class Growth(Strategy):
    def entry_signals(self, frame, p, data):
        mask = frame.market_cap.ge(p['cap_min']) & frame.market_cap.lt(p['cap_max'])
        if p['mode'] == 'price_only':
            # Explicit proxy: price-only does not establish earnings growth.
            mask &= frame['Adj Close'].gt(frame['Adj Close'].rolling(50, min_periods=50).mean())
        mask &= financial_mask(frame, p, data)
        if p['listing_enabled']:
            listing = data.get('listing_date')
            if listing is None:
                return pd.Series(False, index=frame.index)
            age = (frame.index - pd.Timestamp(listing)).days / 365.25
            mask &= (age >= 0) & (age <= p['listing_years'])
        return mask

    def reasons(self, frame, position, parameters, data):
        return super().reasons(frame, position, parameters, data) + f" / 当時時価総額 {frame.market_cap.iloc[position] / 1e8:.1f}億円" + (' / 50日MA上（価格代理条件・成長未確認）' if parameters['mode'] == 'price_only' else '')


STRATEGY = Growth('kenmo_growth', 'Kenmo Growth', '当時時価総額50〜300億円＋成長性。価格版は50日MA上の代理条件であり業績成長を保証しない。', ('prices', 'historical_shares', 'optional_fundamentals', 'optional_listing_date'), {'cap_min': [5e9], 'cap_max': [3e10]})
