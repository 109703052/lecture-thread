# Local setup constraints

- Keep all Python dependencies in this project's .venv; never install into the user's Miniconda base.
- Do not change the graphics driver, global PATH, execution policy, or register a Windows service.
- Use run.py to scope caches and CUDA DLL paths. Use tools/uv/uv.exe with all UV paths scoped to this project.
- Keep original transcripts unchanged; write corrections and quality flags separately.
- Use run.py for VLM/grounding: it loads the tracked computer-science profile via profile_stage.py. Never invoke vendor VLM/grounding directly for CS courses. Follow profiles/computer-science/note-spec.md for authored notes.
- Preserve every slide occurrence, including revisits and annotation changes. Low keyword overlap is not evidence that a lecturer skipped content.
- Model inference stages run sequentially. Stop the project Ollama after work unless the user requests otherwise.
- Do not commit videos, model weights, caches, generated output, or the vendored repository.

- For continuation in a new chat, read local docs/HANDOFF.md before changing the project when it is available. It is not distributed with the public source; otherwise read README.md and docs/development.md. Its backlog is context, not blanket authorization to implement every item.
