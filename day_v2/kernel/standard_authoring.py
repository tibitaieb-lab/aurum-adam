"""Bounded French authoring of a new exploratory dossier; never arbitrary prose/code.

Resolves author inputs into the existing declarative contract. No finance, data,
authorization, review or historic dossier lookup. Existing dossiers opt in only
by an explicit new creation; importing a recipe preserves its versioned marker.
"""
import re
import unicodedata
from decimal import Decimal
from .compiler import compile_definition
from . import CONTRACT_VERSION
from .contracts import ContractError, clone, digest, require

VERSION = 'AURUM_STANDARD_EXPLORATORY_V1'
MARKER = '_standard_authoring'
MANUAL = ('title','source_origin','initial_observation','alternative_hypothesis_h1',
          'entry_rules','exit_rules','assets','timeframes')
BUDGET = {'max_implementations':'1','max_free_parameters':'0','max_values_per_parameter':'1',
          'max_variants':'1','max_assets':'1','max_timeframes':'1','max_total_runs':'1'}
AUTO = (*BUDGET, 'scientific_nature','oos_policy')
DERIVED = ('primary_phenomenon','direction','null_hypothesis_h0','baseline','success_criteria',
           'rejection_criteria','revision_policy','closure_condition')
DECISION = 'Démonstrateur public : protocole exploratoire borné, aucun droit de lancement'
HELP = {
 'alternative_hypothesis_h1': 'Mesure prise en charge : « La moyenne des rendements nets par opération, en % du notionnel initial, est supérieure à [votre seuil] %. » Le seuil doit être explicite. Aucun test statistique de H1 n’est présumé.',
 'entry_rules': 'Précisez LONG ou SHORT et « à l’ouverture suivante si … » ; pour les nouveaux ordres DAY, « sur ordre déclaré si … ». Séries : clôture, ouverture, plus haut, plus bas, volume ; SMA N des clôtures ; EMA 8/20/50/200 des clôtures ; ATR 14 ; RSI 14 ; stochastic k/d 14/3/3 ; stoch rsi k/d 14/14/3/3 ; plus di 14, minus di 14, adx 14 ; Donchian upper/lower/middle 20/40 ; MACD line/signal/histogram ; Ichimoku tenkan/kijun/senkou a/senkou b ; range et autres primitives Price Action structurées ; breakout up/down sur un niveau causal explicite ; HH/HL/LH/LL et BOS sur pivots confirmés 2/2 ; maximum/minimum des N barres ; rendement sur N clôtures. Comparaisons : >, >=, <, <=, =, croise au-dessus de / au-dessous de. Conditions reliées par ET ou par OU. Tout est calculé sur les barres clôturées du timeframe choisi.',
 'exit_rules': 'Déclarez une sortie : « Stop fixe au plus bas du signal moins N ticks » (ou plus haut / plus N ticks), « Objectif fixe N R », « Sortir à l’ouverture suivante si … », ou « Sortir après N barres ». Séparez les clauses par un point. Ajoutez « Positions ouvertes exclues de la mesure » ou « Positions ouvertes : résultat inconcluant ». Aucune liquidation implicite.',
}

def enabled(fields):
    return MARKER in fields

def norm(text):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFD',text.lower().replace('’',"'"))
                            if unicodedata.category(c)!='Mn').split()).strip().rstrip('.')

def fail(field,message):
    raise ContractError('STANDARD_FIELD_PRECISION_REQUIRED',field,message)

def threshold(text):
    value=norm(text).replace('pourcentage','%')
    pattern=r"(?:la )?moyenne des rendements nets par operation,? en % du notionnel initial,? (?:est )?(?:strictement )?superieure? a ([+-]?\d+(?:[.,]\d+)?)\s*%"
    found=re.fullmatch(pattern,value)
    if not found:fail('alternative_hypothesis_h1',HELP['alternative_hypothesis_h1'])
    return format(Decimal(found[1].replace(',','.')),'f')

