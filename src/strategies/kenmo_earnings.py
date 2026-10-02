import pandas as pd
from .base import Strategy, financial_mask


class Earnings(Strategy):
    def entry_signals(self, frame, p, data):
        mask = pd.Series(False, index=frame.index)
        reasons = {}
        for release in data['earnings']:
            when = pd.Timestamp(release['released_at'])
            if when.tzinfo is None:
                when = when.tz_localize('Asia/Tokyo')
            else:
                when = when.tz_convert('Asia/Tokyo')
            day = when.normalize().tz_localize(None)
            base = int(frame.index.searchsorted(day))
            if base >= len(frame) or base == 0:
                continue
            # Only a verified market-hours timestamp permits same-session reaction.
            close_minutes = 15 * 60 + (30 if day >= pd.Timestamp('2024-11-05') else 0)
            minutes = when.hour * 60 + when.minute
            intraday = release.get('timing_known', False) and frame.index[base] == day and 9 * 60 <= minutes < close_minutes
            reaction = base if intraday else base + 1
            entry = base + p['entry_offset']
            signal = entry - 1
            if reaction >= len(frame) or entry >= len(frame) or signal < reaction:
                continue
            previous = base - 1
            ret = frame['Adj Close'].iloc[reaction] / frame['Adj Close'].iloc[previous] - 1
            ratio = frame.strategy_volume_ratio.iloc[reaction]
            if ret >= p['reaction_rate'] and (not p['volume_enabled'] or ratio >= p['volume_ratio']):
                mask.iloc[signal] = True
                reasons[signal] = f"決算 {when.isoformat()} / {'場中' if intraday else '翌営業日反応（時刻不明・場外は保守的）'} / 株価反応 {ret:.1%} / 出来高 {ratio:.2f}倍 / {p['entry_offset']}営業日後"
        data['earnings_reasons'] = reasons
        return mask & financial_mask(frame, p, data)

    def reasons(self, frame, position, parameters, data):
        return data.get('earnings_reasons', {}).get(position, '') + ' / ' + super().reasons(frame, position, parameters, data)


STRATEGY = Earnings('kenmo_earnings', 'Kenmo Earnings Momentum', '公表済み決算への株価・出来高反応。財務版は安全な観測値のみ。', ('prices', 'earnings', 'optional_fundamentals'), {'entry_offset': [1, 2, 3, 5], 'reaction_rate': [.03, .05, .1], 'volume_ratio': [1, 1.5, 2]})
