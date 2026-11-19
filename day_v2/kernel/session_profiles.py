"""Versioned market calendars and optional strategy windows, with no price access."""
from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from functools import lru_cache
from bisect import bisect_right
from .contracts import keys, require, integer, stamp, digest, clone

VERSION = 'AURUM_SESSION_PROFILE_V1'
AUTHORITY_VERSION = 'AURUM_SESSION_AUTHORITY_C21_V1'
RESEARCH_VERSION = 'AURUM_C21_EXPLORATORY_V2'


def exploratory(profile, source_hash=None):
    value = profile.get('research')
    if value is None:
        return False
    keys(value, ('version','mode','asset','dataset_id','file_sha256','manifest_sha256',
                 'gap_policy','flat_policy','training_policy','unknown_holidays','warning','session_policy'), 'session_profile.research')
    require(value['version']==RESEARCH_VERSION and value['mode']=='EXPLORATORY_RESEARCH'
            and profile['status']=='MODEL' and value['gap_policy']=='BLOCK_SELECTED_PERIOD'
            and value['flat_policy']=='OBSERVED_BIDASK_MODEL_WARNING'
            and value['training_policy']=='PREVIOUS_MONTH_ONLY'
            and value['session_policy']=='JOIN_MIDNIGHT_CONTINUATIONS;24H_CIVIL_BOUNDARY_MODEL'
            and value['unknown_holidays']=='UNKNOWN_NOT_CLOSED' and bool(value['warning']),
            'C21_RESEARCH_POLICY_INVALID','session_profile.research','Convention C21 exploratoire explicite et conservatrice requise.')
    for name in ('dataset_id','file_sha256','manifest_sha256'):
        require(isinstance(value[name],str) and len(value[name])==64 and all(c in '0123456789abcdef' for c in value[name]),
                'C21_SOURCE_IDENTITY','session_profile.research.'+name,'Empreinte de la source exacte requise.')
    if source_hash is not None:
        require(value['file_sha256']==source_hash,'C21_SOURCE_MISMATCH','session_profile','Calendrier lié à une autre source M1 ; aucune substitution.')
    return True


def clock(value, field):
    require(isinstance(value, str) and len(value) == 5, 'SESSION_TIME', field, 'Heure locale HH:MM requise.')
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        require(False, 'SESSION_TIME', field, 'Heure locale HH:MM invalide.')
    require(parsed.second == parsed.microsecond == 0, 'SESSION_TIME', field, 'Précision minute requise.')
    return parsed


def local_instant(day, hhmm, zone):
    """Ambiguous/nonexistent civil instants are never silently resolved."""
    naive = datetime.combine(day, clock(hhmm, 'session.time'))
    candidates = set()
    for fold in (0, 1):
        utc = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(utc)
    require(len(candidates) == 1, 'SESSION_DST_AMBIGUOUS_OR_MISSING', 'session.time',
            'Borne locale ambiguë ou inexistante au changement d’heure ; préciser le calendrier.')
    return next(iter(candidates))


