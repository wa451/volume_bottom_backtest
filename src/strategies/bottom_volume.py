from .base import Strategy
from src.signals import signal_mask


class BottomVolume(Strategy):
    def entry_signals(self, frame, parameters, data):
        return signal_mask(frame, parameters['drawdown_threshold'], parameters['volume_ratio'])

    def reasons(self, frame, position, parameters, data):
        row = frame.iloc[position]
        return f'底値・出来高 / 下落率 {row.drawdown:.1%} / 出来高 {row.volume_ratio:.2f}倍'


STRATEGY = BottomVolume('bottom_volume', 'Bottom + Volume', '十分下落＋出来高異常値。単独実行は既存Event Study、比較実行は資金配分を伴う検証。', ('prices', 'historical_shares'), {})
