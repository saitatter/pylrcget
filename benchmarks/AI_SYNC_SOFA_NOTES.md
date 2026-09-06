# SOFA Research Benchmark Notes

Commit: `research(ai): benchmark sofa singing forced alignment`

SOFA is represented as an isolated research candidate only. The upstream
checkout was placed under `%LOCALAPPDATA%\PyLrcGet\research\SOFA` and was not
copied into the repository or the user Music share.

## Compatibility gate

- code license observed in checkout: MIT
- upstream runtime requirement: Python 3.8
- supported experiments: PyTorch, ONNX CPU, and ONNX GPU
- required external artifacts: a `.ckpt` model and a phoneme/G2P dictionary
- model license: unknown until a specific checkpoint is selected

An isolated Python 3.8 environment was created with Torch 2.4.1 CPU,
torchaudio 2.4.1, and the upstream requirements. The SOFA `infer.py --help`
CLI imports successfully. The repository still does not contain a pretrained
checkpoint, so no honest quality score can be reported. SOFA stays
research-only and is not installed in the application or Python 3.13 AI
runtime.
