# llm-harness

> Built for learning. A minimal tool-use loop around a local HuggingFace model — to understand how agents might work under the hood.

> "We have claude code at home"

## Run

```bash
pip install -r requirements.txt
python3 main.py --model Qwen/Qwen2.5-1.5B-Instruct
```

## Structure

| File | Purpose |
|---|---|
| `tools.py` | What the model can do |
| `harness.py` | The generation + tool-call loop |
| `cli.py` | Terminal UI |
| `main.py` | Entry point |
