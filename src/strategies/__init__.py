from .bottom_volume import STRATEGY as bottom
from .kenmo_breakout import STRATEGY as breakout
from .kenmo_earnings import STRATEGY as earnings
from .kenmo_growth import STRATEGY as growth

REGISTRY = {s.id: s for s in (bottom, breakout, earnings, growth)}


def metadata():
    return [{'id': s.id, 'name': s.name, 'description': s.description, 'required_data': s.required_data, 'parameters': s.parameter_definitions} for s in REGISTRY.values()]
