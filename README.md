# Fashion Model Pose Expander

为服装模特原图扩展自然、松弛且有表现力的 Lookbook 站姿。工作流保持原人物身份、穿搭、配饰与摄影环境，通过受限原创动作或用户提供的动作参考库生成结果，并交付实际提示词、逐张视觉检查和可恢复报告。

## 基础信息

| 项目 | 内容 |
| --- | --- |
| 名称 | `fashion-model-pose-expander` |
| 类型 | Codex Skill / 图像生成与视觉验收工作流 |
| 源目录创建时间 | 2026-11-03 |
| 公开版本 | `2026.11.03` |
| 发布日期 | 2026-11-03 |
| 当前状态 | 可用；生成和逐图判断由 Codex 执行 |

入口文件是 `SKILL.md`；批次规划入口是 `scripts/plan_batch.py`；报告入口是 `scripts/build_report.py`。

## 适用场景

适用于单张测试、目录批量、继续补抽动作参考和针对失败结果的一次定向重做。支持受限原创动作、一个或多个动作参考库、按性别目录路由、历史去重和逐张三图对照。

不适用于只输出提示词而不生成图片、需要走外部付费模型 API、允许人物身份或服装随动作参考变化，或没有逐张视觉检查的批量盲生成。

## 严格输入要求

### 配置 JSON

使用 UTF-8 JSON，并执行：

```powershell
python -X utf8 scripts/plan_batch.py --config "<配置.json>"
```

必填字段：

```json
{
  "run_dir": "<一个尚不存在的新批次目录>",
  "sources": [
    {"path": "<原模特图片>", "gender": "女"}
  ],
  "total_per_image": 8,
  "constrained_count": 3,
  "libraries": [
    {
      "name": "动作库名称",
      "path": "<动作参考库根目录>",
      "gender_subdirs": {"女": "女", "男": "男"},
      "per_image": 5
    }
  ]
}
```

- `run_dir` 必须不存在，防止覆盖旧批次。
- `sources` 必须是 Codex 已看图确认的明确文件列表；脚本不根据文件名推断性别。
- 支持输入图片：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.tif`、`.tiff`。
- 数量必须满足 `total_per_image = constrained_count + sum(libraries[].per_image)`；均为非负整数，`total_per_image` 必须大于零。
- 每个动作库必须提供 `name`、`path`、`per_image`；`gender_subdirs` 把来源的性别值映射到子目录，单性别或无子目录库可映射为空字符串。
- `pool_limit` 可限制每库参与随机抽选的候选数，但不代表生成数量。
- 可选 `seed`、`requested`、`history_manifests` 和 `exclude_by_source` 用于复现、记录请求参数和历史排除。
- 库不足时规划阶段直接失败；不能重复凑数、换性别、静默减少数量或自动放宽站姿规则。

完整字段、manifest 状态及 `review` 八项结构见 `references/config-and-manifest.md`。

### 图像角色与顺序

- 参考迁移固定 `IMAGE 1 = 原模特图`，`IMAGE 2 = 动作参考图`。
- 受限原创动作只输入原模特图，不虚构 IMAGE 2。
- 每个动作独立从原图生成，不能把上一张结果作为下一张输入累积漂移。
- 原模特控制身份、脸、发型、肤色、体型、服装、鞋、配饰和背景；参考图只控制可见姿态。

### 提示词依据

生成前读取：

- `references/pose-transfer-system-prompt.txt`；
- `assets/动作修改1103.docx`、`references/word-prompt-examples.txt` 和图片对照；
- 有受限原创组时读取 `references/script-standing-system-prompt.txt`。

`references/tested-examples/` 仅提供写法示例，必须按当前原图和参考图重新分析，不能复制人物、服装或动作事实。

## 环境与依赖

- Python 3.10+。
- `Pillow`，用于报告尺寸、拼图和解码验证。
- Codex 内置 `image_gen` 与本地图像查看能力。
- 本流程不需要 RunningHub、ToAPI 或其他外部模型 API 密钥，也不会读取或保存这类密钥。

```powershell
python -m pip install -r requirements.txt
```

## 执行与验收

`plan_batch.py` 只完成数量校验、参考抽选、去重、输入快照和 manifest，不生成图片，也不判断动作语义。Codex 必须逐张查看原图和参考图，保存实际提交的完整提示词，再用内置图像生成工具独立生成每个动作。

每张结果必须检查：头颈、肩与躯干、双臂、手与接触、髋腿脚、人物与服装、自然度、构图。明显偏差可做一次定向修正，保留修正前图片、原因和两次提示词。

完成视觉记录后生成报告：

```powershell
python -X utf8 scripts/build_report.py --manifest "<批次目录>/manifest.json"
```

报告脚本验证文件、哈希、尺寸、提示词格式、数量和人工记录是否完整，但不会代替视觉判断。

## 交付物

- 每个动作的原始生成图和实际提示词。
- 原图、动作参考、提示词和结果的本地快照及 SHA-256。
- `index.html`、`逐张对照报告.md`、`动作对应表.csv`。
- `动作参考对照.jpg`、`生成总览.jpg`、`交付核验.json`。
- 带有任务状态、尝试记录、恢复句柄和逐项 review 的 `manifest.json`。

完整恢复、审核拦截和逐图验收规则见 `references/execution-and-review.md`。
