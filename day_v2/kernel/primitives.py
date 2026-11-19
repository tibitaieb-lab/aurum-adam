"""Causal evaluation of a validated plan over immutable closed-bar views."""
from bisect import bisect_right
from decimal import Decimal, localcontext, DecimalException
from .contracts import require, digest


class Evaluator:
    def __init__(self, plan, series):
        self.plan=plan
        self.definition=plan['definition']
        self.series=series
        self.times={tf:tuple(b.datetime for b in bars) for tf,bars in series.items()}
        self.cache={}
        self.node_keys={}
        self.tf_cache={}
        self.pivots={}
        self.pivot_events=[]
        self.indicators={}
        self.swing_sources={}

    def frame(self, node):
        key=id(node)
        if key in self.tf_cache:return self.tf_cache[key]
        op=node['op']
        if op in ('field','atr','donchian_upper','donchian_lower','donchian_middle',
                  'macd_line','macd_signal','macd_histogram','ichimoku_tenkan',
                  'ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b',
                  'rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                  'plus_di','minus_di','adx','breakout_up','breakout_down',
                  'false_breakout_up','false_breakout_down','higher_high','higher_low',
                  'lower_high','lower_low','break_of_structure_up','break_of_structure_down',
                  'fractal_high','fractal_low','range','body','upper_wick','lower_wick',
                  'body_ratio','close_location','bullish_candle','bearish_candle',
                  'inside_bar','outside_bar','bullish_engulfing','bearish_engulfing',
                  'gap_size','gap_up','gap_down','nr4','nr7','range_expansion',
                  'range_contraction'):value={node['timeframe']}
        elif op=='constant':value=set()
        elif op=='ref':value=self.frame(self.definition['series'][node['name']]['expression'])
        elif 'input' in node:value=self.frame(node['input'])
        elif 'inputs' in node:value=set().union(*(self.frame(x) for x in node['inputs']))
        else:value=self.frame(node['left'])|self.frame(node['right'])
        self.tf_cache[key]=value
        return value

    def previous_time(self, tf, at, count):
        times=self.times.get(tf,())
        index=bisect_right(times,at)-1-count
        return times[index] if index>=0 else None

    def _rsi_values(self, tf, end):
        state=self.indicators.setdefault(('rsi',tf),{'last':-1,'values':[], 'previous':None,
            'count':0,'gain_sum':Decimal(0),'loss_sum':Decimal(0),'gain':None,'loss':None})
        for i in range(state['last']+1,end+1):
            source=self.series[tf][i].close
            current=None if source is None else Decimal(str(source))
            previous=state['previous']
            output=None
            if current is None:
                state.update(previous=None,count=0,gain_sum=Decimal(0),loss_sum=Decimal(0),gain=None,loss=None)
            elif previous is None:
                state['previous']=current
            else:
                change=current-previous
                gain=max(change,Decimal(0));loss=max(-change,Decimal(0))
                state['previous']=current
                if state['gain'] is None:
                    state['count']+=1;state['gain_sum']+=gain;state['loss_sum']+=loss
                    if state['count']==14:
                        state['gain']=state['gain_sum']/Decimal(14)
                        state['loss']=state['loss_sum']/Decimal(14)
                else:
                    state['gain']=(state['gain']*Decimal(13)+gain)/Decimal(14)
                    state['loss']=(state['loss']*Decimal(13)+loss)/Decimal(14)
                if state['gain'] is not None:
                    avg_gain=state['gain'];avg_loss=state['loss']
                    if avg_loss==0 and avg_gain>0:output=Decimal(100)
                    elif avg_gain==0 and avg_loss>0:output=Decimal(0)
                    elif avg_gain>0 and avg_loss>0:
                        output=Decimal(100)*avg_gain/(avg_gain+avg_loss)
            state['values'].append(output);state['last']=i
        return state['values']

    def _stochastic_values(self, tf, end):
        state=self.indicators.setdefault(('stochastic',tf),{'last':-1,'raw':[],'k':[],'d':[]})
        for i in range(state['last']+1,end+1):
            raw=None
            if i>=13:
                window=self.series[tf][i-13:i+1]
                highs=[bar.high for bar in window];lows=[bar.low for bar in window]
                close=self.series[tf][i].close
                if close is not None and all(v is not None for v in highs+lows):
                    upper=max(highs);lower=min(lows)
                    if upper!=lower:raw=Decimal(100)*(Decimal(str(close))-lower)/(upper-lower)
            state['raw'].append(raw)
            recent=state['raw'][-3:]
            slow_k=sum(recent,Decimal(0))/Decimal(3) if len(recent)==3 and all(v is not None for v in recent) else None
            state['k'].append(slow_k)
            recent=state['k'][-3:]
            slow_d=sum(recent,Decimal(0))/Decimal(3) if len(recent)==3 and all(v is not None for v in recent) else None
            state['d'].append(slow_d);state['last']=i
        return state

    def _stoch_rsi_values(self, tf, end):
        rsi=self._rsi_values(tf,end)
        state=self.indicators.setdefault(('stoch_rsi',tf),{'last':-1,'raw':[],'k':[],'d':[]})
        for i in range(state['last']+1,end+1):
            raw=None
            if i>=27:
                window=rsi[i-13:i+1]
                if all(v is not None for v in window):
                    upper=max(window);lower=min(window)
                    if upper!=lower:raw=Decimal(100)*(rsi[i]-lower)/(upper-lower)
            state['raw'].append(raw)
            recent=state['raw'][-3:]
            slow_k=sum(recent,Decimal(0))/Decimal(3) if len(recent)==3 and all(v is not None for v in recent) else None
            state['k'].append(slow_k)
            recent=state['k'][-3:]
            slow_d=sum(recent,Decimal(0))/Decimal(3) if len(recent)==3 and all(v is not None for v in recent) else None
            state['d'].append(slow_d);state['last']=i
        return state

    def _directional_values(self, tf, end):
        state=self.indicators.setdefault(('directional',tf),{'last':-1,'previous':None,'count':0,
            'tr_sum':Decimal(0),'plus_sum':Decimal(0),'minus_sum':Decimal(0),
            'smooth_tr':None,'smooth_plus':None,'smooth_minus':None,'dx_run':[],
            'adx_seed':None,'plus':[],'minus':[],'adx':[]})
        for i in range(state['last']+1,end+1):
            bar=self.series[tf][i]
            current=None if any(getattr(bar,k) is None for k in ('high','low','close')) else (
                Decimal(str(bar.high)),Decimal(str(bar.low)),Decimal(str(bar.close)))
            previous=state['previous'];plus_di=minus_di=dx=None
            if current is None:
                state.update(previous=None,count=0,tr_sum=Decimal(0),plus_sum=Decimal(0),
                    minus_sum=Decimal(0),smooth_tr=None,smooth_plus=None,smooth_minus=None,
                    dx_run=[],adx_seed=None)
            elif previous is None:
                state['previous']=current
            else:
                high,low,_=current;previous_high,previous_low,previous_close=previous
                up=high-previous_high;down=previous_low-low
                plus=up if up>down and up>0 else Decimal(0)
                minus=down if down>up and down>0 else Decimal(0)
                tr=max(high-low,abs(high-previous_close),abs(low-previous_close))
                state['previous']=current
                if state['smooth_tr'] is None:
                    state['count']+=1;state['tr_sum']+=tr
                    state['plus_sum']+=plus;state['minus_sum']+=minus
                    if state['count']==14:
                        state['smooth_tr']=state['tr_sum'];state['smooth_plus']=state['plus_sum']
                        state['smooth_minus']=state['minus_sum']
                else:
                    state['smooth_tr']=state['smooth_tr']-state['smooth_tr']/Decimal(14)+tr
                    state['smooth_plus']=state['smooth_plus']-state['smooth_plus']/Decimal(14)+plus
                    state['smooth_minus']=state['smooth_minus']-state['smooth_minus']/Decimal(14)+minus
                if state['smooth_tr'] is not None and state['smooth_tr']>0:
                    plus_di=Decimal(100)*state['smooth_plus']/state['smooth_tr']
                    minus_di=Decimal(100)*state['smooth_minus']/state['smooth_tr']
                    if plus_di+minus_di>0:
                        dx=Decimal(100)*abs(plus_di-minus_di)/(plus_di+minus_di)
            if dx is None:
                state['dx_run']=[];state['adx_seed']=None;adx=None
            else:
                state['dx_run'].append(dx)
                if len(state['dx_run'])>14:state['dx_run'].pop(0)
                if state['adx_seed'] is None:
                    if len(state['dx_run'])==14:state['adx_seed']=sum(state['dx_run'],Decimal(0))/Decimal(14)
                else:state['adx_seed']=(state['adx_seed']*Decimal(13)+dx)/Decimal(14)
                adx=state['adx_seed']
            state['plus'].append(plus_di);state['minus'].append(minus_di)
            state['adx'].append(adx);state['last']=i
        return state

    def _swing_events(self, tf, side, end):
        key=(tf,side)
        state=self.swing_sources.get(key)
        if state is None:
            field='high' if side=='high' else 'low'
            node={'op':'pivot_'+side,'input':{'op':'field','field':field,'timeframe':tf},'left':2,'right':2}
            state={'node':node,'last':-1,'events':[]};self.swing_sources[key]=state
        times=self.times.get(tf,())
        for i in range(state['last']+1,end+1):
            prior=len(self.pivot_events)
            self.value(state['node'],times[i])
            for event in self.pivot_events[prior:]:
                state['events'].append((i,Decimal(event['price'])))
            state['last']=i
        return [event for event in state['events'] if event[0]<=end]

    def named(self, name, at):
        return self.value(self.definition['series'][name]['expression'],at)

    def value(self, node, at):
        if at is None:return None
        identity=self.node_keys.setdefault(id(node),id(node))
        key=(identity,at)
        if key in self.cache:return self.cache[key]
        try:
            with localcontext() as ctx:
                ctx.prec=50
                result=self._value(node,at)
                if isinstance(result,Decimal) and not result.is_finite():result=None
        except (ZeroDivisionError, DecimalException):
            result=None
        self.cache[key]=result
        return result

    def _value(self,node,at):
        op=node['op']
        if op=='constant':return node['value'] if node['unit']=='BOOLEAN' else Decimal(node['value'])
        if op=='ref':return self.named(node['name'],at)
        if op=='field':
            tf=node['timeframe']; index=bisect_right(self.times.get(tf,()),at)-1
            return None if index<0 else getattr(self.series[tf][index],node['field'])
        if op in ('rsi','stochastic_k','stochastic_d','stoch_rsi_k','stoch_rsi_d',
                  'plus_di','minus_di','adx'):
            tf=node['timeframe'];end=bisect_right(self.times.get(tf,()),at)-1
            if end<0:return None
            if op=='rsi':return self._rsi_values(tf,end)[end]
            if op.startswith('stochastic_'):
                state=self._stochastic_values(tf,end)
                return state['k' if op.endswith('_k') else 'd'][end]
            if op.startswith('stoch_rsi_'):
                state=self._stoch_rsi_values(tf,end)
                return state['k' if op.endswith('_k') else 'd'][end]
            state=self._directional_values(tf,end)
            return state['plus' if op=='plus_di' else 'minus' if op=='minus_di' else 'adx'][end]
        if op in ('breakout_up','breakout_down','false_breakout_up','false_breakout_down'):
            tf=node['timeframe'];times=self.times.get(tf,());i=bisect_right(times,at)-1
            if i<0:return None
            level=self.value(node['level'],times[i]);bar=self.series[tf][i]
            if level is None or bar.close is None:return None
            if op.startswith('false_breakout_'):
                if op.endswith('_up'):
                    return None if bar.high is None else bar.high>level and bar.close<=level
                return None if bar.low is None else bar.low<level and bar.close>=level
            if i<1:return None
            previous_level=self.value(node['level'],times[i-1])
            previous_close=self.series[tf][i-1].close
            if previous_level is None or previous_close is None:return None
            return (previous_close<=previous_level and bar.close>level if op.endswith('_up')
                    else previous_close>=previous_level and bar.close<level)
        if op in ('higher_high','higher_low','lower_high','lower_low',
                  'break_of_structure_up','break_of_structure_down'):
            tf=node['timeframe'];times=self.times.get(tf,());i=bisect_right(times,at)-1
            if i<0:return None
            side='high' if op in ('higher_high','lower_high','break_of_structure_up') else 'low'
            if op.startswith('break_of_structure_'):
                if i<1:return None
                swings=self._swing_events(tf,side,i-1)
                previous=self.series[tf][i-1].close;current=self.series[tf][i].close
                if not swings or previous is None or current is None:return None
                level=swings[-1][1]
                return (previous<=level and current>level if op.endswith('_up')
                        else previous>=level and current<level)
            swings=self._swing_events(tf,side,i)
            if len(swings)<2:return None
            latest=swings[-1][1];previous=swings[-2][1]
            return latest>previous if op.startswith('higher_') else latest<previous
        if op in ('donchian_upper','donchian_lower','donchian_middle'):
            tf=node['timeframe'];n=node['periods'];end=bisect_right(self.times.get(tf,()),at)-1
            if end<n:return None
            prior=self.series[tf][end-n:end]
            highs=[b.high for b in prior];lows=[b.low for b in prior]
            if any(x is None for x in highs+lows):return None
            upper=max(highs);lower=min(lows)
            return upper if op=='donchian_upper' else lower if op=='donchian_lower' else (upper+lower)/Decimal(2)
        if op in ('ichimoku_tenkan','ichimoku_kijun','ichimoku_senkou_a','ichimoku_senkou_b'):
            tf=node['timeframe'];i=bisect_right(self.times.get(tf,()),at)-1
            needed=9 if op=='ichimoku_tenkan' else 52 if op=='ichimoku_senkou_b' else 26
            if i+1<needed:return None
            def midpoint(n):
                window=self.series[tf][i-n+1:i+1]
                highs=[b.high for b in window];lows=[b.low for b in window]
                return None if any(v is None for v in highs+lows) else (max(highs)+min(lows))/Decimal(2)
            if op=='ichimoku_tenkan':return midpoint(9)
            if op=='ichimoku_kijun':return midpoint(26)
            if op=='ichimoku_senkou_b':return midpoint(52)
            tenkan=midpoint(9);kijun=midpoint(26)
            return None if tenkan is None or kijun is None else (tenkan+kijun)/Decimal(2)
        if op in ('macd_line','macd_signal','macd_histogram'):
            tf=node['timeframe'];times=self.times.get(tf,());end=bisect_right(times,at)-1
            if end<0:return None
            state=self.indicators.setdefault(id(node),{'last':-1,'values':[],'fast':None,
                'slow':None,'signal':None,'line_count':0,'failed':False})
            for i in range(state['last']+1,end+1):
                x=self.series[tf][i].close
                if state['failed'] or x is None:
                    state['failed']=True;output=None
                else:
                    x=Decimal(str(x))
                    state['fast']=x if state['fast'] is None else (Decimal(2)*x+Decimal(11)*state['fast'])/Decimal(13)
                    state['slow']=x if state['slow'] is None else (Decimal(2)*x+Decimal(25)*state['slow'])/Decimal(27)
                    line=state['fast']-state['slow']
                    if i<25:output=None
                    else:
                        state['line_count']+=1
                        state['signal']=line if state['signal'] is None else (line+Decimal(4)*state['signal'])/Decimal(5)
                        output=(line if op=='macd_line' else
                                state['signal'] if op=='macd_signal' and state['line_count']>=9 else
                                line-state['signal'] if op=='macd_histogram' and state['line_count']>=9 else None)
                state['values'].append(output);state['last']=i
            return state['values'][end]
        if op in ('fractal_high','fractal_low'):
            tf=node['timeframe'];times=self.times.get(tf,());end=bisect_right(times,at)-1
            if end<4:return None
            state=self.pivots.setdefault(id(node),{'last':-1,'values':[],'value':None})
            for i in range(state['last']+1,end+1):
                if i>=4:
                    bars=self.series[tf][i-4:i+1]
                    field='high' if op=='fractal_high' else 'low'
                    values=[getattr(b,field) for b in bars]
                    if all(v is not None for v in values):
                        center=values[2]
                        if all(center>v if op=='fractal_high' else center<v for j,v in enumerate(values) if j!=2):
                            state['value']=center
                            self.pivot_events.append(dict(primitive=op,timeframe=tf,
                                pivot_time=times[i-2].isoformat(),available_at=times[i].isoformat(),price=str(center)))
                state['values'].append(state['value']);state['last']=i
            return state['values'][end]
        if op in ('range','body','upper_wick','lower_wick','body_ratio','close_location',
                  'bullish_candle','bearish_candle','inside_bar','outside_bar',
                  'bullish_engulfing','bearish_engulfing','gap_size','gap_up','gap_down',
                  'nr4','nr7','range_expansion','range_contraction'):
            tf=node['timeframe'];i=bisect_right(self.times.get(tf,()),at)-1
            if i<0:return None
            bar=self.series[tf][i]
            if op in ('nr4','nr7','range_expansion','range_contraction'):
                n=4 if op=='nr4' else 7 if op=='nr7' else 20
                if i+1<n:return None
                spans=[b.high-b.low if b.high is not None and b.low is not None else None
                       for b in self.series[tf][i-n+1:i+1]]
                if any(v is None for v in spans):return None
                if op in ('nr4','nr7'):return spans[-1]==min(spans)
                mean=sum(spans,Decimal(0))/Decimal(n)
                return spans[-1]>mean if op=='range_expansion' else spans[-1]<mean
            if any(getattr(bar,k) is None for k in ('open','high','low','close')):return None
            o,h,l,c=(getattr(bar,k) for k in ('open','high','low','close'))
            if op=='range':return h-l
            if op=='body':return abs(c-o)
            if op=='upper_wick':return h-max(o,c)
            if op=='lower_wick':return min(o,c)-l
            if op=='body_ratio':return None if h==l else abs(c-o)/(h-l)
            if op=='close_location':return None if h==l else (c-l)/(h-l)
            if op=='bullish_candle':return c>o
            if op=='bearish_candle':return c<o
            if i<1:return None
            prev=self.series[tf][i-1]
            if any(getattr(prev,k) is None for k in ('open','high','low','close')):return None
            po,ph,pl,pc=(getattr(prev,k) for k in ('open','high','low','close'))
            if op=='inside_bar':return h<ph and l>pl
            if op=='outside_bar':return h>ph and l<pl
            if op=='bullish_engulfing':return pc<po and c>o and o<=pc and c>=po
            if op=='bearish_engulfing':return pc>po and c<o and o>=pc and c<=po
            if op=='gap_size':return o-pc
            if op=='gap_up':return o>pc
            if op=='gap_down':return o<pc
        if op in ('pivot_high','pivot_low'):
            tf=next(iter(self.frame(node['input'])));times=self.times.get(tf,())
            end=bisect_right(times,at)-1
            key=id(node);state=self.pivots.setdefault(key,{'last':-1,'values':[],'value':None})
            for i in range(state['last']+1,end+1):
                candidate=i-node['right'];left=candidate-node['left']
                if left>=0:
                    values=[self.value(node['input'],times[j]) for j in range(left,i+1)]
                    value=values[node['left']]
                    if all(v is not None for v in values):
                        peers=values[:node['left']]+values[node['left']+1:]
                        if all(value>v if op=='pivot_high' else value<v for v in peers):
                            state['value']=value
                            self.pivot_events.append(dict(primitive=op,timeframe=tf,pivot_time=times[candidate].isoformat(),available_at=times[i].isoformat(),price=str(value)))
                state['values'].append(state['value']);state['last']=i
            return state['values'][end] if end>=0 else None
        if op in ('ema','atr'):
            tf=next(iter(self.frame(node)))
            times=self.times.get(tf,())
            end=bisect_right(times,at)-1
            if end<0:return None
            state=self.indicators.setdefault(id(node),{'last':-1,'values':[],'seed':None,'failed':False})
            for i in range(state['last']+1,end+1):
                if state['failed']:
                    value=None
                elif op=='ema':
                    x=self.value(node['input'],times[i])
                    if x is None:
                        state['failed']=True;value=None
                    else:
                        x=Decimal(str(x));previous=state['seed']
                        n=Decimal(node['periods'])
                        value=x if previous is None else (Decimal(2)*x+(n-Decimal(1))*previous)/(n+Decimal(1))
                else:
                    bar=self.series[tf][i]
                    previous_close=None if i==0 else self.series[tf][i-1].close
                    if any(x is None for x in (bar.high,bar.low,bar.close)) or (i>0 and previous_close is None):
                        state['failed']=True;value=None
                    else:
                        high,low=Decimal(str(bar.high)),Decimal(str(bar.low))
                        tr=high-low if i==0 else max(high-low,abs(high-Decimal(str(previous_close))),abs(low-Decimal(str(previous_close))))
                        previous=state['seed']
                        value=tr if previous is None else (tr+Decimal(13)*previous)/Decimal(14)
                state['seed']=value
                state['values'].append(value if i+1>=node['periods'] else None)
                state['last']=i
            return state['values'][end]
        if op in ('lag','sma','highest','lowest','return'):
            item=node['input'];tf=next(iter(self.frame(item)));n=node['periods']
            if op=='lag':return self.value(item,self.previous_time(tf,at,n))
            if op=='return':
                now=self.value(item,at);past=self.value(item,self.previous_time(tf,at,n))
                return None if now is None or past is None or past==0 else now/past-1
            values=[self.value(item,self.previous_time(tf,at,i)) for i in range(n)]
            if any(v is None for v in values):return None
            if op=='sma':return sum(values,Decimal(0))/Decimal(n)
            return max(values) if op=='highest' else min(values)
        if op=='not':
            value=self.value(node['input'],at)
            return None if value is None else not value
        if op in ('all','any'):
            values=[self.value(x,at) for x in node['inputs']]
            if any(v is None for v in values):return None
            return all(values) if op=='all' else any(values)
        left=self.value(node['left'],at);right=self.value(node['right'],at)
        if left is None or right is None:return None
        if op in ('cross_above','cross_below'):
            tf=next(iter(self.frame(node))) if 'day' in self.plan else self.definition['timeframe']
            previous=self.previous_time(tf,at,1)
            a=self.value(node['left'],previous);b=self.value(node['right'],previous)
            if a is None or b is None:return None
            return a<=b and left>right if op=='cross_above' else a>=b and left<right
        if op=='add':return left+right
        if op=='sub':return left-right
        if op=='mul':return left*right
        if op=='div':return None if right==0 else left/right
        if op=='gt':return left>right
        if op=='ge':return left>=right
        if op=='lt':return left<right
        if op=='le':return left<=right
        if op=='eq':return left==right
        raise AssertionError('Validated primitive missing: '+op)
