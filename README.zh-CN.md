# LP Video Analysis Skill

面向 Agent 的通用视频理解 Skill。它用于把视频处理成结构化理解结果，包括媒体信息、转写、抽帧观察、语义分段、摘要、报告、问答上下文、搜索索引，以及可选的片段剪辑。

[English README](README.md)

## 这个项目做什么

- 使用 `ffprobe` 探测视频元信息。
- 使用 `ffmpeg` 抽取音频，供 ASR 转写。
- 按时间间隔抽帧，供视觉理解、OCR、画面描述使用。
- 校验外部 ASR 转写和 frame observations 文件。
- 从转写、画面观察和 metadata 自动构建语义分段。
- 定义通用的 `video_analysis.json` 结构。
- 校验语义分段、转写片段、可选片段计划。
- 从分析结果派生 Markdown 摘要。
- 从分析结果派生 `search_index.jsonl`，用于 Video RAG 或媒体资产搜索。
- 从分析结果派生可选的 `clip_plan.json`。
- 可选地剪辑片段、生成 SRT 字幕和静态 review 页面。

这个仓库本身不内置视频大模型。ASR、画面描述、OCR、多模态复核和结构化 JSON 生成，需要由你的 Agent 或模型栈提供。

## 快速开始

创建分析工作区：

```bash
python3 scripts/video_understanding.py init-analysis --output work/demo --scenario summary
```

探测视频：

```bash
python3 scripts/video_understanding.py probe examples/demo-input/original-product-video.mp4 --output work/demo/metadata.json
```

根据 metadata 自动选择成本策略：

```bash
python3 scripts/video_understanding.py plan-analysis \
  --metadata work/demo/metadata.json \
  --scenario report \
  --budget standard \
  --output work/demo/analysis_strategy.json
```

抽取音频和画面帧：

```bash
python3 scripts/video_understanding.py extract-audio input.mp4 --output work/demo/audio.wav
python3 scripts/video_understanding.py sample-frames input.mp4 --output-dir work/demo/frames --interval 30
```

校验模型生成的转写和画面观察：

```bash
python3 scripts/video_understanding.py validate-transcript assets/sample_transcript.json
python3 scripts/video_understanding.py validate-frames assets/sample_frame_observations.json
```

把抽帧交给多模态模型审阅，并导入模型结果：

```bash
python3 scripts/video_understanding.py prepare-frame-review \
  --frames-dir work/demo/frames \
  --interval 30 \
  --output work/demo/frame_review_manifest.json \
  --prompt-output work/demo/frame_review_prompt.md \
  --language Chinese

# 等 VLM 写出 work/demo/frame_review_output.json 后：
python3 scripts/video_understanding.py ingest-frame-review \
  --manifest work/demo/frame_review_manifest.json \
  --review work/demo/frame_review_output.json \
  --output work/demo/frame_observations.json
```

从模型输出构建 `video_analysis.json`：

```bash
python3 scripts/video_understanding.py build-segments \
  --transcript assets/sample_transcript.json \
  --frames assets/sample_frame_observations.json \
  --metadata work/demo/metadata.json \
  --output work/demo/video_analysis.json \
  --scenario summary
```

校验通用视频分析结果：

```bash
python3 scripts/video_understanding.py validate-analysis assets/sample_video_analysis.json
```

选择需要二次精看的候选窗口：

```bash
python3 scripts/video_understanding.py refine-plan \
  --analysis work/demo/video_analysis.json \
  --output work/demo/refine_plan.json
```

`refine-plan` 会按规则标记 `P0`、`P1`、`P2`：包括 segment importance 高、moment score 高、包含视觉价值或不确定关键词、有音频但没有转写、存在待确认问题等。后续只对这些窗口做加密抽帧和局部 ASR/VLM/OCR。

按二次精看计划准备重点窗口素材：

```bash
python3 scripts/video_understanding.py execute-refine-plan input.mp4 \
  --plan work/demo/refine_plan.json \
  --output-dir work/demo/refine \
  --priorities P0,P1
```

每个被选中的窗口会得到加密 `frames/`、需要 ASR 时的 `audio.wav`、`frame_review_manifest.json`、`frame_review_prompt.md` 和 `window.json`。等 ASR 和 VLM/OCR 的结果写入窗口目录后，再合回主分析：

```bash
python3 scripts/video_understanding.py merge-refine-results \
  --analysis work/demo/video_analysis.json \
  --execution-manifest work/demo/refine/refine_execution_manifest.json \
  --normalize-outputs \
  --output work/demo/video_analysis.refined.json
```

派生摘要、搜索索引和可选剪辑计划：

