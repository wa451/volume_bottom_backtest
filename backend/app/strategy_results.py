"""Read-only queries over immutable Worker portfolio artifacts."""
import csv
import io
import json
import duckdb
import pandas as pd
import numpy as np
from pydantic import BaseModel, Field, ConfigDict
from .serialization import clean

SORTS = {'total_return', 'cagr', 'max_drawdown', 'sharpe_ratio', 'sortino_ratio', 'profit_factor', 'expectancy', 'num_trades', 'win_rate', 'calmar_ratio'}


class StrategyFilter(BaseModel):
    model_config = ConfigDict(extra='forbid')
    period_type: str = Field('train', pattern='^(train|test|full)$')
    market_cap_group: str = Field('ALL', max_length=40)
    market_segment: str = Field('ALL', pattern='^(ALL|Prime|Standard|Growth)$')
    strategy_id: str | None = Field(None, pattern='^(bottom_volume|kenmo_breakout|kenmo_earnings|kenmo_growth)$')
    parameter_id: str | None = Field(None, pattern='^[a-f0-9]{16}$')


def result_page(path, filters, sort, descending, limit, offset):
    frame = pd.read_parquet(path)
    for key, value in filters.model_dump().items():
        if value is not None:
            frame = frame[frame[key].eq(value)]
    # No-loss PF is undefined/infinite, kept visible but never represented as 0.
    frame['_rank'] = frame[sort]
    if sort == 'profit_factor':
        frame.loc[frame.profit_factor_no_losses, '_rank'] = np.inf
    frame = frame.sort_values(['_rank', 'num_trades', 'parameter_id'], ascending=[not descending, False, True], na_position='last').drop(columns='_rank')
    items = clean(frame.iloc[offset:offset + limit].to_dict('records'))
    for row in items:
        row['parameters'] = json.loads(row['parameters'])
    return {'items': items, 'total': len(frame), 'limit': limit, 'offset': offset}


def _query(path, filters):
    clauses, values = [], [str(path)]
    for key, value in filters.model_dump().items():
        if value is not None:
            clauses.append(f'"{key}" = ?')
            values.append(value)
    return 'SELECT * FROM read_parquet(?) WHERE ' + ' AND '.join(clauses), values


def artifact_page(path, filters, limit, offset, curve=False):
    query, values = _query(path, filters)
    with duckdb.connect() as db:
        total = db.execute('SELECT count(*) FROM (' + query + ')', values).fetchone()[0]
        order = 'date' if curve else 'entry_date, ticker'
        frame = db.execute(query + f' ORDER BY {order} LIMIT ? OFFSET ?', values + [limit, offset]).fetchdf()
    return {'items': clean(frame.to_dict('records')), 'total': total, 'limit': limit, 'offset': offset}


def trade_csv(path, filters):
    query, values = _query(path, filters)
    with duckdb.connect() as db:
        cursor = db.execute(query + ' ORDER BY entry_date, ticker', values)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow([column[0] for column in cursor.description])
        yield '\ufeff' + out.getvalue()
        while batch := cursor.fetchmany(1000):
            out.seek(0)
            out.truncate(0)
            for row in batch:
                writer.writerow(["'" + v if isinstance(v, str) and v.lstrip().startswith(('=', '+', '-', '@')) else v for v in row])
            yield out.getvalue()
