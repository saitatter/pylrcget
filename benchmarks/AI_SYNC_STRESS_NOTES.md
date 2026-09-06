# AI Sync Multilingual/Structural Stress Notes

Commit: `test(ai): add multilingual and structural stress regression suite`

The suite covers:

- text-first language detection for English, Romanian, French, and Spanish;
- 60-line repeated-chorus candidate selection with candidate input capped at
  five per line;
- 80-line sparse-evidence hierarchical segmentation with a fallback region
  retained for every line;
- validator detection of timestamp clusters, large jumps, and tail overflow.

The tests are deterministic and use no audio, model, network, or user-library
files. All 7 tests pass in the application venv. Real corpus quality remains a
separate gate for promoting research backends.
