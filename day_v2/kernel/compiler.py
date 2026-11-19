"""Deterministic compiler shared by the human form and contract import."""
from . import CONTRACT_VERSION, COMPILER_VERSION, ENGINE_VERSION
from .contracts import (PRIMITIVES, PRIMITIVE_VERSION, TIMEFRAMES, MAX_NODES, MAX_DEPTH,
                        IDENTIFIER, TypeInfo, ContractError, clone, digest, integer, keys, number, require)


def compile_definition(document):
    if isinstance(document,dict) and document.get('version')in ('AURUM_PORTFOLIO_DEFINITION_V1','AURUM_PORTFOLIO_DEFINITION_V2'):
        require(False,'PUBLIC_PORTFOLIO_UNAVAILABLE','version','Le moteur portefeuille ne fait pas partie du démonstrateur public.')
    doc = clone(document)
    keys(doc, ('version','asset','timeframe','direction','series','entry','exit','position','measurement'), 'definition', optional=('research','day'))
    if 'research' in doc:
        from .methodology import validate
        validate(doc['research'],doc['timeframe'])
    elif doc['timeframe'] in ('W1','MN1','M1','M5'):
        require(False,'METHODOLOGY_REQUIRED','methodology','W1/MN1 demandent une identité Long Term explicite.')
    is_day=doc.get('research',{}).get('methodology')=='DAY'
    require(is_day or 'day' not in doc,'DAY_IDENTITY_REQUIRED','day','Les règles DAY exigent une méthodologie DAY explicite.')
    require(doc['version'] == CONTRACT_VERSION, 'CONTRACT_VERSION_UNSUPPORTED', 'version', 'Version de définition non prise en charge.')
    require(type(doc['asset']) is str and 0 < len(doc['asset']) <= 40 and doc['asset'].strip() == doc['asset'],
            'ASSET_REQUIRED', 'asset', 'Instrument explicite requis.')
    require(type(doc['timeframe']) is str and doc['timeframe'] in TIMEFRAMES, 'TIMEFRAME_UNSUPPORTED', 'timeframe', 'Choisir M15, H1, H4 ou D1.')
    require(doc['direction'] in ('LONG','SHORT'), 'DIRECTION_UNSUPPORTED', 'direction', 'Un seul sens LONG ou SHORT par définition.')
    require(doc['position'] == {'max_open':1,'signals_while_open':'IGNORE'}, 'POSITION_MODEL_UNSUPPORTED', 'position',
            'Une position et aucun renforcement sont pris en charge.')
    require(type(doc['series']) is dict and 0 < len(doc['series']) <= 32, 'SERIES_REQUIRED', 'series', 'Définir entre 1 et 32 séries.')
    for name, series in doc['series'].items():
        require(IDENTIFIER.fullmatch(name) is not None, 'SERIES_NAME_INVALID', 'series', 'Identifiant de série invalide.')
        keys(series, ('label','expression'), 'series.'+name)
        require(type(series['label']) is str and 0 < len(series['label']) <= 120, 'SERIES_LABEL_REQUIRED', 'series.'+name, 'Libellé de série requis.')
    used = set()
    seen = [0]
    requirements = {}

    def check(node, path, stack=(), depth=0):
        seen[0] += 1
        require(depth <= MAX_DEPTH and seen[0] <= MAX_NODES, 'EXPRESSION_LIMIT', path, 'Expression trop profonde ou trop volumineuse.')
        require(type(node) is dict and type(node.get('op')) is str and node.get('op') in PRIMITIVES, 'PRIMITIVE_UNKNOWN', path,
                'Primitive inconnue : '+str(node.get('op') if isinstance(node,dict) else node))
        op=node['op']; used.add(op)
        if op == 'field':
            keys(node, ('op','field','timeframe'), path)
            require(node['field'] in ('open','high','low','close','volume') and type(node['timeframe']) is str and node['timeframe'] in TIMEFRAMES,
                    'SERIES_UNSUPPORTED', path, 'Champ OHLCV et timeframe déclaré requis.')
            return TypeInfo('VOLUME' if node['field']=='volume' else 'PRICE',1,frozenset((node['timeframe'],)))
        if op == 'constant':
            keys(node, ('op','value','unit'), path)
            require(node['unit'] in ('PRICE','RATIO','VOLUME','BOOLEAN'), 'UNIT_UNKNOWN',path,'Unité explicite requise.')
            if node['unit']=='BOOLEAN':
                require(type(node['value']) is bool, 'BOOLEAN_REQUIRED',path,'Booléen requis.')
            else:
                number(node['value'],path+'.value')
            return TypeInfo(node['unit'],0,frozenset())
        if op == 'ref':
            keys(node, ('op','name'), path)
            name=node['name']
            require(type(name) is str and name in doc['series'], 'SERIES_UNKNOWN',path,'Série nommée absente.')
            require(name not in stack, 'SERIES_CYCLE',path,'Référence circulaire entre séries.')
            return check(doc['series'][name]['expression'],path+'→'+name,stack+(name,),depth+1)
        if op in ('pivot_high','pivot_low'):
            keys(node,('op','input','left','right'),path)
            item=check(node['input'],path+'.input',stack,depth+1)
            require(item.unit=='PRICE' and len(item.timeframes)==1,'PIVOT_TYPE',path,'Pivot sur une série de prix mono-timeframe.')
            left=integer(node['left'],path+'.left',1);right=integer(node['right'],path+'.right',1)
            needed=item.warmup+left+right
            for tf in item.timeframes:requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('PRICE',needed,item.timeframes)
        if op == 'ema':
            keys(node, ('op','input','periods'), path)
            require(type(node['periods']) is int and node['periods'] in (8,20,50,200),
                    'EMA_PERIOD_UNSUPPORTED',path,'EMA 8/20/50/200 seulement.')
            require(type(node['input']) is dict and node['input'].get('op')=='field' and node['input'].get('field')=='close',
                    'EMA_INPUT_UNSUPPORTED',path,'EMA exige directement une serie de clotures.')
            item=check(node['input'],path+'.input',stack,depth+1)
            needed=item.warmup+node['periods']-1
            for tf in item.timeframes:requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('PRICE',needed,item.timeframes)
        if op == 'atr':
            keys(node, ('op','periods','timeframe'), path)
            require(type(node['periods']) is int and node['periods']==14,
                    'ATR_PERIOD_UNSUPPORTED',path,'Seul ATR14 est atteste par AURUM L2.')
            require(type(node['timeframe']) is str and node['timeframe'] in TIMEFRAMES,
                    'TIMEFRAME_UNSUPPORTED',path,'Timeframe ATR explicite requis.')
            requirements[node['timeframe']]=max(requirements.get(node['timeframe'],0),14)
            return TypeInfo('PRICE',14,frozenset((node['timeframe'],)))
        if op in ('donchian_upper','donchian_lower','donchian_middle'):
            keys(node,('op','timeframe','periods'),path)
            require(type(node['timeframe']) is str and node['timeframe'] in TIMEFRAMES,
                    'TIMEFRAME_UNSUPPORTED',path,'Timeframe Donchian explicite requis.')
            require(type(node['periods']) is int and node['periods'] in (20,40),
                    'DONCHIAN_PERIOD_UNSUPPORTED',path,'Donchian 20/40 seulement.')
            needed=node['periods']+1
            requirements[node['timeframe']]=max(requirements.get(node['timeframe'],0),needed)
            return TypeInfo('PRICE',needed,frozenset((node['timeframe'],)))
        if op in ('macd_line','macd_signal','macd_histogram','ichimoku_tenkan',
                  'ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b'):
            keys(node,('op','timeframe'),path)
            tf=node['timeframe']
            require(type(tf) is str and tf in TIMEFRAMES,'TIMEFRAME_UNSUPPORTED',path,
                    'Timeframe indicateur explicite requis.')
            needed=(26 if op=='macd_line' else 34 if op.startswith('macd_') else
                    9 if op=='ichimoku_tenkan' else 52 if op=='ichimoku_senkou_b' else 26)
            requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('PRICE',needed,frozenset((tf,)))
        if op in ('rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                  'plus_di','minus_di','adx'):
            keys(node,('op','timeframe'),path)
            tf=node['timeframe']
            require(type(tf) is str and tf in TIMEFRAMES,'TIMEFRAME_UNSUPPORTED',path,
                    'Timeframe indicateur explicite requis.')
            needed={'rsi':15,'stochastic_k':16,'stochastic_d':18,
                    'stoch_rsi_k':30,'stoch_rsi_d':32,'plus_di':15,'minus_di':15,'adx':28}[op]
            requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('RATIO',needed,frozenset((tf,)))
        level_events={'breakout_up','breakout_down','false_breakout_up','false_breakout_down'}
        if op in level_events:
            keys(node,('op','timeframe','level'),path)
            tf=node['timeframe']
            require(type(tf) is str and tf in TIMEFRAMES,'TIMEFRAME_UNSUPPORTED',path,
                    'Timeframe explicite requis.')
            level=check(node['level'],path+'.level',stack,depth+1)
            require(level.unit=='PRICE' and level.timeframes==frozenset((tf,)),
                    'LEVEL_TYPE',path,'Niveau de prix causal sur le même timeframe requis.')
            high_side=op.endswith('_up')
            field='high' if high_side else 'low'
            extreme='highest' if high_side else 'lowest'
            def is_field(item):
                return (type(item) is dict and item.get('op')=='field' and
                        item.get('field')==field and item.get('timeframe')==tf)
            def admitted(item, names=()):
                if type(item) is not dict:return False
                kind=item.get('op')
                if kind=='ref':
                    name=item.get('name')
                    return (type(name) is str and name in doc['series'] and name not in names and
                            admitted(doc['series'][name]['expression'],names+(name,)))
                if kind==('donchian_upper' if high_side else 'donchian_lower') or kind==(
                        'fractal_high' if high_side else 'fractal_low'):
                    return item.get('timeframe')==tf
                if kind==('pivot_high' if high_side else 'pivot_low'):
                    return is_field(item.get('input'))
                if kind=='lag' and item.get('periods')==1:
                    inside=item.get('input')
                    return type(inside) is dict and inside.get('op')==extreme and is_field(inside.get('input'))
                if kind==extreme:
                    inside=item.get('input')
                    return (type(inside) is dict and inside.get('op')=='lag' and
                            inside.get('periods')==1 and is_field(inside.get('input')))
                return False
            require(admitted(node['level']),'LEVEL_SOURCE_UNSUPPORTED',path,
                    'Niveau explicite admissible : extrema précédents, Donchian, pivot ou fractale confirmés.')
            needed=level.warmup+(1 if op.startswith('breakout_') else 0)
            requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('BOOLEAN',needed,frozenset((tf,)))
        if op in ('higher_high','higher_low','lower_high','lower_low',
                  'break_of_structure_up','break_of_structure_down'):
            keys(node,('op','timeframe'),path)
            tf=node['timeframe']
            require(type(tf) is str and tf in TIMEFRAMES,'TIMEFRAME_UNSUPPORTED',path,
                    'Timeframe structurel explicite requis.')
            needed=6 if op.startswith('break_of_structure') else 8
            requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('BOOLEAN',needed,frozenset((tf,)))
        price_action_price={'range','body','upper_wick','lower_wick','gap_size'}
        price_action_ratio={'body_ratio','close_location'}
        price_action_boolean={'bullish_candle','bearish_candle','inside_bar','outside_bar',
            'bullish_engulfing','bearish_engulfing','gap_up','gap_down','nr4','nr7',
            'range_expansion','range_contraction'}
        if op in price_action_price|price_action_ratio|price_action_boolean|{'fractal_high','fractal_low'}:
            keys(node,('op','timeframe'),path)
            tf=node['timeframe']
            require(type(tf) is str and tf in TIMEFRAMES,'TIMEFRAME_UNSUPPORTED',path,
                    'Timeframe explicite requis.')
            needed=(5 if op.startswith('fractal_') else 20 if op.startswith('range_expan') or op.startswith('range_contrac')
                    else 7 if op=='nr7' else 4 if op=='nr4' else 2 if op in
                    ('inside_bar','outside_bar','bullish_engulfing','bearish_engulfing','gap_size','gap_up','gap_down') else 1)
            requirements[tf]=max(requirements.get(tf,0),needed)
            unit='RATIO' if op in price_action_ratio else 'BOOLEAN' if op in price_action_boolean else 'PRICE'
            return TypeInfo(unit,needed,frozenset((tf,)))
        if op in ('lag','sma','highest','lowest','return','not'):
            keys(node, ('op','input') + (() if op=='not' else ('periods',)), path)
            item=check(node['input'],path+'.input',stack,depth+1)
            if op=='not':
                require(item.unit=='BOOLEAN','TYPE_MISMATCH',path,'NON attend une condition.')
                return item
            require(item.unit!='BOOLEAN','TYPE_MISMATCH',path,'Une série numérique est requise.')
            require(len(item.timeframes)==1,'LAG_TIMEFRAME_AMBIGUOUS',path,'Fenêtre/décalage sur une seule unité temporelle à la fois.')
            n=integer(node['periods'],path+'.periods',0 if op=='lag' else 1)
            needed=item.warmup + (n if op in ('lag','return') else n-1)
            for tf in item.timeframes:
                requirements[tf]=max(requirements.get(tf,0),needed)
            return TypeInfo('RATIO' if op=='return' else item.unit,needed,item.timeframes)
        if op in ('all','any'):
            keys(node, ('op','inputs'),path)
            require(type(node['inputs']) is list and 1 <= len(node['inputs']) <= 16,'CONDITIONS_REQUIRED',path,'Entre 1 et 16 conditions par groupe.')
            args=[check(n,path+f'.inputs[{i}]',stack,depth+1) for i,n in enumerate(node['inputs'])]
            require(all(a.unit=='BOOLEAN' for a in args),'TYPE_MISMATCH',path,'Le groupe attend uniquement des conditions.')
            return TypeInfo('BOOLEAN',max(a.warmup for a in args),frozenset().union(*(a.timeframes for a in args)))
        keys(node, ('op','left','right'),path)
        left=check(node['left'],path+'.left',stack,depth+1)
        right=check(node['right'],path+'.right',stack,depth+1)
        require(left.unit!='BOOLEAN' and right.unit!='BOOLEAN','TYPE_MISMATCH',path,'Opérandes numériques requis.')
        tfs=left.timeframes | right.timeframes
        warmup=max(left.warmup,right.warmup)
        if op in ('add','sub','gt','ge','lt','le','eq','cross_above','cross_below'):
            require(left.unit==right.unit,'UNIT_MISMATCH',path,'Les deux côtés doivent avoir la même unité.')
            unit=left.unit if op in ('add','sub') else 'BOOLEAN'
        elif op=='mul':
            require('RATIO' in (left.unit,right.unit),'UNIT_MISMATCH',path,'Le produit doit avoir un facteur sans dimension.')
            unit=right.unit if left.unit=='RATIO' else left.unit
        else:
            require(left.unit==right.unit or right.unit=='RATIO','UNIT_MISMATCH',path,'Division entre unités identiques ou par un ratio.')
            unit='RATIO' if left.unit==right.unit else left.unit
        if op.startswith('cross_'):
            if is_day:require(len(tfs)==1,'DAY_CROSS_CLOCK','rules','Un croisement doit porter sur une seule horloge scientifique.')
            warmup+=1
            for tf in tfs:
                requirements[tf]=max(requirements.get(tf,0),warmup)
        return TypeInfo(unit,warmup,tfs)

    series_types={}
    for name, item in doc['series'].items():
        info=check(item['expression'],'series.'+name,(name,))
        series_types[name]={'unit':info.unit,'warmup':info.warmup,'timeframes':sorted(info.timeframes)}
        for tf in info.timeframes:
            requirements[tf]=max(requirements.get(tf,0),info.warmup)
    keys(doc['entry'], ('timing','when'),'entry')
    declared_order=is_day and doc.get('day',{}).get('entry_order') is not None
    require(doc['entry']['timing']==('DECLARED_ORDER' if declared_order else 'NEXT_BAR_OPEN'),
            'ENTRY_TIMING_UNSUPPORTED','entry.timing',
            'Contrat d’ordres DAY : écrire LONG/SHORT sur ordre déclaré si … ; aucun remplacement silencieux d’une entrée imposée à l’OPEN.'
            if declared_order else 'Entrée à la prochaine ouverture seulement.')
    entry=check(doc['entry']['when'],'entry.when')
    require(entry.unit=='BOOLEAN','TYPE_MISMATCH','entry.when','Une condition d’entrée est requise.')
    keys(doc['exit'],('stop','target_r','when','max_bars'),'exit')
    stop=doc['exit']['stop']
    if stop is not None:
        keys(stop,('series','offset_ticks'),'exit.stop')
        require(type(stop['series']) is str and stop['series'] in series_types and series_types[stop['series']]['unit']=='PRICE','STOP_PRICE_REQUIRED','exit.stop','La référence du stop doit être une série de prix.')
        distance_ops={'atr','range','body','upper_wick','lower_wick','gap_size',
                      'macd_line','macd_signal','macd_histogram'}
        def distance_only(node, seen_names=()):
            op=node['op']
            if op in distance_ops:return True
            if op=='ref':
                name=node['name']
                return name not in seen_names and distance_only(doc['series'][name]['expression'],seen_names+(name,))
            if op in ('lag','sma','highest','lowest'):
                return distance_only(node['input'],seen_names)
            return False
        require(not distance_only(doc['series'][stop['series']]['expression']),
                'STOP_PRICE_REQUIRED','exit.stop','Une distance ou un oscillateur ne peut servir seul de niveau de stop.')
        number(stop['offset_ticks'],'exit.stop.offset_ticks')
    target=doc['exit']['target_r']
    if target is not None:
        require(stop is not None,'TARGET_REQUIRES_STOP','exit.target_r','Un objectif en R nécessite un stop initial.')
        number(target,'exit.target_r',positive=True)
    if doc['exit']['when'] is not None:
        require(check(doc['exit']['when'],'exit.when').unit=='BOOLEAN','TYPE_MISMATCH','exit.when','Condition de sortie requise.')
    if doc['exit']['max_bars'] is not None:
        integer(doc['exit']['max_bars'],'exit.max_bars',1)
    require(stop is not None or doc['exit']['when'] is not None or doc['exit']['max_bars'] is not None,
            'EXIT_UNDEFINED','exit','Préciser au moins une règle de sortie ; aucune durée implicite.')
    keys(doc['measurement'],('metric','operator','threshold','open_policy'),'measurement')
    require(doc['measurement']['metric']=='MEAN_NET_RETURN_PCT' and doc['measurement']['operator']=='>',
            'MEASURE_UNSUPPORTED','measurement','Moyenne nette par opération en %, seuil strict >.')
    number(doc['measurement']['threshold'],'measurement.threshold')
    require(doc['measurement']['open_policy'] in ('INCONCLUSIVE_IF_OPEN','CLOSED_ONLY'),
            'OPEN_POLICY_REQUIRED','measurement.open_policy','Choisir le traitement des positions encore ouvertes, sans liquidation ajoutée.')
    for tf in entry.timeframes:
        requirements[tf]=max(requirements.get(tf,0),entry.warmup)
    day_plan=None
    if is_day:
        from .day_contract import validate as validate_day
        day_plan=validate_day(doc,check,requirements)
    versions={k:('1.0.0_CAUSAL_PIVOT' if k.startswith('pivot_') else '1.0.0_AURUM_L2_EWM' if k in ('ema','atr') else PRIMITIVE_VERSION) for k in sorted(used)}
    result={'contract':CONTRACT_VERSION,'compiler':COMPILER_VERSION,'engine':ENGINE_VERSION,
            'definition':doc,'definition_hash':digest(doc),'primitive_versions':versions,
            'execution_model':'RESOLVED_FROM_VERSIONED_CONFIGURATION','intrabar_model':'DIRECT_M1_STOP_LAST_V1',
            'series_types':series_types,'warmup_requirements':requirements,
            'data_timeframes':sorted(set(requirements)|{doc['timeframe']}|({'M1'} if stop is not None else set())),
            'unit_kind':'CANDIDATE','mode':'DIRECT','availability':'CLOSED_BARS_AS_OF_DECISION_ONLY'}
    if day_plan is not None:
        result['day']=day_plan
        result['data_timeframes']=sorted(set(requirements)|({'M1'} if doc['day'].get('intrabar_tf')=='M1' else set()))
    result['plan_hash']=digest(result)
    return result


def blank_authoring():
    return {'series':[], 'entry':{'kind':'group','operator':'all','children':[]},
            'exit_condition':None,'stop_series':None,'stop_offset_ticks':None,
            'target_r':None,'max_bars':None,'threshold':'0','open_policy':None}


def compile_authoring(fields, authoring):
    """Compile choices made by the common form. Prose is retained, never parsed as code."""
    a=clone(authoring)
    keys(a,('series','entry','exit_condition','stop_series','stop_offset_ticks','target_r','max_bars','threshold','open_policy'),'rules')
    require(type(a['series']) is list and len(a['series']) <=32,'SERIES_REQUIRED','rules.series','Préciser les séries dans l’aide de saisie.')
    series={}
    for row in a['series']:
        keys(row,('id','label','kind','field','timeframe','periods','lag','left','right','value','unit'),'rules.series')
        name=row['id'];kind=row['kind']
        require(type(name) is str and IDENTIFIER.fullmatch(name) is not None,'SERIES_NAME_INVALID','rules.series','Identifiant de série invalide.')
        require(name not in series,'DUPLICATE_SERIES','rules.series','Deux séries portent le même identifiant.')
        if kind in ('field','sma','ema','highest','lowest','return'):
            expression={'op':'field','field':row['field'],'timeframe':row['timeframe'] or fields.get('timeframes','').strip()}
            if kind!='field':
                expression={'op':kind,'input':expression,'periods':row['periods']}
        elif kind=='atr':
            expression={'op':'atr','periods':row['periods'],'timeframe':row['timeframe'] or fields.get('timeframes','').strip()}
        elif kind=='constant':
            expression={'op':'constant','value':row['value'],'unit':row['unit']}
        elif kind in ('add','sub','mul','div'):
            expression={'op':kind,'left':{'op':'ref','name':row['left']},'right':{'op':'ref','name':row['right']}}
        elif kind in ('donchian_upper','donchian_lower','donchian_middle'):
            expression={'op':kind,'timeframe':row['timeframe'] or fields.get('timeframes','').strip(),
                        'periods':row['periods']}
        elif kind in ('macd_line','macd_signal','macd_histogram','ichimoku_tenkan',
                      'ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b',
                      'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                      'plus_di','minus_di','adx','higher_high','higher_low','lower_high',
                      'lower_low','break_of_structure_up','break_of_structure_down',
                      'fractal_high','fractal_low','range','body','upper_wick','lower_wick',
                      'body_ratio','close_location','bullish_candle','bearish_candle',
                      'inside_bar','outside_bar','bullish_engulfing','bearish_engulfing',
                      'gap_size','gap_up','gap_down','nr4','nr7','range_expansion','range_contraction'):
            expression={'op':kind,'timeframe':row['timeframe'] or fields.get('timeframes','').strip()}
        elif kind in ('breakout_up','breakout_down','false_breakout_up','false_breakout_down'):
            require(type(row['left']) is str and any(type(x) is dict and x.get('id')==row['left'] for x in a['series']),
                    'LEVEL_SERIES_REQUIRED','rules.series','Série de niveau explicite requise dans left.')
            expression={'op':kind,'timeframe':row['timeframe'] or fields.get('timeframes','').strip(),
                        'level':{'op':'ref','name':row['left']}}
        else:
            raise ContractError('PRIMITIVE_UNKNOWN','rules.series','Série non prise en charge : '+str(kind))
        if row['lag']:
            expression={'op':'lag','input':expression,'periods':row['lag']}
        series[name]={'label':row['label'],'expression':expression}

    def condition(item, depth=0):
        require(depth<=MAX_DEPTH,'EXPRESSION_LIMIT','rules.condition','Trop de groupes imbriqués.')
        require(type(item) is dict,'AMBIGUOUS_RULE','rules.condition','Préciser la condition dans les champs guidés ; la prose seule ne peut pas être exécutée.')
        if item.get('kind')=='group':
            keys(item,('kind','operator','children'),'rules.group')
            require(item['operator'] in ('all','any'),'PRIMITIVE_UNKNOWN','rules.group','Choisir Toutes ou Au moins une.')
            require(type(item['children']) is list and len(item['children'])<=16,'EXPRESSION_LIMIT','rules.group','Trop de conditions.')
            return {'op':item['operator'],'inputs':[condition(x,depth+1) for x in item['children']]}
        if item.get('kind')=='boolean':
            keys(item,('kind','left','negate'),'rules.condition')
            require(type(item['left']) is str and type(item['negate']) is bool,
                    'BOOLEAN_REQUIRED','rules.condition','Série booléenne et négation explicites requises.')
            node={'op':'ref','name':item['left']}
            return {'op':'not','input':node} if item['negate'] else node
        keys(item,('kind','left','operator','right','constant','unit','negate'),'rules.condition')
        require(item['kind']=='compare' and item['operator'] in ('gt','ge','lt','le','eq','cross_above','cross_below'),
                'PRIMITIVE_UNKNOWN','rules.condition','Comparaison non prise en charge.')
        right={'op':'ref','name':item['right']} if item['right'] else {'op':'constant','value':item['constant'],'unit':item['unit']}
        node={'op':item['operator'],'left':{'op':'ref','name':item['left']},'right':right}
        require(type(item['negate']) is bool,'BOOLEAN_REQUIRED','rules.condition','Négation explicite requise.')
        return {'op':'not','input':node} if item['negate'] else node

    definition={'version':CONTRACT_VERSION,'asset':fields.get('assets','').strip(),'timeframe':fields.get('timeframes','').strip(),
                'direction':fields.get('direction','').strip(),'series':series,
                'entry':{'timing':'NEXT_BAR_OPEN','when':condition(a['entry'])},
                'exit':{'stop':None if a['stop_series'] is None else {'series':a['stop_series'],'offset_ticks':a['stop_offset_ticks']},
                        'target_r':a['target_r'],'when':None if a['exit_condition'] is None else condition(a['exit_condition']),
                        'max_bars':a['max_bars']},
                'position':{'max_open':1,'signals_while_open':'IGNORE'},
                'measurement':{'metric':'MEAN_NET_RETURN_PCT','operator':'>','threshold':a['threshold'],'open_policy':a['open_policy']}}
    from .methodology import attach
    return compile_definition(attach(definition,fields))


def describe(plan):
    if plan['definition'].get('version')in ('AURUM_PORTFOLIO_DEFINITION_V1','AURUM_PORTFOLIO_DEFINITION_V2'):
        require(False,'PUBLIC_PORTFOLIO_UNAVAILABLE','version','Le moteur portefeuille ne fait pas partie du démonstrateur public.')
    doc=plan['definition']; labels={k:v['label'] for k,v in doc['series'].items()}
    symbols={'gt':'>','ge':'≥','lt':'<','le':'≤','eq':'=','cross_above':'croise au-dessus de','cross_below':'croise au-dessous de',
             'add':'+','sub':'−','mul':'×','div':'÷'}
    def text(n):
        op=n['op']
        if op=='ref':return labels[n['name']]
        if op=='field':return {'open':'ouverture','high':'plus haut','low':'plus bas','close':'clôture','volume':'volume'}[n['field']]+' '+n['timeframe']
        if op=='constant':return str(n['value'])+' '+n['unit']
        if op in ('all','any'):return '('+(' ET ' if op=='all' else ' OU ').join(text(x) for x in n['inputs'])+')'
        if op=='not':return 'NON '+text(n['input'])
        if op in ('pivot_high','pivot_low'):
            return f'Pivot {"haut" if op=="pivot_high" else "bas"} de ({text(n["input"])}), {n["left"]} observations à gauche, disponible après {n["right"]} observations à droite'
        if op=='atr':return 'ATR 14 '+n['timeframe']
        if op in ('donchian_upper','donchian_lower','donchian_middle'):
            return op.replace('_',' ').title()+' '+str(n['periods'])+' '+n['timeframe']
        if op in ('breakout_up','breakout_down','false_breakout_up','false_breakout_down'):
            return op.replace('_',' ').title()+' de ('+text(n['level'])+') '+n['timeframe']
        if op in ('macd_line','macd_signal','macd_histogram','ichimoku_tenkan',
                  'ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b',
                  'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                  'plus_di','minus_di','adx','higher_high','higher_low','lower_high',
                  'lower_low','break_of_structure_up','break_of_structure_down',
                  'fractal_high','fractal_low','range','body','upper_wick','lower_wick',
                  'body_ratio','close_location','bullish_candle','bearish_candle',
                  'inside_bar','outside_bar','bullish_engulfing','bearish_engulfing',
                  'gap_size','gap_up','gap_down','nr4','nr7','range_expansion','range_contraction'):
            return op.replace('_',' ').title()+' '+n['timeframe']
        if op in ('lag','sma','ema','highest','lowest','return'):
            name={'lag':'Retard','sma':'SMA','ema':'EMA','highest':'Maximum','lowest':'Minimum','return':'Rendement simple'}[op]
            return f'{name} {n["periods"]} périodes de ({text(n["input"])})'
        return f'({text(n["left"])} {symbols[op]} {text(n["right"])})'
    lines=[f'{doc["asset"]} · {doc["timeframe"]} · {doc["direction"]}']
    lines.extend(label['label']+' = '+text(label['expression']) for label in doc['series'].values())
    order=doc.get('day',{}).get('entry_order')
    if order is None:lines.append('Entrer à l’ouverture immédiatement suivante si '+text(doc['entry']['when']))
    else:
        lines.append('Soumettre '+order['type']+' après le signal '+text(doc['entry']['when'])+' ; première quote admissible strictement postérieure à la soumission.')
        for name in ('stop_price_rule','limit_price_rule'):
            if name in order:
                r=order[name];lines.append(name+' : '+text(r['expression'])+' + ('+str(r['offset'])+') '+r['offset_unit']+' ; référence figée à la décision.')
        lines.append('Validité : '+order['time_in_force']+' ; quantité fixée avant fill, jamais depuis une ouverture future.')
    if doc['exit']['stop']:
        s=doc['exit']['stop'];lines.append(f'Stop fixe : {labels[s["series"]]} + ({s["offset_ticks"]}) ticks, valeur de la bougie du signal.')
    else:lines.append('Aucun stop de prix déclaré.')
    if doc['exit']['target_r']:lines.append('Objectif fixe : '+doc['exit']['target_r']+' R depuis le prix d’entrée effectif, avant charges monétaires.')
    if doc['exit']['when']:lines.append('Sortir à la prochaine ouverture si '+text(doc['exit']['when']))
    if doc['exit']['max_bars']:lines.append('Durée explicitement choisie : '+str(doc['exit']['max_bars'])+' barres, sortie à l’ouverture suivante.')
    lines.extend(('Une position ; signaux pendant position ignorés ; pas de renforcement.',
                  'Amorçage : '+', '.join(str(n)+' clôtures '+tf for tf,n in sorted(plan['warmup_requirements'].items())),
                  'Mesure : moyenne non pondérée des rendements nets en % du notionnel initial ; seuil strict > '+doc['measurement']['threshold']+' %.',
                  'Fin de période : '+doc['measurement']['open_policy']+' ; aucune liquidation forcée.'))
    if 'day' in plan:
        day=doc['day']
        lines.append('DAY : signal '+day['signal_tf']+' ; contexte '+str(day.get('context_tf') or 'aucun')+' ; trigger '+str(day.get('trigger_tf') or 'aucun')+'.')
        lines.append('M1 : source des consolidations DAY ; rôle de signal/trigger '+('oui' if 'M1' in plan['day']['scientific_timeframes'] else 'non')+' ; résolution intrabar '+str(day.get('intrabar_tf') or 'désactivée')+(' pour causalité des ordres et ambiguïtés SL/TP.' if day.get('entry_order') else ' uniquement sur ambiguïté SL/TP.'))
        lines.append('Session '+day['session_profile_id']+' ; overnight '+day['overnight_policy']+'.')
        for key in ('context_when','setup_when','approach_when','touch_when','trigger_when','confirmation_when','invalidation_when'):
            if day.get(key) is not None:lines.append(key+' : '+text(day[key]))
        if day.get('force_flat'):
            lines = [line.replace(' ; aucune liquidation forcée.', ' ; liquidation intraday selon la règle explicite ci-dessous.') for line in lines]
            lines.append('Force-flat : '+str(day['force_flat'])+' ; seulement sur un prix éligible observé, aucun dernier prix reconduit.')
    return lines