class Rules:
    def __init__(self, timeframe):self.tf=timeframe;self.series={}

    def expression(self,text,field,depth=0):
        if depth>12:fail(field,'Série trop imbriquée ; au maximum 12 transformations.')
        text=re.sub(r'^(?:la |le |les )','',text.strip())
        lag=re.fullmatch(r'(.+) decale(?:e)? de (\d+) barres?',text)
        if lag:
            expr,unit=self.expression(lag[1],field,depth+1)
            return dict(op='lag',input=expr,periods=int(lag[2])),unit
        names={'cloture':'close','clotures':'close','ouverture':'open','ouvertures':'open',
               'plus haut':'high','plus hauts':'high','plus bas':'low','volume':'volume','volumes':'volume'}
        if text in names:
            name=names[text]
            return dict(op='field',field=name,timeframe=self.tf),'VOLUME' if name=='volume' else 'PRICE'
        sma=re.fullmatch(r'sma (\d+) (?:des |de la |de )(.+)',text)
        if sma:
            expr,unit=self.expression(sma[2],field,depth+1)
            return dict(op='sma',periods=int(sma[1]),input=expr),unit
        if text=='ema 20 des clotures moins atr 14':
            tf=self.tf
            return dict(op='sub',left=dict(op='ema',periods=20,input=dict(op='field',field='close',timeframe=tf)),
                        right=dict(op='atr',periods=14,timeframe=tf)),'PRICE'
        ema=re.fullmatch(r'ema (\d+)(?: (?:des |de la |de )(.+))?',text)
        if ema:
            n=int(ema[1])
            if n not in (8,20,50,200):fail(field,'EMA 8/20/50/200 seulement.')
            expr,unit=self.expression(ema[2] or 'clotures',field,depth+1)
            if expr.get('op')!='field' or expr.get('field')!='close':fail(field,'EMA exige directement les clotures.')
            return dict(op='ema',periods=n,input=expr),unit
        atr=re.fullmatch(r'atr (\d+)',text)
        if atr:
            if int(atr[1])!=14:fail(field,'Seul ATR 14 est atteste.')
            return dict(op='atr',periods=14,timeframe=self.tf),'PRICE'
        donchian=re.fullmatch(r'donchian (upper|lower|middle) (\d+)',text)
        if donchian:
            n=int(donchian[2])
            if n not in (20,40):fail(field,'Donchian 20/40 seulement.')
            return dict(op='donchian_'+donchian[1],periods=n,timeframe=self.tf),'PRICE'
        indicator=re.fullmatch(r'(macd (?:line|signal|histogram)|ichimoku (?:tenkan|kijun|senkou a|senkou b))',text)
        if indicator:
            return dict(op=indicator[1].replace(' ','_'),timeframe=self.tf),'PRICE'
        oscillator=re.fullmatch(r'(rsi 14|stochastic [kd] 14 3 3|stoch rsi [kd] 14 14 3 3|plus di 14|minus di 14|adx 14)',text)
        if oscillator:
            name=oscillator[1]
            name=('stochastic_'+name.split()[1] if name.startswith('stochastic ') else
                  'stoch_rsi_'+name.split()[2] if name.startswith('stoch rsi ') else
                  name.rsplit(' ',1)[0].replace(' ','_'))
            return dict(op=name,timeframe=self.tf),'RATIO'
        level_event=re.fullmatch(r'(breakout up|breakout down|false breakout up|false breakout down) sur (.+)',text)
        if level_event:
            level,unit=self.expression(level_event[2],field,depth+1)
            if unit!='PRICE':fail(field,'Breakout exige un niveau explicite de prix.')
            return dict(op=level_event[1].replace(' ','_'),timeframe=self.tf,level=level),'BOOLEAN'
        structure=re.fullmatch(r'(higher_high|higher_low|lower_high|lower_low|break_of_structure_up|break_of_structure_down)',text)
        if structure:return dict(op=structure[1],timeframe=self.tf),'BOOLEAN'
        primitive=re.fullmatch(r'(range|body|upper_wick|lower_wick|body_ratio|close_location|gap_size|fractal_high|fractal_low|bullish_candle|bearish_candle|inside_bar|outside_bar|bullish_engulfing|bearish_engulfing|gap_up|gap_down|nr4|nr7|range_expansion|range_contraction)',text)
        if primitive:
            name=primitive[1]
            unit='RATIO' if name in ('body_ratio','close_location') else 'BOOLEAN' if name in (
                'bullish_candle','bearish_candle','inside_bar','outside_bar','bullish_engulfing',
                'bearish_engulfing','gap_up','gap_down','nr4','nr7','range_expansion','range_contraction') else 'PRICE'
            return dict(op=name,timeframe=self.tf),unit
        pivot=re.fullmatch(r'pivot (haut|bas) de (.+) avec (\d+) barres? a gauche et (\d+) barres? a droite',text)
        if pivot:
            expr,unit=self.expression(pivot[2],field,depth+1)
            return dict(op='pivot_high' if pivot[1]=='haut' else 'pivot_low',input=expr,left=int(pivot[3]),right=int(pivot[4])),unit
        extrema=re.fullmatch(r'(maximum|minimum) des (\d+) (plus hauts|plus bas|clotures)( precedents| precedentes)?',text)
        if extrema:
            expr,unit=self.expression(extrema[3],field,depth+1)
            if extrema[4]:expr=dict(op='lag',periods=1,input=expr)
            return dict(op='highest' if extrema[1]=='maximum' else 'lowest',periods=int(extrema[2]),input=expr),unit
        momentum=re.fullmatch(r'rendement sur (\d+) clotures',text)
        if momentum:return dict(op='return',periods=int(momentum[1]),input=dict(op='field',field='close',timeframe=self.tf)),'RATIO'
        fail(field,'Série non reconnue : « '+text+' ». '+HELP['entry_rules'])

    def ref(self,expression):
        name='s_'+digest(expression)[:16]
        def label(n):
            if n['op']=='field':return {'close':'Clôture','open':'Ouverture','low':'Plus bas','high':'Plus haut','volume':'Volume'}[n['field']]
            if n['op']=='atr':return 'ATR 14'
            if n['op'] in ('donchian_upper','donchian_lower','donchian_middle'):
                return n['op'].replace('_',' ').title()+' '+str(n['periods'])
            if n['op'] in ('macd_line','macd_signal','macd_histogram','ichimoku_tenkan',
                           'ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b',
                           'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                           'plus_di','minus_di','adx','higher_high','higher_low','lower_high',
                           'lower_low','break_of_structure_up','break_of_structure_down',
                           'fractal_high','fractal_low','range','body','upper_wick','lower_wick',
                           'body_ratio','close_location','gap_size','bullish_candle','bearish_candle',
                           'inside_bar','outside_bar','bullish_engulfing','bearish_engulfing',
                           'gap_up','gap_down','nr4','nr7','range_expansion','range_contraction'):
                return n['op'].replace('_',' ').title()
            if n['op'] in ('breakout_up','breakout_down','false_breakout_up','false_breakout_down'):
                return n['op'].replace('_',' ').title()+' sur '+label(n['level'])
            if n['op']=='sub':return label(n['left'])+' moins '+label(n['right'])
            if n['op'] in ('pivot_high','pivot_low'):return ('Pivot haut' if n['op']=='pivot_high' else 'Pivot bas')+' '+str(n['left'])+'/'+str(n['right'])+' · '+label(n['input'])
            return {'sma':'SMA','ema':'EMA','highest':'Maximum','lowest':'Minimum','return':'Rendement','lag':'Retard'}[n['op']]+' '+str(n['periods'])+' · '+label(n['input'])
        self.series[name]={'label':label(expression)[:120],'expression':expression}
        return dict(op='ref',name=name)

    def condition(self,text,field):
        # The pivot's left/right phrase is one operand, not a logical conjunction.
        text=re.sub(r'(avec \d+ barres? a gauche) et (\d+ barres? a droite)',r'\1 § \2',text)
        separators=[s for s in (' et ',' ou ') if s in text]
        if len(separators)>1:fail(field,'Le mélange ET / OU doit être précisé ; utilisez un seul type de liaison dans la saisie simple.')
        if separators:
            pieces=text.split(separators[0])
            if len(pieces)>16:fail(field,'Au maximum 16 conditions dans la saisie simple.')
            return dict(op='all' if separators[0]==' et ' else 'any',inputs=[self.condition(x,field) for x in pieces])
        text=text.replace(' § ',' et ')
        if text in ('bullish_candle','bearish_candle','inside_bar','outside_bar',
                    'bullish_engulfing','bearish_engulfing','gap_up','gap_down','nr4','nr7',
                    'range_expansion','range_contraction','higher_high','higher_low',
                    'lower_high','lower_low','break_of_structure_up','break_of_structure_down') or re.fullmatch(
                    r'(?:false )?breakout (?:up|down) sur .+',text):
            return self.expression(text,field)[0]
        operators={'croise au-dessus de':'cross_above','croise au-dessous de':'cross_below',
                   '>=':'ge','<=':'le','>':'gt','<':'lt','=':'eq'}
        match=re.fullmatch(r'(.+?)\s+(croise au-dessus de|croise au-dessous de|>=|<=|>|<|=)\s+(.+)',text)
        if not match:fail(field,'Comparaison incomplète ou hors capacité. '+HELP['entry_rules'])
        left,unit=self.expression(match[1],field)
        scalar=re.fullmatch(r'([+-]?\d+(?:[.,]\d+)?)(\s*%)?',match[3])
        if scalar:
            if scalar[2] and unit!='RATIO':fail(field,'Un pourcentage ne se compare pas directement à un prix ou un volume.')
            n=Decimal(scalar[1].replace(',','.')) / (100 if scalar[2] else 1)
            right=dict(op='constant',value=format(n,'f'),unit=unit)
        else:right=self.ref(self.expression(match[3],field)[0])
        return dict(op=operators[match[2]],left=self.ref(left),right=right)

    def price(self,text,field):
        """The same series grammar, with a typed scalar offset; no executable text."""
        text=norm(text)
        offset='0';unit='PRICE'
        match=re.fullmatch(r'(.+) (plus|moins) (\d+(?:[.,]\d+)?) (ticks?|%|unites? de prix)',text)
        if match:
            text=match[1]
            offset=format(Decimal(match[3].replace(',','.'))*(-1 if match[2]=='moins' else 1),'f')
            unit='TICKS' if match[4].startswith('tick') else 'PERCENT' if match[4]=='%' else 'PRICE'
        scalar=re.fullmatch(r'[+-]?\d+(?:[.,]\d+)?',text)
        if scalar:expression=dict(op='constant',value=text.replace(',','.'),unit='PRICE')
        else:
            expression,kind=self.expression(text,field)
            def distance_only(node):
                if node.get('op') in ('atr','range','body','upper_wick','lower_wick','gap_size',
                                      'macd_line','macd_signal','macd_histogram'):return True
                return node.get('op') in ('lag','sma','highest','lowest') and distance_only(node['input'])
            if distance_only(expression):fail(field,'Une distance ou un oscillateur ne constitue pas un prix d’ordre.')
            if kind!='PRICE':fail(field,'Un niveau d’ordre exige un prix, pas un rendement ni un volume.')
        return dict(expression=expression,offset=offset,offset_unit=unit)

    def entry(self,text):
        declared=re.fullmatch(r"(long|short) sur ordre declare si (.+)",norm(text))
        if declared:return declared[1].upper(),dict(timing='DECLARED_ORDER',when=self.condition(declared[2],'entry_rules'))
        match=re.fullmatch(r"(long|short) a l'ouverture (?:immediatement )?suivante si (.+)",norm(text))
        if not match:fail('entry_rules',HELP['entry_rules'])
        return match[1].upper(),dict(timing='NEXT_BAR_OPEN',when=self.condition(match[2],'entry_rules'))

    def exit(self,text):
        result=dict(stop=None,target_r=None,when=None,max_bars=None);policy=None;seen=set()
        # Decimal dots are not clause separators. Empty / repeated clauses are rejected.
        parts=re.split(r'(?<!\d)\.(?!\d)|\n|;',text.strip().rstrip('.'))
        if len(parts)>8:fail('exit_rules','Trop de clauses de sortie.')
        for raw in parts:
            clause=norm(raw);key=None
            stop=re.fullmatch(r'stop fixe (?:au |a la )(plus bas|plus haut|cloture|ouverture) du signal (moins|plus) (\d+(?:[.,]\d+)?) ticks?',clause)
            target=re.fullmatch(r'objectif fixe (\d+(?:[.,]\d+)?)\s*r',clause)
            timed=re.fullmatch(r'sortir apres (\d+) barres?',clause)
            condition=re.fullmatch(r"sortir a l'ouverture suivante si (.+)",clause)
            if stop:
                key='stop';ref=self.ref(self.expression(stop[1],'exit_rules')[0])
                result[key]=dict(series=ref['name'],offset_ticks=format(Decimal(stop[3].replace(',','.'))*(-1 if stop[2]=='moins' else 1),'f'))
            elif target:key='target_r';result[key]=target[1].replace(',','.')
            elif timed:key='max_bars';result[key]=int(timed[1])
            elif condition:key='when';result[key]=self.condition(condition[1],'exit_rules')
            elif clause in ('positions ouvertes exclues de la mesure','positions ouvertes : resultat inconcluant'):
                key='open_policy';policy='CLOSED_ONLY' if clause=='positions ouvertes exclues de la mesure' else 'INCONCLUSIVE_IF_OPEN'
            else:fail('exit_rules','Clause non reconnue : « '+clause+' ». '+HELP['exit_rules'])
            if key in seen:fail('exit_rules','Deux clauses déclarent la même sortie : '+key+'. Précisez une seule valeur.')
            seen.add(key)
        if not policy:fail('exit_rules','Précisez le traitement des positions encore ouvertes. '+HELP['exit_rules'])
        return result,policy

