#!/usr/bin/env node
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const script = path.resolve(__dirname, "..", "scripts", "video_understanding.py");
const result = spawnSync("python3", [script, ...process.argv.slice(2)], {
  stdio: "inherit"
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 0);
