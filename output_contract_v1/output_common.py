"""Dependency integrity and bounded JSON. No product store or network access."""
from __future__ import annotations
import hashlib, importlib, json, os, re, stat, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).resolve().parent
VERSION = 'ADAM_OUTPUT_CONTRACT_LOCAL_V1'
MAX_OUTPUT_BYTES = 128 * 1024
MAX_FILE_BYTES = 2 * 1024 * 1024
METHOD_IDS = {'ARKS_SRC_METHOD_DEMO'}

class Blocked(RuntimeError):
    pass

def need(condition, code):
    if not condition:
        raise Blocked(code)

def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)

def text_sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def checked(path, *, missing=False):
    path = Path(path).absolute()
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing and part == path:
                continue
            raise Blocked('PATH_ABSENT:' + str(part))
        need(not (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400),
             'LINK_OR_REPARSE_POINT:' + str(part))
    return path

def read_bytes(path):
    path = checked(path)
    need(path.is_file(), 'REGULAR_FILE_REQUIRED:' + path.name)
    with path.open('rb') as stream:
        before = os.fstat(stream.fileno())
        need(before.st_size <= MAX_FILE_BYTES, 'FILE_TOO_LARGE:' + path.name)
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    need(len(raw) == before.st_size and
         (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns),
         'FILE_CHANGED_DURING_READ:' + path.name)
    return raw

def file_sha(path):
    return hashlib.sha256(read_bytes(path)).hexdigest()

def strict_json(raw):
    def pairs(items):
        result = {}
        for k, v in items:
            need(k not in result, 'DUPLICATE_JSON_KEY')
            result[k] = v
        return result
    def constant(_):
        raise Blocked('NONFINITE_JSON')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError) as exc:
        raise Blocked('INVALID_JSON') from exc

def read_json(path):
    return strict_json(read_bytes(path))

REGISTRY_SHA = '1c5cb4b25178b14e4ce9915478b7aea454187124d2c4b58643294c630649db4e'

def load_registry():
    registry = read_json(HERE / 'PUBLIC_REGISTRY.json')
    payload = {k:v for k,v in registry.items() if k != 'registry_payload_sha256'}
    need(registry.get('registry_payload_sha256') == REGISTRY_SHA and text_sha(canonical(payload)) == REGISTRY_SHA,
         'PUBLIC_REGISTRY_CHANGED')
    return registry


def dependency_state():
    registry = load_registry()
    snapshots = {}
    for item in registry['source_files']:
        relative = Path(item['path'])
        need(not relative.is_absolute() and '..' not in relative.parts and relative.parts[:2] == ('day_v2','kernel'),
             'PUBLIC_NATIVE_PATH')
        path = ROOT / relative
        need(file_sha(path) == item['sha256'], 'PUBLIC_NATIVE_SOURCE_CHANGED:' + relative.as_posix())
        snapshots[path] = item['sha256']
    return snapshots, registry


def verify_self():
    manifest = read_json(HERE / 'PUBLIC_COMPONENT_MANIFEST.json')
    names = {'output_common.py','output_models.py','native_validation.py','proposal_validation.py'}
    need(set(manifest['files']) == names, 'PUBLIC_COMPONENT_COMPOSITION')
    for name, digest in manifest['files'].items():
        need(file_sha(HERE / name) == digest, 'PUBLIC_COMPONENT_CHANGED:' + name)
