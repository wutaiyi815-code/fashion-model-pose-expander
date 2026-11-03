"""Plan local pose jobs without generation. Python 3, standard library only."""
from pathlib import Path
from collections import Counter
from datetime import datetime, timezone
import argparse
import hashlib
import json
import random
import shutil

EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'}


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f'{label} must be an integer >= {minimum}')
    return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def plan(config):
    target = Path(config['run_dir']).resolve()
    if target.exists():
        raise FileExistsError(f'Will not overwrite existing run: {target}')
    total = integer(config['total_per_image'], 'total_per_image', 1)
    constrained = integer(config['constrained_count'], 'constrained_count')
    libs = config.get('libraries', [])
    if constrained + sum(integer(x['per_image'], 'per_image') for x in libs) != total:
        raise ValueError('total_per_image != constrained_count + sum(library per_image)')
    sources = config['sources']
    if not sources:
        raise ValueError('At least one explicit source is required')
    seed = config.get('seed', random.SystemRandom().randrange(2 ** 53))
    rng = random.Random(seed)
    usage = Counter()
    excluded = {k: set(v) for k, v in config.get('exclude_by_source', {}).items()}
    for history_path in config.get('history_manifests', []):
        old = read_json(history_path)
        old_sources = {s['id']: s['sha256'] for s in old.get('sources', [])}
        for job in old.get('jobs', []):
            src_hash = old_sources.get(job.get('source_id'), old.get('source_sha256'))
            ref = job.get('reference') or {}
            ref_path = ref.get('source_path') or job.get('reference_source')
            ref_hash = ref.get('sha256')
            if not ref_path:
                continue
            if not ref_hash and Path(ref_path).is_file():
                ref_hash = sha(ref_path)
            if ref_hash:
                usage[ref_hash] += 1
            if src_hash:
                excluded.setdefault(src_hash, set()).update(
                    x for x in [ref_path, Path(ref_path).name, ref_hash] if x)
    manifest = {
        'schema_version': 1, 'status': 'PLANNED',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'generation_tool': 'built-in image_gen (not yet called)',
        'selection_seed': seed, 'library_count': len(libs),
        'expected_outputs': len(sources) * total,
        'total_per_image': total, 'constrained_count': constrained,
        'requested': config.get('requested', {'aspect_ratio': '3:4'}),
        'sources': [], 'jobs': [], 'history_manifests': config.get('history_manifests', [])
    }
    copies = []
    seen_sources = set()
    pools = {}
    for index, spec in enumerate(sources, 1):
        source = Path(spec['path']).resolve(strict=True)
        digest = sha(source)
        if digest in seen_sources:
            raise ValueError(f'Duplicate source content: {source}')
        seen_sources.add(digest)
        gender = spec['gender']
        sid = f'S{index:03}'
        base = f'models/{sid}'
        snap = f'{base}/inputs/original{source.suffix.lower()}'
        manifest['sources'].append(dict(id=sid, original_path=str(source),
                                        snapshot=snap, sha256=digest, gender=gender))
        copies.append((source, snap))
        selected = set()
        selections = []
        forbidden = excluded.setdefault(digest, set())
        for lib_index, lib in enumerate(libs):
            amount = lib['per_image']
            if not amount:
                continue
            if gender not in lib['gender_subdirs']:
                raise ValueError(f'No explicit routing for {gender}: {lib["name"]}')
            key = (lib_index, gender)
            if key not in pools:
                root = Path(lib['path']).resolve(strict=True)
                folder = (root / lib['gender_subdirs'][gender]).resolve(strict=True)
                if folder != root and root not in folder.parents:
                    raise ValueError('gender_subdirs must stay inside library root')
                unique = {}
                for file in sorted(folder.iterdir()):
                    if file.is_file() and file.suffix.lower() in EXTENSIONS:
                        unique.setdefault(sha(file), file)
                pool = list(unique.items())
                rng.shuffle(pool)
                if 'pool_limit' in lib:
                    pool = pool[:integer(lib['pool_limit'], 'pool_limit', 1)]
                pools[key] = pool
            eligible = [(h, p) for h, p in pools[key] if h not in selected
                        and not {h, str(p), p.name}.intersection(forbidden)]
            rng.shuffle(eligible)
            eligible.sort(key=lambda pair: usage[pair[0]])
            if len(eligible) < amount:
                raise ValueError(f'{source.name}: library {lib["name"]} has '
                                 f'{len(eligible)} eligible unused references; requires {amount}')
            for h, p in eligible[:amount]:
                selected.add(h)
                forbidden.add(h)
                usage[h] += 1
                selections.append((lib['name'], h, p))
        for number in range(1, total + 1):
            ref = None
            if number > constrained:
                lib_name, ref_hash, ref_path = selections[number - constrained - 1]
                ref_snap = f'{base}/references/{number:02}_{ref_path.name}'
                copies.append((ref_path, ref_snap))
                ref = dict(library=lib_name, source_path=str(ref_path),
                           snapshot=ref_snap, sha256=ref_hash)
            manifest['jobs'].append(dict(
                id=f'{sid}_{number:02}', source_id=sid,
                kind='reference' if ref else 'constrained', reference=ref,
                prompt=f'{base}/prompts/{number:02}.txt',
                output=f'{base}/results/{number:02}.png', status='PLANNED',
                pose_design='', visual_selection='Pending visual review',
                attempts=[], review=None))
    # All eligibility checks above happen before any run-directory mutation.
    target.mkdir(parents=True, exist_ok=False)
    for src, rel in copies:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        if sha(src) != sha(dest):
            raise OSError(f'Copy verification failed: {src}')
    for job in manifest['jobs']:
        for key in ['prompt', 'output']:
            (target / job[key]).parent.mkdir(parents=True, exist_ok=True)
    (target / 'config.json').write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    out = target / 'manifest.json'
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    print(plan(read_json(args.config)))
