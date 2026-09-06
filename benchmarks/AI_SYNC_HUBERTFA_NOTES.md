# HubertFA Research Benchmark Notes

Commit: `research(ai): benchmark hubertfa singing forced alignment`

HubertFA is represented as a specialized research candidate only. The
upstream checkout was placed under `%LOCALAPPDATA%\PyLrcGet\research\HubertFA`;
no repository or Music-share file was modified.

## Compatibility gate

- code license observed in checkout: Apache-2.0
- upstream runtime: Python 3.10
- documented languages: Chinese, Japanese, English, and Cantonese
- supported experiments: PyTorch, ONNX CPU, and ONNX GPU
- required external artifacts: ONNX/FA model and language-specific phoneme dictionary
- model license: unknown until a specific release artifact is selected

The checkout contains no model artifact, and this machine has no suitable
checkpoint/dictionary pair for a quality run. Its ONNX requirements also list
an older GPU package, while the available local PyTorch runtime is CPU-only.

An isolated Python 3.10 ONNX CPU environment was created and the upstream
`onnx_infer` module imports successfully. The available providers are
`AzureExecutionProvider` and `CPUExecutionProvider`. `setuptools<81` is pinned
in that research environment because the upstream librosa 0.9 import still
uses `pkg_resources`.

No measurement is promoted from this probe; the candidate remains outside the
production router and the Python 3.13 AI runtime until a model/dictionary pair
and a real singing corpus are available.
