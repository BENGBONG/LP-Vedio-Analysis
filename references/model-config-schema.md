# Model Config Schema

`model_config.json` defines how the workflow hands ASR, frame review, and OCR tasks to model providers.

The default configuration uses `handoff` mode. In that mode the script writes request and prompt files, then waits for an external model or Agent capability to produce the expected output.

## Shape

```json
{
  "schema": "model_config.v1",
  "default_language": "Chinese",
  "providers": {
    "asr": {
      "mode": "handoff",
      "name": "external-asr",
      "description": "Transcribe audio into timestamped transcript JSON.",
      "command": [],
      "api_key_env": "",
      "output_contract": "transcript.v1"
    },
    "frame-review": {
      "mode": "handoff",
      "name": "external-vlm",
      "description": "Review sampled frames with VLM/OCR and return frame observations.",
      "command": [],
      "api_key_env": "",
      "output_contract": "frame_observations.v1"
    },
    "ocr": {
      "mode": "handoff",
      "name": "external-ocr",
      "description": "Extract visible text from frames when a separate OCR provider is used.",
      "command": [],
      "api_key_env": "",
      "output_contract": "ocr_observations.v1"
    }
  }
}
```

## Provider Modes

- `handoff`: write a `model_request.v1` JSON file and Markdown prompt. A separate model step must write the expected output file.
- `command`: run a configured command list. This is for local wrappers or model CLIs that can produce the expected output file.
- `disabled`: skip the task.

## Command Placeholders

Command mode uses a list of arguments, not a shell string. Placeholders are substituted before execution.

Supported placeholders:

- `{audio}`: input audio path for ASR.
- `{manifest}`: frame review manifest path.
- `{prompt}`: existing frame review prompt path.
- `{frames_dir}`: sampled frames directory.
- `{output}`: expected provider output path.
- `{language}`: requested language.
- `{task}`: provider task name.
- `{request}`: generated model request JSON path.
- `{prompt_output}`: generated prompt path.

Example:

```json
{
  "mode": "command",
  "name": "local-asr-wrapper",
  "command": [
    "python3",
    "tools/local_asr.py",
    "--audio",
    "{audio}",
    "--output",
    "{output}",
    "--language",
    "{language}"
  ],
  "output_contract": "transcript.v1"
}
```

## Output Contracts

- ASR providers must write `transcript.json` as a list or object with a `transcript` list. Each item needs `start`, `end`, and `text`.
- Frame review providers must write `frame_review_output.json` with a `frames` list. `ingest-frame-review` normalizes it into `frame_observations.json`.
- OCR-only providers should write frame-level OCR observations. When possible, prefer the `frame-review` provider because it can combine caption, OCR, objects, and uncertainty in one pass.
