"""Strategy contract; signals are known at close and entries occur next session."""
from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    description: str
    required_data: tuple[str, ...]
    parameter_definitions: dict

    def entry_signals(self, frame, parameters, data):
        raise NotImplementedError

    def exit_trade(self, frame, entry_position, parameters):
        from src.execution import find_exit
        return find_exit(frame, entry_position, parameters)

    def reasons(self, frame, position, parameters, data):
        row = frame.iloc[position]
        reason = [self.name]
        if parameters.get('high_enabled', False):
            reason.append(f"{parameters['high_period']}日高値更新")
        if parameters.get('volume_enabled', True):
            ratio = row.get('strategy_volume_ratio', float('nan'))
            reason.append(f'出来高 {ratio:.2f}倍')
        if parameters.get('mode') == 'fundamentals':
            for column, label in [('revenue_growth', '売上YoY'), ('earnings_growth', 'EPS/利益YoY'), ('roe', 'ROE'), ('per', 'PER')]:
                value = data['fundamentals'].iloc[position].get(column)
                enabled = parameters[{'revenue_growth': 'revenue_enabled', 'earnings_growth': 'earnings_enabled', 'roe': 'roe_enabled', 'per': 'per_enabled'}[column]]
                if enabled and pd.notna(value):
                    reason.append(f'{label} {value:.2%}' if column != 'per' else f'PER {value:.2f}倍')
        return ' / '.join(reason)


def financial_mask(frame, p, data):
    mask = pd.Series(True, index=frame.index)
    if p['mode'] != 'fundamentals':
        return mask
    f = data['fundamentals']
    for enabled, column, key in [('revenue_enabled', 'revenue_growth', 'revenue_growth'), ('earnings_enabled', 'earnings_growth', 'earnings_growth'), ('roe_enabled', 'roe', 'roe')]:
        if p[enabled]:
            mask &= f[column].ge(p[key])
    if p['per_enabled']:
        mask &= f['per'].between(p['per_min'], p['per_max'])
    return mask
