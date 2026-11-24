"""Versioned JSON checkpoints; no pickle, eval, dynamic imports or constructors.

Checkpoints contain private authoritative state and are not NPC observations.
Only built-in world/entity/policy types are restored. Save at a completed tick
or completed resolution batch, never from inside a policy or active transaction.
"""
from dataclasses import fields, is_dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import platform
import random
import subprocess
import sys
import tempfile

FORMAT = 'eternia.checkpoint.v1'


def source_fingerprint():
    root = Path(__file__).resolve().parent
    digest = sha256()
    for path in [root.parent / 'main.py', *sorted(root.glob('*.py'))]:
        digest.update(path.name.encode('utf-8'))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_manifest(world):
    root = Path(__file__).resolve().parent.parent
    try:
        revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=all',
                                     '--', 'main.py', 'eternia'], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip())
    except (OSError, subprocess.CalledProcessError):
        revision = None
        dirty = None
    return dict(source_revision=revision, source_worktree_dirty=dirty,
                source_fingerprint=source_fingerprint(),
                python=platform.python_version(), world_type=type(world).__name__,
                seed=world.seed, ticks_per_year=getattr(world, 'ticks_per_year', None),
                shock_year=getattr(world, 'shock_year', None),
                policy_style=getattr(world, 'policy_style', None),
                adaptive_goals=getattr(world, 'adaptive_goals', None))


def _registries():
    from .model import Agent, Settlement
    from .community import Citizen, CommunityWorld, CommunityEngine
    from .civilizations import RegionalCitizen, CivilizationWorld
    from .institutions import Institution, InstitutionEngine
    from .regional_engine import RegionalInstitution, RegionalEngine
    from .institutional_world import InstitutionalWorld
    from .physical_world import PhysicalWorld
    from .society import SocietyWorld, SocietyEngine
    from .simulation import World
    from .actions import ActionEngine
    from .autonomy import GoalPolicy
    from .society_policy import CommunityPolicy
    from .institution_policy import InstitutionalPolicy
    from .regional_policy import RegionalPolicy
    from .logistics_policy import LogisticsPolicy
    from .logistics_engine import LogisticsEngine
    from .economic_policy import EconomicPolicy
    entities = {cls.__name__: cls for cls in
                (Agent, Settlement, Citizen, RegionalCitizen, Institution, RegionalInstitution)}
    policies = {cls.__name__: cls for cls in
                (GoalPolicy, CommunityPolicy, InstitutionalPolicy, RegionalPolicy, LogisticsPolicy, EconomicPolicy)}
    worlds = {cls.__name__: (cls, engine) for cls, engine in (
        (World, ActionEngine), (CommunityWorld, CommunityEngine),
        (InstitutionalWorld, InstitutionEngine), (CivilizationWorld, RegionalEngine),
        (PhysicalWorld, LogisticsEngine), (SocietyWorld, SocietyEngine))}
    return entities, policies, worlds


def _encode(value, entities, policies):
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Checkpoint state must contain finite numbers')
        return value
    if type(value) is list:
        return [_encode(item, entities, policies) for item in value]
    if type(value) in (tuple, set):
        values = list(value) if type(value) is tuple else sorted(value)
        return {'tag': type(value).__name__, 'items': [_encode(v, entities, policies) for v in values]}
    if type(value) is dict:
        return {'tag': 'dict', 'items': [[_encode(k, entities, policies), _encode(v, entities, policies)]
                                       for k, v in value.items()]}
    name = type(value).__name__
    if type(value) is entities.get(name) and is_dataclass(value):
        return {'tag': 'entity', 'class': name,
                'state': _encode({f.name: getattr(value, f.name) for f in fields(value)}, entities, policies)}
    if type(value) is policies.get(name):
        return {'tag': 'policy', 'class': name, 'state': _encode(vars(value), entities, policies)}
    raise ValueError('Unsupported checkpoint type: ' + name)


def _decode(value, entities, policies, depth=0):
    if depth > 160:
        raise ValueError('Checkpoint is nested too deeply')
    if value is None or type(value) in (bool, str, int):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError('Nonfinite checkpoint number')
        return value
    if type(value) is list:
        return [_decode(v, entities, policies, depth + 1) for v in value]
    if type(value) is not dict:
        raise ValueError('Invalid checkpoint value')
    tag = value.get('tag')
    if tag in ('tuple', 'set', 'dict'):
        if set(value) != {'tag', 'items'} or type(value['items']) is not list:
            raise ValueError('Invalid typed collection')
        items = [_decode(v, entities, policies, depth + 1) for v in value['items']]
        if tag == 'dict':
            result = {}
            for pair in items:
                if type(pair) is not list or len(pair) != 2:
                    raise ValueError('Invalid dictionary entry')
                key, item = pair
                if type(key) not in (str, int, tuple) or key in result:
                    raise ValueError('Invalid or duplicate dictionary key')
                result[key] = item
            return result
        return tuple(items) if tag == 'tuple' else set(items)
    if tag in ('entity', 'policy') and set(value) == {'tag', 'class', 'state'}:
        registry = entities if tag == 'entity' else policies
        cls = registry.get(value['class'])
        if cls is None:
            raise ValueError('Unknown checkpoint class')
        state = _decode(value['state'], entities, policies, depth + 1)
        if type(state) is not dict or not all(type(k) is str for k in state):
            raise ValueError('Invalid object state')
        if tag == 'entity':
            if set(state) != {f.name for f in fields(cls)}:
                raise ValueError('Incompatible entity fields')
            return cls(**state)
        # Built-in policies are deliberately small and have no world reference.
        allowed = {'reason', 'style'} if cls.__name__ == 'EconomicPolicy' else {'reason'}
        if set(state) - allowed:
            raise ValueError('Unsupported policy state')
        instance = cls(state.get('style', 'balanced')) if cls.__name__ == 'EconomicPolicy' else cls()
        instance.__dict__.update(state)
        return instance
    raise ValueError('Unknown checkpoint tag')


