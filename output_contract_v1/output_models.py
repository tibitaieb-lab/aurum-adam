"""ADAM proposal shape only; never an execution or scientific approval."""
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

VERSION = 'ADAM_PROPOSAL_V1'
Text = Annotated[str, StringConstraints(min_length=1, max_length=4000)]
Short = Annotated[str, StringConstraints(min_length=1, max_length=160)]
NullableText = Text | None
SHA = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{64}$')]
Nonce = Annotated[str, StringConstraints(pattern=r'^[a-f0-9]{32}$')]
SourceID = Annotated[str, StringConstraints(pattern=r'^ARKS_SRC_[A-Za-z0-9_-]{1,80}$')]
ChunkID = Annotated[str, StringConstraints(pattern=r'^chk_[a-f0-9]{64}$')]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)

class AuthorFields(StrictModel):
    # Same eight manual fields, in UI order. None means an explicit unresolved input.
    initial_observation: NullableText
    source_origin: Literal['PERSONAL', 'ARTICLE', 'BOOK', 'OTHER'] | None
    title: NullableText
    assets: Annotated[str, StringConstraints(min_length=1, max_length=40)] | None
    timeframes: Literal['M1', 'M5', 'M15', 'H1', 'H4', 'D1'] | None
    alternative_hypothesis_h1: NullableText
    entry_rules: NullableText
    exit_rules: NullableText

class Citation(StrictModel):
    source_id: SourceID
    chunk_id: ChunkID
    quote: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    relation: Literal['SUPPORT', 'CONTRADICTION', 'LIMITATION', 'BACKGROUND']
    interpretation: Text

class Reasoning(StrictModel):
    mechanism: Text
    causal_timing: Text
    falsification: Text
    objections: Annotated[list[Text], Field(min_length=1, max_length=12)]
    uncertainties: Annotated[list[Text], Field(min_length=1, max_length=12)]

class Decision(StrictModel):
    field: Short
    question: Text

class Boundary(StrictModel):
    mode: Literal['BEFORE_CLOSE', 'LOCAL_TIME']
    minutes: Annotated[int, Field(ge=1, le=1440)] | None
    time: Annotated[str, StringConstraints(pattern=r'^\d{2}:\d{2}$')] | None
    day_offset: Literal[0, 1] | None

class SignalTTL(StrictModel):
    value: Annotated[int, Field(ge=1, le=525600)]
    unit: Literal['MINUTES']
    mode: Literal['WALL_CLOCK', 'ELIGIBLE_SESSION_TIME']

class StrategyWindow(StrictModel):
    open: Annotated[str, StringConstraints(pattern=r'^\d{2}:\d{2}$')]
    close: Annotated[str, StringConstraints(pattern=r'^\d{2}:\d{2}$')]
    close_day_offset: Literal[0, 1]

class EntryOrder(StrictModel):
    version: Literal['AURUM_ENTRY_ORDER_V1']
    type: Literal['MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT']
    time_in_force: Literal['AUTO', 'UNTIL_SIGNAL_EXPIRY', 'SESSION_END', 'GTD', 'GTC']
    limit_price_text: NullableText
    stop_price_text: NullableText
    good_till: NullableText

class DayControls(StrictModel):
    version: Literal['AURUM_DAY_METHODOLOGY_V1']
    signal_tf: Literal['H1', 'M15', 'M5', 'M1']
    session_profile_id: Short | None
    alignment: Literal['CLOCK_ALIGNED', 'SESSION_ALIGNED'] | None
    overnight_policy: Literal['ALLOW', 'FORBID'] | None
    intrabar_tf: Literal['M1'] | None
    context_tf: Literal['H1', 'M15', 'M5', 'M1'] | None
    trigger_tf: Literal['M15', 'M5', 'M1'] | None
    context_text: NullableText
    setup_text: NullableText
    approach_text: NullableText
    touch_text: NullableText
    trigger_text: NullableText
    confirmation_text: NullableText
    invalidation_text: NullableText
    signal_ttl: SignalTTL | None
    strategy_window: Annotated[list[StrategyWindow], Field(min_length=1, max_length=8)] | None
    last_entry: Boundary | None
    force_flat: Boundary | None
    setup_family: Annotated[str, StringConstraints(min_length=1, max_length=80)] | None
    entry_order: EntryOrder | None

class Proposal(StrictModel):
    schema_version: Literal['ADAM_PROPOSAL_V1']
    request_id: Nonce
    registry_payload_sha256: SHA
    short_name: Short
    proposal_version: Annotated[str, StringConstraints(pattern=r'^\d+\.\d+\.\d+$', max_length=24)]
    methodology: Literal['DAY', 'SWING']
    disposition: Literal['PROPOSED', 'OUT_OF_SCOPE']
    author_fields: AuthorFields
    day_controls: DayControls | None
    reasoning: Reasoning
    citations: Annotated[list[Citation], Field(max_length=20)]
    decisions_required: Annotated[list[Decision], Field(max_length=0, description="Compatibility only; always empty. ADAMO chooses all unspecified design values.")]
    unsupported_capabilities: Annotated[list[Short], Field(max_length=20)]
