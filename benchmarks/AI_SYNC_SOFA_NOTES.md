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

The local machine has no Python 3.8 interpreter and the repository does not
contain a pretrained checkpoint. Therefore no honest quality or latency score
can be reported yet. SOFA stays research-only and is not installed in the
application or Python 3.13 AI runtime.
