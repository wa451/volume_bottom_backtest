from datetime import date, datetime
import math
import numpy as np
import pandas as pd


def clean(value):
    if isinstance(value, dict):
        out = {str(k): clean(v) for k, v in value.items()}
        if "profit_factor" in value:
            pf = value["profit_factor"]
            out["profit_factor_infinite"] = bool(
                isinstance(pf, (float, np.floating)) and math.isinf(pf) and pf > 0
            )
        return out
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is pd.NA or value is pd.NaT or value is None:
        return None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
