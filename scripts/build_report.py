"""Build review reports from real outputs and Codex-authored observations; never generate or judge poses."""
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote
import argparse
import csv
import hashlib
import html
import json
import math
import re
from PIL import Image, ImageOps, ImageDraw, ImageFont

ASPECTS = {
    'head_neck': '头颈', 'torso_shoulders': '肩与躯干', 'arms': '双臂',
    'hands_contact': '手与接触', 'hips_legs_feet': '髋腿脚',
    'identity_wardrobe': '人物与服装', 'naturalness': '自然度', 'framing': '构图'
}
OPENING = 'Use case: identity-preserve, photorealistic fashion pose transfer.'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def local(root, rel):
    if not rel:
        return None
    p = (root / rel).resolve()
    if p == root or root not in p.parents:
        raise ValueError(f'Artifact path must be inside run folder: {rel}')
    return p


def write(root, filename, text):
    (root / filename).write_text(text, encoding='utf-8')


def build(manifest_path):
    file = Path(manifest_path).resolve(strict=True)
    root = file.parent
    data = json.loads(file.read_text(encoding='utf-8-sig'))
    sources = {s['id']: s for s in data['sources']}
    jobs = data['jobs']
    if len({j['id'] for j in jobs}) != len(jobs):
        raise ValueError('Duplicate job IDs')
    source_checks = []
    for source in sources.values():
        snapshot = local(root, source['snapshot'])
        original = Path(source['original_path'])
        source_checks.append(dict(
            id=source['id'], snapshot_ok=snapshot.is_file() and sha(snapshot) == source['sha256'],
            original_unchanged=(sha(original) == source['sha256']) if original.is_file() else None))
    rows, cards, markdown, checks = [], [], [], []
    output_hashes = []
    tiles = []
    for job in jobs:
        source = sources[job['source_id']]
        original = local(root, source['snapshot'])
        ref = job.get('reference')
        reference = local(root, ref['snapshot']) if ref else None
        output = local(root, job['output'])
        prompt = local(root, job['prompt'])
        errors = []
        dimensions = None
        output_hash = None
        if output.is_file():
            try:
                with Image.open(output) as im:
                    im.load()
                    dimensions = list(im.size)
                output_hash = sha(output)
                output_hashes.append(output_hash)
            except Exception as exc:
                errors.append(f'成图不可解码: {type(exc).__name__}')
        else:
            errors.append('未保存成图')
        prompt_stats = None
        if prompt.is_file():
            text = prompt.read_text(encoding='utf-8-sig').strip()
            paragraphs = re.split(r'\n\s*\n', text)
            prompt_stats = dict(words=len(text.split()), paragraphs=len(paragraphs))
            if not text:
                errors.append('提示词为空')
            if job['kind'] == 'reference':
                if not 550 <= prompt_stats['words'] <= 700:
                    errors.append('参考提示词不在550–700词范围')
                if len(paragraphs) not in (9, 10):
                    errors.append('参考提示词不是9/10段')
                if paragraphs[0] != OPENING or len(paragraphs) < 2 or not paragraphs[1].startswith('Edit IMAGE 1,'):
                    errors.append('参考提示词开头或图序声明不合格式')
        else:
            errors.append('未保存实际提示词')
        if job['kind'] == 'reference':
            if not reference or not reference.is_file() or sha(reference) != ref['sha256']:
                errors.append('参考快照缺失或哈希改变')
        elif not job.get('pose_design', '').strip():
            errors.append('原创动作缺少设计说明')
        ratio = data.get('requested', {}).get('aspect_ratio')
        if dimensions and ratio:
            try:
                w, h = map(float, ratio.split(':'))
                if abs(dimensions[0] / dimensions[1] - w / h) > .005:
                    errors.append(f'实际比例与请求{ratio}不符')
            except (ValueError, ZeroDivisionError):
                errors.append('请求比例格式无效')
        review = job.get('review') or {}
        aspects = review.get('aspects') or {}
        missing = [label for key, label in ASPECTS.items()
                   if not isinstance(aspects.get(key), str) or not aspects[key].strip()]
        reviewed = not missing and review.get('status') in ('pass', 'needs_adjustment', 'unjudgeable')
        review_label = {'pass': '通过', 'needs_adjustment': '需调整', 'unjudgeable': '无法判断'}.get(review.get('status'), '未检查')
        if not reviewed:
            review_label = '未完成检查'
        deviations = review.get('deviations') or []
        row = dict(id=job['id'], kind=job['kind'], source=source['original_path'],
                   reference=ref['source_path'] if ref else '', output=job['output'],
                   prompt=job['prompt'], dimensions=dimensions, output_sha256=output_hash,
                   prompt_stats=prompt_stats, visual_review=review_label,
                   missing_review_fields=missing, file_issues=errors,
                   deviations=deviations, status=job.get('status', 'UNKNOWN'),
                   pass_all=not errors and reviewed and review.get('status') == 'pass')
        checks.append(row)
        esc = html.escape

        def figure(rel, label):
            path = local(root, rel) if rel else None
            if not path or not path.is_file():
                return f'<figure><p class="missing">{esc(label)}：未提供</p></figure>'
            url = quote(rel.replace('\\', '/'), safe='/')
            return f'<figure><a href="{url}"><img loading="lazy" src="{url}" alt="{esc(label)}"></a><figcaption>{esc(label)}</figcaption></figure>'

        mid = figure(ref['snapshot'], '动作参考') if ref else '<figure><h3>原创动作设计</h3><p>' + esc(job.get('pose_design', '')) + '</p></figure>'
        size = '×'.join(map(str, dimensions)) if dimensions else '无成图'
        details = ''.join(f'<tr><th>{label}</th><td>{esc(str(aspects.get(key) or "未检查"))}</td></tr>' for key, label in ASPECTS.items())
        issue_text = '；'.join(errors) or '文件核验通过'
        dev_text = '；'.join(map(str, deviations)) or '未记录残余偏差'
        prompt_url = quote(job['prompt'].replace('\\', '/'), safe='/')
        cards.append(f'<article id="{esc(job["id"])}"><h2>{esc(job["id"])} · {review_label}</h2>'
                     f'<p>{esc(job["kind"])} · 实际尺寸 {size} · 任务状态 {esc(job.get("status", "UNKNOWN"))}</p>'
                     '<div class="triple">' + figure(source['snapshot'], '原模特') + mid + figure(job['output'], '最终成图') + '</div>'
                     f'<table>{details}</table><p><b>偏差/适配：</b>{esc(dev_text)}</p>'
                     f'<p>{esc(str(review.get("notes", "")))}</p><p><b>文件核验：</b>{esc(issue_text)}</p>'
                     f'<p><a href="{prompt_url}">实际完整提示词</a></p>'
                     '<details><summary>调用与修正记录</summary><pre>' + esc(json.dumps(job.get('attempts', []), ensure_ascii=False, indent=2)) + '</pre></details></article>')
        markdown.extend([f'## {job["id"]} · {review_label}', '', f'类型：{job["kind"]}；尺寸：{size}', '',
                         f'![原图]({quote(source["snapshot"], safe="/")})', '',
                         f'![参考]({quote(ref["snapshot"], safe="/")})' if ref else f'动作设计：{job.get("pose_design", "")}', '',
                         f'![成图]({quote(job["output"], safe="/")})', ''])
        markdown.extend(f'- {label}：{aspects.get(key) or "未检查"}' for key, label in ASPECTS.items())
        markdown.extend(['', f'偏差/适配：{dev_text}', f'文件核验：{issue_text}', '',
                         f'[实际提示词]({prompt_url})', '',
                         '调用记录：' + json.dumps(job.get('attempts', []), ensure_ascii=False), ''])
        rows.append([job['id'], job['kind'], source['original_path'], ref['source_path'] if ref else '',
                     job['output'], job['prompt'], size, review_label, dev_text, issue_text])
        tiles.append((job['id'], original, reference, output))
    unique = len(set(output_hashes)) == len(output_hashes)
    expected = data['expected_outputs']
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), expected_outputs=expected,
                  available_outputs=len(output_hashes), unique_output_hashes=unique,
                  source_checks=source_checks, requested=data.get('requested', {}),
                  visual_pass_count=sum(j['visual_review'] == '通过' and not j['missing_review_fields'] for j in checks),
                  complete=(len(jobs) == expected == len(output_hashes) and unique and
                            all(s['snapshot_ok'] and s['original_unchanged'] is True for s in source_checks) and
                            all(j['pass_all'] for j in checks)), jobs=checks)
    title = f'模特动作逐张对照 · {len(output_hashes)}/{expected}'
    page = ('<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{title}</title><style>body{{font:16px system-ui;max-width:1500px;margin:24px auto;padding:16px;background:#f3f3ef}}'
            'article{background:white;padding:20px;margin:24px 0;border-radius:12px}.triple{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}'
            'figure{margin:0;text-align:center}img{width:100%;height:540px;object-fit:contain}table{width:100%;border-collapse:collapse;margin-top:20px}'
            'th,td{border:1px solid #ddd;padding:8px;text-align:left}th{width:110px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.missing{color:#a33}'
            '@media(max-width:700px){.triple{grid-template-columns:1fr}img{height:420px}}</style>'
            f'<h1>{title}</h1><p>全部完成并通过：{report["complete"]}。文件核验与视觉结论分列，未检查不等于通过。</p>'
            '<p>请求参数：' + html.escape(json.dumps(data.get('requested', {}), ensure_ascii=False)) + '。实际输出见每张尺寸；未返回的模型和质量参数不宣称生效。</p>'
            '<p><a href="动作参考对照.jpg">全部参考对照</a> · <a href="生成总览.jpg">成图总览</a> · <a href="动作对应表.csv">对应表</a> · <a href="交付核验.json">核验记录</a></p>'
            + ''.join(cards) + '</html>')
    write(root, 'index.html', page)
    write(root, '逐张对照报告.md', '# ' + title + '\n\n' + '\n'.join(markdown))
    write(root, '交付核验.json', json.dumps(report, ensure_ascii=False, indent=2))
    with (root / '动作对应表.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['编号', '类型', '原图', '参考', '成图', '实际提示词', '实际尺寸', '视觉结论', '偏差适配', '文件核验'])
        writer.writerows(rows)
    if tiles:
        make_sheets(root, tiles)
    return report


def make_sheets(root, tiles):
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 18)
    except OSError:
        font = ImageFont.load_default()

    def cell(canvas, x, y, path, label):
        draw = ImageDraw.Draw(canvas)
        draw.text((x + 8, y + 8), label, fill='black', font=font)
        if path and path.is_file():
            try:
                with Image.open(path) as im:
                    thumb = ImageOps.contain(im.convert('RGB'), (312, 410))
                canvas.paste(thumb, (x + (320 - thumb.width) // 2, y + 35))
            except OSError:
                draw.text((x + 8, y + 60), '无法读取', fill='red', font=font)
        else:
            draw.text((x + 8, y + 60), '无图/原创设计', fill='gray', font=font)

    # Paginate to avoid huge canvases for many sources. index links always refer to the first sheet.
    for start in range(0, len(tiles), 8):
        chunk = tiles[start:start + 8]
        sheet = Image.new('RGB', (960, 460 * len(chunk)), '#eeeeec')
        for row, (jid, source, reference, result) in enumerate(chunk):
            for col, (path, label) in enumerate([(source, '原图'), (reference, '参考'), (result, '成图')]):
                cell(sheet, col * 320, row * 460, path, f'{jid} {label}')
        suffix = '' if start == 0 else f'_{start // 8 + 1:02}'
        sheet.save(root / f'动作参考对照{suffix}.jpg', quality=92)
    for start in range(0, len(tiles), 20):
        chunk = tiles[start:start + 20]
        sheet = Image.new('RGB', (1280, 460 * math.ceil(len(chunk) / 4)), '#eeeeec')
        for k, (jid, _, _, result) in enumerate(chunk):
            cell(sheet, k % 4 * 320, k // 4 * 460, result, jid)
        suffix = '' if start == 0 else f'_{start // 20 + 1:02}'
        sheet.save(root / f'生成总览{suffix}.jpg', quality=92)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    args = parser.parse_args()
    result = build(args.manifest)
    print(json.dumps({key: result[key] for key in ['expected_outputs', 'available_outputs', 'visual_pass_count', 'complete']}, ensure_ascii=False))