def validate(profile):
    keys(profile, ('version', 'id', 'timezone', 'valid_from', 'valid_to', 'weekly',
                   'exceptions', 'status', 'reference'), 'session_profile', optional=('research','regimes','day_closure_policy'))
    require(profile['version'] == VERSION, 'SESSION_VERSION', 'session_profile', 'Version de session inconnue.')
    for field in ('id', 'reference'):
        require(isinstance(profile[field], str) and bool(profile[field].strip()),
                'SESSION_REFERENCE', 'session_profile.' + field, 'Identité et provenance de session requises.')
    require(profile['status'] in ('DOCUMENTED', 'DERIVED', 'MODEL', 'ASSUMED'),
            'SESSION_STATUS', 'session_profile.status', 'Statut documentaire ou modèle explicite requis.')
    try:
        ZoneInfo(profile['timezone'])
        start, end = date.fromisoformat(profile['valid_from']), date.fromisoformat(profile['valid_to'])
    except (ZoneInfoNotFoundError, TypeError, ValueError):
        require(False, 'SESSION_CALENDAR_INVALID', 'session_profile', 'Fuseau IANA et couverture datée requis.')
    require(start <= end, 'SESSION_COVERAGE', 'session_profile', 'Couverture de calendrier invalide.')
    require(isinstance(profile['weekly'], dict) and set(profile['weekly']) == set('0123456'),
            'SESSION_WEEK', 'session_profile.weekly', 'Définir les sept jours ; liste vide pour fermeture.')
    require(isinstance(profile['exceptions'], dict), 'SESSION_EXCEPTIONS', 'session_profile.exceptions', 'Exceptions datées attendues.')
    for key in profile['exceptions']:
        try:
            day = date.fromisoformat(key)
        except (TypeError, ValueError):
            require(False, 'SESSION_EXCEPTION_DATE', 'session_profile.exceptions', 'Date ISO requise.')
        require(start <= day <= end, 'SESSION_EXCEPTION_COVERAGE', 'session_profile.exceptions', 'Exception hors couverture.')
    for segments in (*profile['weekly'].values(), *profile['exceptions'].values()):
        validate_segments(segments)
    closure = profile.get('day_closure_policy')
    if closure is not None:
        keys(closure, ('version','month_day','status','scope','observations','reference'), 'session_profile.day_closure_policy')
        require(closure['version']=='AURUM_DAY_CLOSURE_POLICY_V1' and closure['month_day']=='12-25'
                and closure['status']=='MODEL' and closure['scope']=='DAY_NEW_ENTRIES_ONLY'
                and closure['observations']=='KEEP_OBSERVED_NO_FORCED_EXIT' and bool(closure['reference'])
                and exploratory(profile), 'DAY_CLOSURE_POLICY_INVALID', 'session_profile.day_closure_policy',
                'Fermeture expérimentale DAY explicite, sans suppression de cotations ni nouvelle liquidation.')
    if exploratory(profile):
        regimes=profile.get('regimes')
        require(isinstance(regimes,list) and 0<len(regimes)<=120,'C21_REGIMES_REQUIRED','session_profile.regimes','Régimes mensuels causaux bornés requis.')
        previous=None
        for r in regimes:
            keys(r,('valid_from','valid_to','weekly','trained_from','trained_before','status','evidence'),'session_profile.regime')
            first,last=date.fromisoformat(r['valid_from']),date.fromisoformat(r['valid_to'])
            require(start<=first<=last<=end and (previous is None or previous<first),
                    'C21_REGIME_OVERLAP','session_profile.regimes','Régimes ordonnés, disjoints et dans la couverture.')
            require(stamp(r['trained_from'])<stamp(r['trained_before'])<=local_instant(first,'00:00',ZoneInfo(profile['timezone']))
                    and r['status']=='MODEL','C21_CALENDAR_LOOKAHEAD','session_profile.regimes','Apprentissage strictement antérieur au régime applicable.')
            require(set(r['weekly'])==set('0123456'),'SESSION_WEEK','session_profile.regime.weekly','Sept jours explicites requis.')
            for segments in r['weekly'].values():validate_segments(segments)
            previous=last
    else:
        require('regimes' not in profile,'C21_RESEARCH_POLICY_REQUIRED','session_profile','Régimes exploratoires sans contrat explicite interdits.')
    return profile


def validate_segments(segments):
    require(isinstance(segments, list) and len(segments) <= 8, 'SESSION_SEGMENTS', 'session', 'Au plus huit plages par jour.')
    for segment in segments:
        keys(segment, ('open', 'close', 'close_day_offset'), 'session.segment')
        a, b = clock(segment['open'], 'session.open'), clock(segment['close'], 'session.close')
        offset = integer(segment['close_day_offset'], 'session.close_day_offset', 0, 1)
        require(offset == 1 or a < b, 'SESSION_ORDER', 'session', 'Fermeture strictement après ouverture.')


