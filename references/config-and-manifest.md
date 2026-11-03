# 配置与清单

运行 `python -X utf8 scripts/plan_batch.py --config <UTF-8 JSON>`，只规划不生图，run_dir必须不存在。

```json
{
  "run_dir": "D:/动作测试/新批次_时间戳",
  "sources": [{"path": "D:/原图/模特.png", "gender": "女"}],
  "total_per_image": 8,
  "constrained_count": 3,
  "libraries": [{
    "name": "ColdCulture与Scuffers精选",
    "path": "D:/动作库/OK的",
    "gender_subdirs": {"女": "女", "男": "男"},
    "per_image": 5
  }],
  "seed": 20261103,
  "requested": {"aspect_ratio": "3:4", "resolution": "2K", "quality": "max"},
  "history_manifests": [],
  "exclude_by_source": {}
}
```

这是已测试的8=3＋5示例，不是固定要求。全参考5张设总数5、受限0、库配额5。多个库各填per_image，总和需匹配。每库可加pool_limit限制候选数。gender_subdirs可映射自定义文件夹或空字符串（库根目录），单性别库也明确映射。数字是非负整数，总数正数。

sources是Codex确认的文件列表；目录默认只枚举顶层图片，不扫描生成子目录。脚本不按文件名判断性别。性别路由用于用户素材分组，视觉不明确或组内混放须核实。

exclude_by_source将原图SHA256映射到已用参考文件名、路径或SHA256列表。history_manifests可读本skill清单或本次历史单原图source/jobs结构。历史参考无哈希且不可读取时按文件名保守排除。候选字节去重、随机打乱，可选pool_limit，跨模特优先低使用次数；不足在创建目录前失败，不重复凑数。视觉语义去重仍由Codex看图完成。

输出manifest.json含sources、jobs、expected_outputs、selection_seed、library_count、requested。source记录id/original_path/snapshot/sha256/gender。job含id/source_id/kind/reference/prompt/output/status/pose_design/visual_selection/attempts/review。reference含source_path/snapshot/sha256/library；kind=constrained时reference=null。路径是相对批次目录；原文件路径仅作追溯。

看图后更新visual_selection，不适合则换参考并同步快照、哈希。原创组填pose_design。完整提示词写到prompt指向的文本，成图保存到output。一个job对应一张独立结果，不能复用同一成图凑数。

attempts逐次追加工具、提交时间、输入图序、cell/job ID、实际提示词路径、结果或错误；不要删除旧尝试。视觉检查按下例填review，状态pass/needs_adjustment/unjudgeable。未填或缺项报告为未检查：

```json
{
  "status": "pass",
  "aspects": {
    "head_neck": "头向画面左侧，下巴微低，与参考接近",
    "torso_shoulders": "近正面，肩线松弛",
    "arms": "右臂下垂，左肘抬高，方向一致",
    "hands_contact": "左手接触现有衣领，未添加帽子",
    "hips_legs_feet": "双脚收拢、右膝略松，鞋均着地",
    "identity_wardrobe": "原身份、墨镜、夹克裤型和鞋保留",
    "naturalness": "关节接触自然",
    "framing": "头和双鞋完整，比例符合请求"
  },
  "deviations": ["服装结构不同，抓帽沿适配为现有衣领"],
  "notes": "适配未影响主要动作识别"
}
```

是否接受适配结合用户要求；全关节一致的任务不能把明显残差判通过。报告文件核验与视觉结论分列；请求分辨率/quality与实际值分列，未返回的模型字段不编造。
