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

# Lecture authoring

- Before writing or revising lecture prose, read profiles/computer-science/note-spec.md, including its plain-language workflow and teaching-quality review. Pass these instructions explicitly to any authoring subagent; it must read them before drafting.
- Author lecture prose directly in Codex unless the user explicitly requests a local text model. Existing local OCR/VLM/transcription evidence may be reused; do not relabel a local model's old prose as directly authored content.
- For a course series, read the latest preceding lecture notes and unresolved checks before finalizing the next lecture. Preserve the lecturer's progression, not merely the slide order.
- Explain mechanisms, workflows, structural levels and worked examples in straightforward Traditional Chinese. Keep source discrepancies explicit, with detailed auditing in the review list rather than dominating the main lesson.
- Complete a teaching-quality review as well as source-ID/time/hash validation. Mechanical coverage is not evidence that the explanation is complete or correct. Publish direct-authored chapters with editorial_publish.py; never resume the old local authoring worker over them.
