"""DAY conditions use the same bounded scientific rule translator as the form."""
import json
from .contracts import clone, require


def attach(definition, fields):
    from .standard_authoring import Rules, norm
    controls = json.loads(fields.get('_day_controls', 'null'))
    require(isinstance(controls, dict), 'DAY_CONTROLS_REQUIRED', 'day', 'Précisez les conventions DAY ; contexte et trigger restent facultatifs.')
    controls = clone(controls)
    controls['signal_tf'] = definition['timeframe']
    for role in ('context','trigger'):
        if role+'_tf' in controls:
            require(controls[role+'_tf'] is not None, 'DAY_CONDITION_ROLE_REQUIRED', 'day.'+role,
                    'Choisissez le timeframe ajouté ou retirez cette option.')
    for name in ('context','setup','approach','touch','trigger','confirmation','invalidation'):
        text = controls.pop(name + '_text', None)
        if not text:
            continue
        tf = controls.get('context_tf') if name == 'context' else controls.get('trigger_tf') if name in ('approach','touch','trigger','confirmation') else controls['signal_tf']
        require(tf is not None, 'DAY_CONDITION_ROLE_REQUIRED', 'day.' + name, 'Condition présente sans timeframe correspondant.')
        rules = Rules(tf)
        controls[name + '_when'] = rules.condition(norm(text), 'day.' + name)
        definition['series'].update(rules.series)
    order = controls.get('entry_order')
    if order is not None:
        for name in ('limit','stop'):
            text = order.pop(name + '_price_text', None)
            if text is not None:
                require(bool(text.strip()), 'ORDER_PRICE_REQUIRED', 'day.entry_order.'+name,
                        'Précisez la règle de prix '+name+'.')
                order[name + '_price_rule'] = Rules(controls['signal_tf']).price(text, 'day.entry_order.'+name)
    definition['day'] = controls
    return definition