```bash
python3 scripts/video_understanding.py summary --analysis assets/sample_video_analysis.json --output work/demo/summary.md
python3 scripts/video_understanding.py search-index --analysis assets/sample_video_analysis.json --output work/demo/search_index.jsonl
python3 scripts/video_understanding.py derive-clips --analysis assets/sample_video_analysis.json --output work/demo/clip_plan.json
```

可选：剪辑片段并生成 review 页面：

```bash
python3 scripts/video_understanding.py cut examples/demo-input/original-product-video.mp4 --plan work/demo/clip_plan.json --output-dir work/demo/clips
python3 scripts/video_understanding.py page --plan work/demo/clip_plan.json --clips-dir work/demo/clips --source-video examples/demo-input/original-product-video.mp4 --copy-media --output work/demo/site/index.html
```

旧入口 `scripts/video_highlight.py` 仍然保留，但只作为兼容包装器，实际会转发到 `video_understanding.py`。

## 推荐的视频理解架构

```text
video
 -> ffprobe metadata
 -> plan-analysis
 -> ASR transcript with timestamps
 -> sampled frames
 -> VLM frame review + OCR
 -> build-segments
 -> video_analysis.json
 -> refine-plan
 -> dense candidate-window review
 -> refined video_analysis.json
 -> summary / search index / report / Q&A
 -> optional selected moments and ffmpeg clips
```

长视频不要一次性全部交给强多模态模型。更稳妥的方式是先用 ASR 和低频抽帧建立时间轴，再只对候选片段做多模态复核。

模型交接层是显式的：

```text
frames/*.jpg
 -> prepare-frame-review
 -> frame_review_manifest.json + frame_review_prompt.md
 -> 外部 VLM/OCR 模型
 -> frame_review_output.json
 -> ingest-frame-review
 -> frame_observations.json
```

二次精看也是显式产物：

```text
video_analysis.json
 -> refine-plan
 -> refine_plan.json
 -> execute-refine-plan
 -> 每个窗口的加密抽帧 + 局部音频 + frame review prompt
 -> 外部 ASR/VLM/OCR 输出
 -> merge-refine-results
 -> refined video_analysis.json
```

## 评估样例

Golden eval 样例放在 `examples/eval/`。它们不调用 ASR、OCR、VLM、`ffmpeg` 或 `ffprobe`，只验证稳定的工程契约：

```bash
python3 scripts/evaluate_fixtures.py
```

每个样例包含 `manifest.json`、稳定 metadata、transcript、frame observations，以及人工确认过的 `expected_video_analysis.json`。后续有真实业务视频时，按同样目录结构新增 case 即可。

## 输出结构

主产物：

```text
video_analysis.json
```

常见派生产物：

```text
summary.md
search_index.jsonl
可选：clip_plan.json
可选：clips/*.mp4
可选：clips/*.srt
可选：site/index.html
```

参考：

- [references/video-analysis-schema.md](references/video-analysis-schema.md)：通用视频理解 schema。
- [references/analysis-schema.md](references/analysis-schema.md)：可选片段剪辑计划 schema。

## 和原项目的关系

本仓库基于 [inhai-wiki/video-highlight-skill](https://github.com/inhai-wiki/video-highlight-skill) 改造。原项目使用 MIT License 发布，因此允许复制、修改、发布和再授权；我们保留了 MIT License，并保留 Git 历史中的原作者贡献记录。

我们参考了原项目的这些内容：

- Agent Skill 的组织方式：`SKILL.md`、`scripts/`、`references/`、`assets/`、`agents/`、`examples/`。
- 确定性媒体处理流程：`ffprobe` 探测、`ffmpeg` 抽音频、抽帧、剪辑、SRT 字幕和静态页面生成。
- 原有的可选片段计划结构和 demo 媒体处理流程。

我们修改和新增了这些部分：

- 将项目定位从“高光剪辑优先”改为“通用视频理解优先”。
- 新增 `video_analysis.json` 作为主产物。
- 新增 [references/video-analysis-schema.md](references/video-analysis-schema.md)。
- 新增 [scripts/video_understanding.py](scripts/video_understanding.py)，支持 `init-analysis`、`validate-analysis`、`validate-transcript`、`validate-frames`、`build-segments`、`summary`、`search-index`、`derive-clips` 等命令。
- 新增显式 transcript/frame observation 输入约定、VLM 抽帧审阅交接命令、`moments` 主字段和更适合 Video RAG 的 JSONL 输出。
- 保留 [scripts/video_highlight.py](scripts/video_highlight.py) 作为兼容包装器。
- 替换原来的高光剪辑首屏品牌图，改为 LP Video Analysis 封面。
- 新增 [assets/sample_video_analysis.json](assets/sample_video_analysis.json)。
- 新增基础单元测试。

## License

MIT。详见 [LICENSE](LICENSE)。
