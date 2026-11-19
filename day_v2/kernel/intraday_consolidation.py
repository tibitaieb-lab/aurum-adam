"""Session-aware boundaries around the existing OHLCV aggregation primitive.

Input minutes are start-labelled. Published bars are end-labelled, including M1
when it is scientific. Raw M1 passed to the intrabar resolver is never relabelled.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from .contracts import require, digest
from .session_profiles import SessionCalendar, local_instant, exploratory
from ._support.market_data import MarketBar
from ._support.resampling import FixedTimeframeResampler

VERSION = 'AURUM_INTRADAY_CONSOLIDATION_V1'
DURATIONS = {'M1':60,'M5':300,'M10':600,'M15':900,'M30':1800,'H1':3600,'H4':14400}


@dataclass(frozen=True)
class IntradayBar(MarketBar):
    period_start: datetime | None = None
    available_at: datetime | None = None
    open_timestamp: datetime | None = None
    source_hash: str = ''
    session_hash: str = ''
    completeness: str = 'COMPLETE'
    bid: dict | None = None
    ask: dict | None = None
    signal_side: str | None = None
    bid_volume: Decimal | None = None
    ask_volume: Decimal | None = None
    volume_semantics: str | None = None


def aggregate(minutes, requested, profile, *, alignment, source_hash, start, end, frontier=None, historical=False, _calendar=None, evaluation_start=None):
    require(set(requested) <= DURATIONS.keys() and bool(requested), 'INTRADAY_TIMEFRAME', 'day', 'Source M1 ; consolidation M5, M10, M15, M30, H1 ou H4.')
    require(alignment in ('CLOCK_ALIGNED', 'SESSION_ALIGNED'), 'INTRADAY_ALIGNMENT', 'day.alignment', 'Alignement explicite requis.')
    require(bool(source_hash), 'INTRADAY_SOURCE_HASH', 'dataset', 'Empreinte source requise.')
    calendar = _calendar or SessionCalendar(profile)
    sessions = calendar.intervals(start, end)
    cutoff = min(end, frontier) if frontier is not None else end
    if historical:
        require(profile['status'] in ('DOCUMENTED','DERIVED') or exploratory(profile,source_hash), 'UNKNOWN_SESSION', 'session_profile',
                'Un calendrier de simulation ne prouve pas une session historique.')
    flat_warnings=0;warmup_unqualified=0;warmup_incomplete=0
    selected = []
    previous = None
    symbol = None
    for bar in minutes:
        t = bar.datetime
        require(t.tzinfo is not None and t.second == t.microsecond == 0 and bar.timeframe == 'M1',
                'M1_TIMESTAMP_INVALID', 'dataset.M1', 'Minute UTC consciente du fuseau et alignée requise.')
        t = t.astimezone(timezone.utc)
        require(previous is None or t > previous, 'M1_DUPLICATE_OR_UNORDERED', 'dataset.M1', 'Minutes dupliquées ou non ordonnées.')
        previous = t
        if not start <= t < end or t + timedelta(minutes=1) > cutoff:
            continue
        require(symbol in (None, bar.symbol), 'M1_ASSET_MISMATCH', 'dataset.M1', 'Un seul actif par consolidation.')
        symbol = bar.symbol
        unknown_volume=(bar.volume is None and getattr(bar,'signal_side',None)=='BID'
                        and getattr(bar,'volume_semantics',None)=='UNKNOWN_GENERIC;PROVIDER_REPORTED_PER_SIDE')
        require(all(isinstance(getattr(bar, k), Decimal) and getattr(bar, k).is_finite() for k in ('open','high','low','close'))
                and 0 < bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
                and (unknown_volume or isinstance(bar.volume,Decimal) and bar.volume.is_finite() and bar.volume>=0),
                'OHLC_INVALID', 'dataset.M1', 'Minute OHLCV invalide.')
        assessment = calendar.assess(t, present=True,
            flat=historical and bar.open == bar.high == bar.low == bar.close,
            historical=historical,qualified_flat=calendar.research and getattr(bar,'signal_side',None)=='BID'
            and isinstance(getattr(bar,'bid',None),dict) and isinstance(getattr(bar,'ask',None),dict)
            and getattr(bar,'source_m1_count',None)==1 and getattr(bar,'has_internal_gap',None) is False)
        if evaluation_start is not None and t<evaluation_start and assessment['status'] not in ('PASS','WARNING'):
            warmup_unqualified+=1;continue
        require(assessment['status'] in ('PASS','WARNING'), assessment['code'], 'dataset.M1',
                f'{t.isoformat()} : {assessment["code"]} ; données conservées, aucune minute supprimée ou fabriquée.')
        if assessment['status']=='WARNING':flat_warnings+=1
        selected.append(bar)
    by_time = {b.datetime.astimezone(timezone.utc): b for b in selected}
    result = {tf: [] for tf in sorted(set(requested))}
    diagnostics = []
    if historical and calendar.expected(start) == 'UNKNOWN_SESSION':
        diagnostics.append(dict(code='UNKNOWN_SESSION_SKIPPED', at=start.isoformat(),
            reason='Unproven overnight coverage at left boundary; only known session intervals are consolidated.'))
    for session in sessions:
        a, b = session
        if a >= end or b <= start:
            continue
        for tf in result:
            step = timedelta(seconds=DURATIONS[tf])
            anchor = a if alignment == 'SESSION_ALIGNED' else local_instant(a.astimezone(calendar.zone).date(), '00:00', calendar.zone)
            opened = anchor + ((a - anchor) // step) * step
            while opened < min(b, end):
                closed = opened + step
                if opened < a or closed > b or opened < start or closed > end or closed > cutoff:
                    diagnostics.append(dict(code='PARTIAL_BAR_EXCLUDED', timeframe=tf, start=opened.isoformat(), end=closed.isoformat()))
                    opened = closed
                    continue
                expected = tuple(opened + timedelta(minutes=i) for i in range(DURATIONS[tf] // 60))
                missing = [t for t in expected if t not in by_time]
                if missing and all(calendar.entry_closed(t) for t in missing):
                    diagnostics.append(dict(code='DAY_CLOSED_INCOMPLETE_BAR_EXCLUDED',timeframe=tf,
                                            start=opened.isoformat(),end=closed.isoformat()))
                    opened=closed
                    continue
                if missing and evaluation_start is not None and closed<=evaluation_start:
                    warmup_incomplete+=1
                    diagnostics.append(dict(code='WARMUP_INCOMPLETE_BAR_EXCLUDED',timeframe=tf,start=opened.isoformat(),end=closed.isoformat(),missing_minutes=len(missing)))
                    opened=closed;continue
                require(not missing, 'M1_SCIENTIFIC_GAP', 'dataset.M1',
                        f'{tf} {opened.isoformat()} : {len(missing)} minute(s) attendue(s) absente(s) ; aucun cours fabriqué.')
                members = [by_time[t] for t in expected]
                native=all(getattr(x,'signal_side',None)=='BID' and x.volume is None for x in members)
                require(native or all(x.volume is not None for x in members),'VOLUME_CONTRACT_MIXED','data.volume','Ne pas mélanger volumes inconnus et génériques.')
                if native:
                    base=MarketBar(closed,symbol,tf,members[0].open,max(x.high for x in members),min(x.low for x in members),members[-1].close,None)
                else:base = FixedTimeframeResampler._aggregate([(x, x.datetime) for x in members], closed, symbol, tf)
                quotes = {} if not native else dict(signal_side='BID',volume_semantics='UNKNOWN_GENERIC;PROVIDER_REPORTED_PER_SIDE',
                    bid_volume=sum(x.bid_volume for x in members),ask_volume=sum(x.ask_volume for x in members))
                for side in ('bid', 'ask'):
                    q = [getattr(x, side, None) for x in members]
                    require(all(x is None for x in q) or all(isinstance(x, dict) for x in q),
                            'INCOMPLETE_QUOTE_SERIES', 'dataset.' + side, 'Cotations BID/ASK partiellement présentes.')
                    if q[0] is not None:
                        quotes[side] = dict(open=q[0]['open'], high=max(x['high'] for x in q), low=min(x['low'] for x in q), close=q[-1]['close'])
                result[tf].append(IntradayBar(**base.__dict__, period_start=opened, available_at=closed,
                                            open_timestamp=opened, source_hash=source_hash, session_hash=calendar.hash, **quotes))
                opened = closed
    report = dict(version=VERSION, source_hash=source_hash, source_timeframe='M1', requested=sorted(result),
                  alignment=alignment, timezone=profile['timezone'], session_hash=calendar.hash,
                  source_rows=len(selected), bars={tf: len(v) for tf, v in result.items()}, diagnostics=diagnostics,
                  session_qualification='EXPLORATORY_MODEL_NOT_CERTIFIED' if calendar.research else profile['status'],
                  flat_observed_exploratory_warnings=flat_warnings,
                  warmup_unqualified_minutes=warmup_unqualified,warmup_incomplete_bars=warmup_incomplete,
                  warmup_policy='OBSERVED_COMPLETE_CLOSES_CONTINUOUS_V1' if evaluation_start is not None else 'STRICT_COMPLETE_WINDOW')
    report['hash'] = digest(report)
    return {tf: tuple(v) for tf, v in result.items()}, report


def aggregate_progressive(minutes,requested,profile,*,alignment,source_hash,start,end,frontier=None,historical=False,evaluation_start=None):
    """Reuse native aggregation on physical sessions; I/O boundaries own no trading state."""
    calendar=SessionCalendar(profile);result={tf:[] for tf in sorted(set(requested))}
    iterator=iter(minutes);current=next(iterator,None);previous=None;selected=0;warnings=0;chunks=0;peak=0;diagnostics=[];diagnostic_count=0;warmup_unqualified=0;warmup_incomplete=0
    boundaries=[min(b,end) for a,b in calendar.intervals(start,end) if a<end and b>start]
    if not boundaries or boundaries[-1]<end:boundaries.append(end)
    beginning=start
    for boundary in boundaries:
        if boundary<=beginning:continue
        chunk=[]
        while current is not None and current.datetime<boundary:
            require(previous is None or current.datetime>previous,'M1_DUPLICATE_OR_UNORDERED','dataset.M1','Ordre strict conservé entre blocs.')
            previous=current.datetime;chunk.append(current)
            require(len(chunk)<=14400,'DAY_SESSION_BUFFER_LIMIT','dataset.M1','Fenêtre physique de plus de dix jours ; aucune coupure silencieuse.')
            current=next(iterator,None)
        values,report=aggregate(chunk,requested,profile,alignment=alignment,source_hash=source_hash,start=beginning,end=boundary,frontier=frontier,historical=historical,_calendar=calendar,evaluation_start=evaluation_start)
        for tf,rows in values.items():
            result[tf].extend(rows)
            from .contracts import MAX_SWING_DAY_BARS
            require(len(result[tf])<=MAX_SWING_DAY_BARS,'DATA_VOLUME_LIMIT','dataset.'+tf,'Plafond scientifique de 500000, amorçage compris.')
        warmup_unqualified+=report['warmup_unqualified_minutes'];warmup_incomplete+=report['warmup_incomplete_bars']
        selected+=report['source_rows'];warnings+=report['flat_observed_exploratory_warnings'];chunks+=1;peak=max(peak,len(chunk));diagnostic_count+=len(report['diagnostics'])
        diagnostics.extend(report['diagnostics'][:max(0,1000-len(diagnostics))]);beginning=boundary
    require(current is None,'M1_WINDOW_LEAKAGE','dataset.M1','Observation au-delà de la fin exclusive.')
    require(all(a.datetime<b.datetime for rows in result.values() for a,b in zip(rows,rows[1:])),'INTRADAY_BLOCK_BOUNDARY','dataset.DAY','Doublon ou désordre interblocs.')
    report=dict(version=VERSION,source_hash=source_hash,source_timeframe='M1',requested=sorted(result),alignment=alignment,timezone=profile['timezone'],session_hash=calendar.hash,
        source_rows=selected,bars={tf:len(rows) for tf,rows in result.items()},diagnostics=diagnostics,diagnostic_count=diagnostic_count,diagnostics_truncated=diagnostic_count>len(diagnostics),
        session_qualification='EXPLORATORY_MODEL_NOT_CERTIFIED' if calendar.research else profile['status'],flat_observed_exploratory_warnings=warnings,
        progressive=dict(physical_session_chunks=chunks,maximum_buffered_minutes=peak,position_state_owner='UNCHANGED_NATIVE_REPLAY_ENGINE'),
        warmup_unqualified_minutes=warmup_unqualified,warmup_incomplete_bars=warmup_incomplete,
        warmup_policy='OBSERVED_COMPLETE_CLOSES_CONTINUOUS_V1' if evaluation_start is not None else 'STRICT_COMPLETE_WINDOW')
    report['hash']=digest(report)
    return {tf:tuple(rows) for tf,rows in result.items()},report
