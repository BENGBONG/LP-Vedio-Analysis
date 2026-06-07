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
 -> ASR transcript with timestamps
 -> sampled frames + captions + OCR
 -> build-segments
 -> video_analysis.json
 -> summary / search index / report / Q&A
 -> optional selected moments and ffmpeg clips
```

长视频不要一次性全部交给强多模态模型。更稳妥的方式是先用 ASR 和低频抽帧建立时间轴，再只对候选片段做多模态复核。

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
- 新增显式 transcript/frame observation 输入约定、`moments` 主字段和更适合 Video RAG 的 JSONL 输出。
- 保留 [scripts/video_highlight.py](scripts/video_highlight.py) 作为兼容包装器。
- 替换原来的高光剪辑首屏品牌图，改为 LP Video Analysis 封面。
- 新增 [assets/sample_video_analysis.json](assets/sample_video_analysis.json)。
- 新增基础单元测试。

## License

MIT。详见 [LICENSE](LICENSE)。
