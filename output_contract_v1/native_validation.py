"""Load and verify the bundled pure compiler. No external AURUM installation."""
from contextlib import contextmanager
import importlib
from pathlib import Path
from output_common import ROOT, need, dependency_state, verify_self

@contextmanager
def native_compiler(registry):
    verify_self()
    snapshots, current = dependency_state()
    need(registry == current, 'PUBLIC_REGISTRY_MISMATCH')
    names = ('contracts','session_profiles','compiler','primitives','methodology',
             'standard_authoring','scientific_fields','day_authoring','order_contract','day_contract')
    modules = {}
    for name in names:
        module = importlib.import_module('day_v2.kernel.' + name)
        need(Path(module.__file__).resolve() == (ROOT / 'day_v2/kernel' / (name + '.py')).resolve(),
             'PUBLIC_NATIVE_IMPORT_ORIGIN')
        modules[name] = module
    try:
        yield modules
    finally:
        dependency_state()


def check_design_subset(value):
    """Keep historical ADAM indicator parameters despite a wider ARL parser."""
    if isinstance(value,dict):
        op=value.get('op')
        periods=value.get('periods',14)
        allowed=({'ema':(8,20,50,200),'atr':(14,),
                  'donchian_upper':(20,40),'donchian_lower':(20,40),'donchian_middle':(20,40),
                  'rsi':(14,),'plus_di':(14,),'minus_di':(14,),'adx':(14,)}).get(op)
        if allowed is not None:
            need(type(periods) is int and periods in allowed,'NATIVE_FIELDS_REJECTED:ADAM_PERIOD_SUBSET')
        for child in value.values():check_design_subset(child)
    elif isinstance(value,list):
        for child in value:check_design_subset(child)
