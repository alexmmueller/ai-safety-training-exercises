# AI safety experiments

Small, independent experiments in agent monitoring, model evaluation, and activation probing. Code, results, and reproduction instructions are organised by topic:

- [Behavioural classifiers](ontask-classifier/): LoRA fine-tuning on synthetic on-task/off-task actions.
- [Monitor comparison](monitor-comparison/): deterministic rules, a classifier, an LLM judge, and hybrid escalation.
- [Activation probes](hermes-plugins/local_activation_probe/): linear probes on local model activations.
- [Reasoning-trace monitoring](cot-monitor/): a small pilot; its initial detection was a false positive.
- [Inspect evaluation](boolq-eval/): an end-to-end benchmark smoke test.
- [Tool-call logging](hermes-plugins/observability_bridge/) and [sandbox preparation](docker-sandbox/).

**Scope:** Learning exercises and research prototypes, not validated safety tools. Datasets and evaluations are small or synthetic; results do not establish deployment reliability. The Docker sandbox remains a scaffold, not a verified containment system. Setup requirements vary by experiment; follow the instructions in its directory.