def resolve(fields):
    """Pure resolution, including incomplete inputs. Never writes or fetches a profile."""
    f=clone(fields);issues=[];origins={};plan=None
    if f.get(MARKER)!=VERSION:
        return dict(fields=f,plan=None,issues=[dict(code='STANDARD_PROFILE_UNKNOWN',field=MARKER,
                    message='Version de saisie standard inconnue ; aucune substitution.',status='BLOCK')],provenance={})
    for key in (*AUTO,*DERIVED):f.pop(key,None)
    def put(key,value,status,source):
        if status=='AUTO' and key in fields and fields[key]!=value:
            issues.append(dict(code='STANDARD_AUTO_CONFLICT',field=key,message='Cette valeur diffère du protocole standard explicite ; utilisez une décision/protocole spécifique, sans substitution silencieuse.',status='BLOCK'))
        f[key]=value;origins[key]=dict(status=status,source=source,value=value)
    for key,value in BUDGET.items():put(key,value,'AUTO',DECISION+' — budget 1/0/1/1/1/1/1 ; aucun droit de lancement')
    put('scientific_nature','EXPLORATORY','AUTO',VERSION+' — périmètre explicite du nouveau formulaire standard')
    put('oos_policy','Période AUTO compatible affichée ; aucune réserve OOS créée et aucune indépendance présumée. Toute période ultérieurement exécutée sera tracée comme consultée.','AUTO',DECISION+' — décision OOS générique')
    put('revision_policy','Toute modification crée une version traçable ; la tentative précédente est conservée. Une nouvelle tentative nécessite son propre budget et une autorisation ; aucun droit antérieur hérité.','DERIVED','Contrats existants de versionnement, budget borné et autorisation du dossier courant ; ne définit pas une politique d’optimisation supplémentaire')
    put('closure_condition','Un essai maximum dans ce dossier, uniquement après autorisation. Clôture au statut terminal documenté : incident technique, résultat exploratoire ou inconcluant. Aucune validation scientifique automatique.','DERIVED','Budget générique max_total_runs=1 + cycle de vie et classement exploratoire existants')
    if f.get('initial_observation','').strip():put('primary_phenomenon',f['initial_observation'],'DERIVED','Copie exacte du phénomène unique déclaré dans initial_observation ; validateur de phénomène unique conservé')
    def capture(fn):
        try:return fn()
        except ContractError as exc:issues.append(exc.as_dict())
    for key in MANUAL:
        if not f.get(key,'').strip():issues.append(dict(code='STANDARD_FIELD_REQUIRED',field=key,message='Renseignez ce champ obligatoire.',status='BLOCK'))
        if len(f.get(key,''))>4000:issues.append(dict(code='STANDARD_TEXT_LIMIT',field=key,message='Saisie standard limitée à 4000 caractères par champ.',status='BLOCK'))
    if any(i['code']=='STANDARD_TEXT_LIMIT' for i in issues):return dict(fields=f,plan=None,issues=issues,provenance=origins)
    limit=capture(lambda:threshold(f['alternative_hypothesis_h1'])) if f.get('alternative_hypothesis_h1','').strip() else None
    if limit is not None:
        metric='moyenne non pondérée des rendements nets par opération en % du notionnel initial'
        put('null_hypothesis_h0',metric+' ≤ '+limit+' %. Complément du critère exploratoire déclaré ; aucun test statistique effectué.','DERIVED','H1 : mesure et seuil explicitement saisis')
        put('baseline','Seuil déclaré dans H1 : '+limit+' % du notionnel initial par opération ; référence de mesure, aucun carrier de comparaison.','DERIVED','H1 : seuil explicitement saisi')
        put('success_criteria',metric+' > '+limit+' % ; résultat exploratoire encourageant uniquement.','DERIVED','H1 + mesure effectivement supportée par le contrat déclaratif')
        put('rejection_criteria',metric+' ≤ '+limit+' % : non encourageant, aucun rejet statistique. Aucun trade ou mesure inexploitable : INCONCLUANT.','DERIVED','Complément du critère H1 + classement existant')
    rules=Rules(f.get('timeframes','').strip())
    entry=capture(lambda:rules.entry(f['entry_rules'])) if f.get('entry_rules','').strip() else None
    exit_=capture(lambda:rules.exit(f['exit_rules'])) if f.get('exit_rules','').strip() else None
    if entry:put('direction',entry[0],'DERIVED','Sens LONG/SHORT explicitement déclaré dans entry_rules')
    if entry and exit_ and limit is not None:
        definition=dict(version=CONTRACT_VERSION,asset=f.get('assets','').strip(),timeframe=rules.tf,direction=entry[0],
                        series=rules.series,entry=entry[1],exit=exit_[0],position=dict(max_open=1,signals_while_open='IGNORE'),
                        measurement=dict(metric='MEAN_NET_RETURN_PCT',operator='>',threshold=limit,open_policy=exit_[1]))
        from .methodology import attach
        plan=capture(lambda:compile_definition(attach(definition,f)))
    return dict(fields=f,plan=plan,issues=issues,provenance=origins)

def apply(draft):
    resolved=resolve(draft['fields'])
    for item in resolved['issues']:
        if item['code']=='STANDARD_AUTO_CONFLICT':
            raise ContractError(item['code'],item['field'],item['message'])
    draft['fields'].clear();draft['fields'].update(resolved['fields'])
    evidence=dict(type='STANDARD_AUTHORING_RESOLUTION',version=VERSION,
                  inputs_hash=digest({k:v for k,v in draft['fields'].items() if k not in (*AUTO,*DERIVED)}),
                  fields=resolved['provenance'],definition_hash=None if resolved['plan'] is None else resolved['plan']['definition_hash'])
    draft['provenance']=[p for p in draft.get('provenance',[]) if p.get('type')!='STANDARD_AUTHORING_RESOLUTION']+[evidence]
    return resolved