def _stable_bytes(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')


def checkpoint(world):
    entities, policies, worlds = _registries()
    if hasattr(world, 'demo'):
        raise ValueError('The isolated NPC demo has no resumable step loop; use an integrated world mode')
    if type(world).__name__ not in worlds or type(world) is not worlds[type(world).__name__][0]:
        raise ValueError('Unsupported world type')
    if (getattr(world, '_resolving', False) or getattr(world, '_transaction_active', False)
            or getattr(world, '_batch_remaining', None) is not None
            or getattr(world, '_pending_events', ())):
        raise ValueError('Save only between completed decisions or ticks')
    world._assert_invariants()
    state = {k: v for k, v in vars(world).items() if k not in ('action_engine', 'rng')}
    payload = dict(world_type=type(world).__name__, manifest=run_manifest(world),
                   state=_encode(state, entities, policies),
                   rng=_encode(world.rng.getstate(), entities, policies))
    return dict(format=FORMAT, sha256=sha256(_stable_bytes(payload)).hexdigest(), payload=payload)


def write_atomically(path, data):
    """Replace ``path`` with ``data`` in one step: a crash leaves the old file or the new one, never a mix."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', dir=path.parent, prefix=path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return path


def checkpoint_bytes(data):
    """A checkpoint as it is stored: its format and checksum first, then the payload."""
    return _stable_bytes(data)


def stored_checksum(path):
    """A stored checkpoint's own checksum, read from its header without loading the payload."""
    with open(path, 'rb') as stream:
        head = stream.read(256).decode('utf-8', 'replace')
    marker = '"sha256":"'
    start = head.find(marker)
    if not head.startswith('{"format":"' + FORMAT + '"') or start < 0:
        return None
    checksum = head[start + len(marker):start + len(marker) + 64]
    return checksum if len(checksum) == 64 and all(c in '0123456789abcdef' for c in checksum) else None


def save_world(world, path):
    data = checkpoint(world)  # Validate and serialize before touching an older save.
    return write_atomically(path, _stable_bytes(data))


def restore_checkpoint(data):
    entities, policies, worlds = _registries()
    if type(data) is not dict or set(data) != {'format', 'sha256', 'payload'} or data['format'] != FORMAT:
        raise ValueError('Unsupported checkpoint format')
    payload = data['payload']
    if sha256(_stable_bytes(payload)).hexdigest() != data['sha256']:
        raise ValueError('Checkpoint checksum does not match')
    if type(payload) is not dict or set(payload) != {'world_type', 'manifest', 'state', 'rng'}:
        raise ValueError('Invalid checkpoint envelope')
    manifest = payload['manifest']
    if manifest['source_fingerprint'] != source_fingerprint():
        raise ValueError('Checkpoint needs the exact simulation source version; migration is not implemented')
    if manifest['python'].split('.')[:2] != platform.python_version().split('.')[:2]:
        raise ValueError('Checkpoint needs the same Python major/minor version')
    if payload['world_type'] not in worlds:
        raise ValueError('Unknown checkpoint world type')
    cls, engine = worlds[payload['world_type']]
    state = _decode(payload['state'], entities, policies)
    if type(state) is not dict or any(type(k) is not str for k in state) or 'action_engine' in state or 'rng' in state:
        raise ValueError('Invalid authoritative state')
    world = cls.__new__(cls)  # No initialization, random draws or world decisions.
    world.__dict__.update(state)
    world.rng = random.Random()
    world.rng.setstate(_decode(payload['rng'], entities, policies))
    world.action_engine = engine(world)
    if (getattr(world, '_resolving', False) or getattr(world, '_transaction_active', False)
            or getattr(world, '_batch_remaining', None) is not None):
        raise ValueError('Checkpoint is inside an incomplete transaction')
    try:
        world._assert_invariants()
    except (AssertionError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('Checkpoint violates world invariants') from error
    return world


def load_world(path):
    path = Path(path)
    if path.stat().st_size > 512 * 1024 * 1024:
        raise ValueError('Checkpoint exceeds the 512 MiB reader limit')
    def reject_constant(value):
        raise ValueError('Invalid JSON number: ' + value)
    try:
        data = json.loads(path.read_text(encoding='utf-8'), parse_constant=reject_constant)
        return restore_checkpoint(data)
    except (KeyError, TypeError, RecursionError, OverflowError) as error:
        raise ValueError('Malformed checkpoint') from error

