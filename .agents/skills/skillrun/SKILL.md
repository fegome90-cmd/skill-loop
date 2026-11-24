---
name: skillrun
description: "Trigger: skillrun, run a skillrun plugin. Direct the operator to launch the interactive CLI."
license: MIT
metadata:
  author: "fegome90-cmd"
  version: "1.0"
---

## Activation Contract

Use this skill when the operator asks to run or resume a skillrun plugin.

## Hard Rules

- Do not execute the command for the operator or simulate the run in chat.
- Do not answer prompts, confirm the synthesis, or reconcile on the operator's behalf.

## Execution Steps

1. Use the operator's plugin path, goal, workspace, and run ID. Keep placeholders
   for values they have not provided. To resume, show the original arguments.
2. Ask the operator to run this command from the skillrun checkout:

   ```bash
   uv run skillrun run <plugin.json> --goal "<goal>" --cwd <workspace> --run-id <id>
   ```

## Output Contract

Return the command for the operator to run, not a claimed run result.
For status and recovery commands, point to the [CLI reference](../../../README.md#cli).
