"""Explicit calendar selection over the existing OHLC aggregation primitive.

No exchange calendar is inferred. An observed-only calendar is a MODEL with a
coverage warning; an expected-session list can prove missing source periods.
"""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .contracts import require, keys, integer, stamp, iso, digest, TIMEFRAMES
from ._support.market_data import MarketBar
from ._support.resampling import FixedTimeframeResampler

VERSION='AURUM_CALENDAR_PERIOD_V1'
CALENDAR_TIMEFRAMES=('W1','MN1')


@dataclass(frozen=True)
class CalendarBar(MarketBar):
    period_start: datetime | None = None
    available_at: datetime | None = None
    open_timestamp: datetime | None = None
    source_hash: str = ''
    calendar_hash: str = ''
    coverage_status: str = ''
    bid: dict | None = None
    ask: dict | None = None


def bar_start(bar):
    if bar.timeframe in CALENDAR_TIMEFRAMES:
        start=getattr(bar,'period_start',None)
        require(isinstance(start,datetime) and start.tzinfo is not None
                and start<bar.datetime and getattr(bar,'available_at',None)==bar.datetime,
                'CALENDAR_BAR_BOUNDS_REQUIRED','data.'+bar.timeframe,
                'Période et disponibilité explicites requises ; aucune durée mensuelle supposée.')
        return start
    require(bar.timeframe in TIMEFRAMES or bar.timeframe=='M1','TIMEFRAME_UNSUPPORTED','timeframe','Unité temporelle inconnue.')
    return bar.datetime-timedelta(seconds=60 if bar.timeframe=='M1' else TIMEFRAMES[bar.timeframe])


def validate(profile):
    keys(profile,('version','timezone','anchor_time','week_start','status','reference','completeness','expected_sessions'),'calendar')
    require(profile['version']==VERSION,'CALENDAR_VERSION','calendar','Version de calendrier inconnue.')
    require(profile['status'] in ('DOCUMENTED','MODEL','ASSUMED') and isinstance(profile['reference'],str)
            and bool(profile['reference'].strip()),'CALENDAR_PROVENANCE','calendar','Statut et provenance explicites requis.')
    try: zone=ZoneInfo(profile['timezone'])
    except (ZoneInfoNotFoundError,TypeError):
        require(False,'CALENDAR_TIMEZONE','calendar.timezone','Fuseau IANA absent ou inconnu.')
    value=profile['anchor_time']
    require(isinstance(value,str) and len(value)==5 and value[2]==':' and value[:2].isdigit() and value[3:].isdigit(),
            'CALENDAR_ANCHOR','calendar.anchor_time','Heure locale HH:MM requise.')
    hour,minute=map(int,value.split(':'))
    require(0<=hour<24 and 0<=minute<60,'CALENDAR_ANCHOR','calendar.anchor_time','Heure locale invalide.')
    if profile['week_start'] is not None:integer(profile['week_start'],'calendar.week_start',0,6)
    require(profile['completeness'] in ('EXPECTED_SESSIONS','OBSERVED_ONLY_WARNING'),
            'CALENDAR_COMPLETENESS','calendar','Politique de couverture explicite requise.')
    sessions=profile['expected_sessions']
    require(isinstance(sessions,list) and len(sessions)<=100000,'CALENDAR_SESSIONS','calendar','Liste de séances bornée requise.')
    require(bool(sessions)==(profile['completeness']=='EXPECTED_SESSIONS'),
            'CALENDAR_SESSIONS','calendar','Séances nécessaires uniquement pour une couverture documentée.')
    previous=None
    for row in sessions:
        keys(row,('start','end'),'calendar.expected_sessions')
        a,b=stamp(row['start']),stamp(row['end'])
        require(a<b and (previous is None or previous<=a),'CALENDAR_SESSIONS_ORDER','calendar','Séances ordonnées sans chevauchement requises.')
        previous=b
    return zone,hour,minute


def _local_boundary(year,month,day,hour,minute,zone):
    value=datetime(year,month,day,hour,minute,tzinfo=zone)
    # DST ambiguous/nonexistent anchors must not choose an undocumented fold.
    require(value.utcoffset()==value.replace(fold=1).utcoffset()
            and value.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)==value.replace(tzinfo=None),
            'CALENDAR_AMBIGUOUS_ANCHOR','calendar.anchor_time','Ancrage ambigu ou inexistant lors du changement d’heure.')
    return value