class SessionCalendar:
    def __init__(self, profile):
        self.profile = clone(validate(profile))
        self.hash = digest(self.profile)
        self.zone = ZoneInfo(profile['timezone'])
        self.first = date.fromisoformat(profile['valid_from'])
        self.last = date.fromisoformat(profile['valid_to'])
        self.research = exploratory(self.profile)
        self._indexed_sessions = None
        self._regime_starts = tuple(r['valid_from'] for r in self.profile.get('regimes',()))

    def rule(self, day):
        if not self.research:
            return self.profile['weekly']
        index=bisect_right(self._regime_starts,day.isoformat())-1
        if index>=0:
            r=self.profile['regimes'][index]
            if day.isoformat()<=r['valid_to']:return r['weekly']
        return None

    def expected(self, at, *, historical=True):
        """C21: calendar authority only; no inference from observed prices."""
        require(at.tzinfo is not None, 'SESSION_CLOCK', 'session', 'Timestamp conscient du fuseau requis.')
        civil = at.astimezone(self.zone).date()
        if not self.first <= civil <= self.last:
            return 'UNKNOWN_SESSION'
        if self.entry_closed(at):
            return 'EXPECTED_CLOSED'
        if self.rule(civil) is None:
            return 'UNKNOWN_SESSION'
        if historical and self.profile['status'] not in ('DOCUMENTED', 'DERIVED') and not self.research:
            return 'UNKNOWN_SESSION'
        # The preceding day's overnight interval is not certified at the left
        # coverage boundary. Do not turn its absence into an expected closure.
        if civil == self.first and any(s['close_day_offset'] for segments in self.rule(civil).values() for s in segments):
            current = self.day(civil)
            if not current or at < current[0][0]:
                return 'UNKNOWN_SESSION'
        return 'EXPECTED_OPEN' if self.containing(at) is not None else 'EXPECTED_CLOSED'

    def assess(self, at, *, present, flat=False, historical=True, qualified_flat=False):
        """A flat price alone never proves an observed executable market."""
        require(type(present) is bool and type(flat) is bool, 'SESSION_OBSERVATION', 'session', 'Présence/flat booléennes requises.')
        expected = self.expected(at, historical=historical)
        if self.entry_closed(at):
            return dict(version=AUTHORITY_VERSION, expected='EXPECTED_CLOSED',
                        observed='DATA_PRESENT' if present else 'DATA_ABSENT',
                        code='DAY_MODEL_CLOSED_OBSERVATIONS_RETAINED' if present else 'SESSION_MATCH',
                        status='WARNING' if present else 'PASS', qualification='EXPLORATORY_MODEL_NOT_CERTIFIED',
                        session_hash=self.hash)
        code = ('UNKNOWN_SESSION' if expected == 'UNKNOWN_SESSION' else
                'SESSION_DATA_CONFLICT' if expected == 'EXPECTED_CLOSED' and present else
                'SESSION_DATA_GAP' if expected == 'EXPECTED_OPEN' and not present else
                'FLAT_OBSERVED_EXPLORATORY' if present and flat and self.research and qualified_flat else
                'FLAT_BAR_SEMANTICS_UNKNOWN' if present and flat else 'SESSION_MATCH')
        return dict(version=AUTHORITY_VERSION, expected=expected, observed='DATA_PRESENT' if present else 'DATA_ABSENT',
                    code=code, status='PASS' if code == 'SESSION_MATCH' else 'WARNING' if code=='FLAT_OBSERVED_EXPLORATORY' else 'BLOCK',
                    qualification='EXPLORATORY_MODEL_NOT_CERTIFIED' if self.research else self.profile['status'],
                    session_hash=self.hash)

    def dates(self, at, *, trading_date_convention=None):
        """Expose dates without silently choosing a provider trading date."""
        require(trading_date_convention in (None, 'OPEN_DATE', 'CLOSE_DATE'),
                'TRADING_DATE_CONVENTION', 'session', 'Convention explicite de date de trading requise.')
        session = self.containing(at)
        opened = session[0].astimezone(self.zone).date() if session else None
        closed = session[1].astimezone(self.zone).date() if session else None
        trading = opened if trading_date_convention == 'OPEN_DATE' else closed if trading_date_convention == 'CLOSE_DATE' else None
        return dict(timestamp_utc=at.astimezone(timezone.utc).isoformat(),
                    calendar_date=at.astimezone(self.zone).date().isoformat(),
                    session_date=opened.isoformat() if opened else None,
                    trading_date=trading.isoformat() if trading else None,
                    trading_date_status='EXPLICIT_CONVENTION' if trading else 'UNKNOWN')

    @lru_cache(maxsize=4096)
    def day(self, day):
        require(self.first <= day <= self.last, 'SESSION_COVERAGE_MISSING', 'session_profile',
                'Le calendrier ne couvre pas cette date ; aucune fermeture présumée.')
        weekly=self.rule(day)
        require(weekly is not None,'UNKNOWN_SESSION','session_profile','Aucun régime causal disponible pour cette date ; aucune fermeture supposée.')
        segments = self.profile['exceptions'].get(day.isoformat(), weekly[str(day.weekday())])
        values = sorted((local_instant(day, s['open'], self.zone),
                         local_instant(day + timedelta(days=s['close_day_offset']), s['close'], self.zone)) for s in segments)
        if self.research and day>self.first and day.isoformat() in self._regime_starts and self.rule(day-timedelta(days=1)) is not None:
            # A new monthly forecast cannot split an already-open session at
            # midnight. Its rule governs new sessions only after that close.
            previous=self.day(day-timedelta(days=1))
            if previous:
                frontier=previous[-1][1]
                values=[(max(a,frontier),b) for a,b in values if b>max(a,frontier)]
        require(all(a < b for a, b in values) and all(x[1] <= y[0] for x, y in zip(values, values[1:])),
                'SESSION_OVERLAP', 'session_profile', 'Plages de marché invalides ou chevauchantes.')
        return tuple(values)

    def intervals(self, start, end):
        require(start.tzinfo is not None and end.tzinfo is not None and start <= end,
                'SESSION_CLOCK', 'session', 'Bornes conscientes du fuseau requises.')
        first = start.astimezone(self.zone).date()
        last = end.astimezone(self.zone).date()
        require(self.first <= first <= last <= self.last, 'SESSION_COVERAGE_MISSING', 'session_profile',
                'Couverture du calendrier insuffisante pour la période.')
        cursor = max(self.first, first - timedelta(days=1))
        values = []
        while cursor <= last:
            if self.rule(cursor) is not None:
                values.extend((a, b) for a, b in self.day(cursor) if a <= end and b > start)
            cursor += timedelta(days=1)
        values.sort()
        require(all(x[1] <= y[0] for x, y in zip(values, values[1:])),
                'SESSION_OVERLAP', 'session_profile', 'Chevauchement entre journées de marché.')
        return tuple(values)

    def containing(self, at, *, close_inclusive=False):
        if self.research:
            require(at.tzinfo is not None,'SESSION_CLOCK','session','Timestamp conscient du fuseau requis.')
            civil=at.astimezone(self.zone).date()
            require(self.first<=civil<=self.last,'SESSION_COVERAGE_MISSING','session_profile','Date hors couverture C21.')
            if self._indexed_sessions is None:
                cursor=self.first;values=[]
                while cursor<=self.last:
                    if self.rule(cursor) is not None:values.extend(self.day(cursor))
                    cursor+=timedelta(days=1)
                values.sort()
                require(all(x[1]<=y[0] for x,y in zip(values,values[1:])),'SESSION_OVERLAP','session_profile','Chevauchement de régimes C21.')
                self._indexed_sessions=(tuple(x[0] for x in values),tuple(values))
            opened,values=self._indexed_sessions;index=bisect_right(opened,at)-1
            if index>=0:
                a,b=values[index]
                if a<=at<b or close_inclusive and a<at==b:return a,b
                # Preserve the earlier session at a touching close/open boundary.
                if close_inclusive and at==a and index>0 and values[index-1][1]==at:return values[index-1]
            return None
        for a, b in self.intervals(at, at):
            if a <= at < b or (close_inclusive and a < at == b):
                return a, b
        # intervals uses a half-open overlap; include the previous minute for a close decision.
        if close_inclusive:
            for a, b in self.intervals(at - timedelta(microseconds=1), at):
                if a < at <= b:
                    return a, b
        return None

    def windows(self, session, policy):
        if policy is None:
            return (session,)
        validate_segments(policy)
        day = session[0].astimezone(self.zone).date()
        values = tuple((local_instant(day, s['open'], self.zone),
                        local_instant(day + timedelta(days=s['close_day_offset']), s['close'], self.zone)) for s in policy)
        require(all(session[0] <= a < b <= session[1] for a, b in values),
                'STRATEGY_WINDOW_OUTSIDE_MARKET', 'day.strategy_window', 'La fenêtre stratégique sort des heures de marché admises.')
        values = tuple(sorted(values))
        require(all(a[1] <= b[0] for a, b in zip(values, values[1:])), 'STRATEGY_WINDOW_OVERLAP',
                'day.strategy_window', 'Fenêtres stratégiques chevauchantes.')
        return values

    def eligible(self, at, window=None, *, decision=False):
        session = self.containing(at, close_inclusive=decision)
        if session is None:
            return False
        return any(a <= at < b or (decision and a < at == b) for a, b in self.windows(session, window))

    def entry_closed(self, at):
        """DAY entry calendar; observed prices and physical overnight sessions remain intact."""
        policy = self.profile.get('day_closure_policy')
        return bool(policy and at.astimezone(self.zone).strftime('%m-%d') == policy['month_day'])

    def entry_eligible(self, at, window=None, *, decision=False):
        return not self.entry_closed(at) and self.eligible(at, window, decision=decision)

    def elapsed(self, start, end, window=None):
        return sum((max(timedelta(0), min(b, end) - max(a, start))
                    for session in self.intervals(start, end) for a, b in self.windows(session, window)), timedelta(0))

    def boundary(self, session, policy):
        if policy is None:
            return None
        if policy['mode'] == 'BEFORE_CLOSE':
            return session[1] - timedelta(minutes=policy['minutes'])
        return local_instant(session[0].astimezone(self.zone).date() + timedelta(days=policy['day_offset']), policy['time'], self.zone)


def validate_boundary(policy, field):
    if policy is None:
        return
    require(isinstance(policy, dict), 'SESSION_BOUNDARY', field, 'Limite explicite requise.')
    if policy.get('mode') == 'BEFORE_CLOSE':
        keys(policy, ('mode', 'minutes'), field)
        integer(policy['minutes'], field + '.minutes', 1, 1440)
    else:
        keys(policy, ('mode', 'time', 'day_offset'), field)
        require(policy['mode'] == 'LOCAL_TIME', 'SESSION_BOUNDARY', field, 'Mode de limite inconnu.')
        clock(policy['time'], field + '.time')
        integer(policy['day_offset'], field + '.day_offset', 0, 1)
