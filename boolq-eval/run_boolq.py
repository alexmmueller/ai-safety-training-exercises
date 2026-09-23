from inspect_ai import eval
from inspect_evals.boolq import boolq

results = eval(boolq(), model="ollama/qwen2.5:3b", limit=10, log_dir="/tmp/inspect_boolq_logs")
print(results)