def bounds(at,timeframe,profile):
    zone,hour,minute=validate(profile)
    require(timeframe in CALENDAR_TIMEFRAMES,'CALENDAR_TIMEFRAME','timeframe','W1 ou MN1 requis.')
    local=at.astimezone(zone)
    if timeframe=='W1':
        integer(profile['week_start'],'calendar.week_start',0,6)
        day=local.date()-timedelta(days=(local.weekday()-profile['week_start'])%7)
        begin=_local_boundary(day.year,day.month,day.day,hour,minute,zone)
        if local<begin:day-=timedelta(days=7);begin=_local_boundary(day.year,day.month,day.day,hour,minute,zone)
        finish=day+timedelta(days=7)
        end=_local_boundary(finish.year,finish.month,finish.day,hour,minute,zone)
    else:
        year,month=local.year,local.month
        begin=_local_boundary(year,month,1,hour,minute,zone)
        if local<begin:
            year,month=(year-1,12) if month==1 else (year,month-1)
            begin=_local_boundary(year,month,1,hour,minute,zone)
        year,month=(year+1,1) if month==12 else (year,month+1)
        end=_local_boundary(year,month,1,hour,minute,zone)
    return begin.astimezone(timezone.utc),end.astimezone(timezone.utc)


def schedule(start,end,frequency,profile):
    tf={'WEEKLY':'W1','MONTHLY':'MN1'}.get(frequency)
    require(tf is not None,'REBALANCE_FREQUENCY','rebalance','Hebdomadaire ou mensuel requis.')
    _,at=bounds(start,tf,profile)
    result=[]
    while at<end:
        result.append(at)
        _,at=bounds(at,tf,profile)
        require(len(result)<=100000,'SCHEDULE_LIMIT','rebalance','Calendrier trop volumineux.')
    return tuple(result)


def aggregate(source,timeframe,profile,*,source_hash,coverage_start,coverage_end):
    validate(profile)
    require(source_hash and len(source_hash)==64,'CALENDAR_SOURCE_HASH','calendar','Empreinte de source requise.')
    require(all(b.timeframe=='D1' for b in source),'CALENDAR_SOURCE_TIMEFRAME','calendar','Source D1 uniquement ; jamais M1.')
    require(all(a.datetime<=bar_start(b) for a,b in zip(source,source[1:])),
            'CALENDAR_SOURCE_ORDER','calendar','Sources chevauchantes ou non ordonnées.')
    groups={};excluded=[];missing=[];bars=[]
    for bar in source:
        a,b=bounds(bar_start(bar),timeframe,profile)
        require(bar.datetime<=b,'SOURCE_CROSSES_CALENDAR_BOUNDARY','calendar','Une barre source traverse la frontière du calendrier choisi.')
        groups.setdefault((a,b),[]).append(bar)
    for session in profile['expected_sessions']:
        a,b=bounds(stamp(session['start']),timeframe,profile)
        groups.setdefault((a,b),[])
    for (a,b),members in sorted(groups.items()):
        if a<coverage_start or b>coverage_end:
            excluded.append(dict(start=iso(a),end=iso(b),reason='PARTIAL_PERIOD'));continue
        expected=[(stamp(s['start']),stamp(s['end'])) for s in profile['expected_sessions'] if a<=stamp(s['start'])<b]
        actual={(bar_start(s),s.datetime) for s in members}
        if profile['completeness']=='EXPECTED_SESSIONS':
            require(all(a<=x<y<=b for x,y in expected),'SESSION_CROSSES_PERIOD','calendar','Séance traversant la période.')
            require(not actual-set(expected),'UNDECLARED_SESSION','calendar','Barre hors calendrier des séances fourni.')
            absent=set(expected)-actual
            if absent:
                missing.extend(dict(start=iso(x),end=iso(y)) for x,y in sorted(absent))
                excluded.append(dict(start=iso(a),end=iso(b),reason='MISSING_EXPECTED_SESSION'));continue
        if not members:continue
        grouped=FixedTimeframeResampler._aggregate([(s,s.datetime) for s in members],b,members[0].symbol,timeframe)
        quotes={}
        for side in ('bid','ask'):
            if any(getattr(s,side,None) is not None for s in members):
                require(all(getattr(s,side,None) is not None for s in members),'CALENDAR_QUOTES_INCOMPLETE','calendar','Côtés de prix incomplets.')
                q=[replace(s,**getattr(s,side)) for s in members]
                value=FixedTimeframeResampler._aggregate([(s,s.datetime) for s in q],b,members[0].symbol,timeframe)
                quotes[side]={name:getattr(value,name) for name in ('open','high','low','close')}
        bars.append(CalendarBar(b,grouped.symbol,timeframe,grouped.open,grouped.high,grouped.low,grouped.close,grouped.volume,
                    period_start=a,available_at=b,open_timestamp=bar_start(members[0]),source_hash=source_hash,calendar_hash=digest(profile),
                    coverage_status=profile['completeness'],**quotes))
    return tuple(bars),dict(version=VERSION,source_hash=source_hash,calendar_hash=digest(profile),excluded=excluded,
        missing_sessions=missing,warning='SESSION_COMPLETENESS_UNPROVEN' if profile['completeness']=='OBSERVED_ONLY_WARNING' else None,
        actual_source_bars=len(source),result_bars=len(bars))
