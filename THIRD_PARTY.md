# Third-party components and provenance

## Distributed source

### Transkun

- Upstream: https://github.com/Yujia-Yan/Transkun
- Revision: `c5cb8370e17b4a1650b5971ba87ee4b0d208e5b6`, packaged version 2.0.1.
- License: MIT, retained at `piano/vendor/transkun/LICENSE`.
- Distributed subset: inference model source, feature/transformer layers, note utilities, CRF decoder and the author's packaged 2.0 configuration. Retained inference modules are unmodified; local package entry point adds a short notice.
- Model: Transkun V2 No Pedal Extension. Official-repository weight SHA256 `50a80010effc2a59ffcd068a95cd2b29bd7f23a27a3515bc3ccd209c89a3d44c`; published by the author in the MIT-licensed repository, with no separate weight-license file found. The application setup downloads the fixed upstream weight and verifies its hash; the checkpoint is excluded from this Git repository.
- Original adapter `piano/piano_worker.py` performs bounded local audio decoding, verifies weights/config, uses safe tensor-only checkpoint loading, calls the unmodified default decoder and emits progress/JSON. It does not read reference MIDI while predicting.
- Runtime additions: PyTorch 2.5.1+cpu and torchaudio 2.5.1+cpu from the official PyTorch wheel index; installed licenses remain in the runtime.
- Paper: Yujia Yan and Zhiyao Duan, Scoring intervals using non-hierarchical transformer for automatic piano transcription, ISMIR 2024, https://arxiv.org/abs/2404.09466 .

### PianoPlayer

- Upstream: https://github.com/marcomusy/pianoplayer
- Revision: `6fb0e2114d7b21f75c0be5208172e1243a57323e` (upstream version 3.0.2)
- License: MIT, retained verbatim at `piano/vendor/pianoplayer/LICENSE`.
- Distributed subset: `__init__.py`, `hand.py`, `models.py` and provenance JSON.
- Modification: the `models` import in `hand.py` was made relative for package isolation; otherwise the retained optimizer files are unmodified.
- Original integration: `piano/fingering.py` preserves explicit source hand labels, infers unlabelled hand routing and invokes the upstream optimizer. Valid upstream fingering is retained; local repair runs only for a physical conflict, followed by a separate output check. Simplification and all omitted/shortened events are accounted for. Upstream already provides chord optimization, hand-size support and annotation colors; those are not claimed as new algorithms here.

## Installed runtime and model

### ncmdump-local

- Upstream: https://github.com/Calvin-Vollerei/ncmdump-local
- Revision: `06c495d61e1347963fbef8d970033d5bc2f6bc0d`.
- License: MIT. Retained LICENSE, NOTICE and provenance are inside `piano/vendor/ncmdump_local/`.
- Subset: `aes_lite.py`, `ncm_core.py`, a minimal package entry point. The upstream GUI and CLI (including its source-file deletion option) are excluded.
- Original adapter `piano/ncm_convert.py` streams the container to a temporary file, validates decoded audio and preserves source files. Non-MP3 payloads use installed FFmpeg for actual MP3 encoding.
- `imageio-ffmpeg==0.6.0` is installed from PyPI; its wrapper is BSD-2-Clause, while the included FFmpeg binary and codecs retain their own upstream licenses. It is not included in this source archive.

### Spotify Basic Pitch

- Upstream: https://github.com/spotify/basic-pitch
- Release: 0.4.0, tag revision `9991303bba609a3b93089d13ec80d1d495083596`.
- License: Apache-2.0. LICENSE and NOTICE are retained in `licenses/Basic-Pitch-LICENSE` and `licenses/Basic-Pitch-NOTICE`.
- The official distribution bundles its `nmp.onnx` model under the repository's license. No separate model-license file was present in the checked distribution.
- Model SHA256: `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec`.
- PyPI wheel SHA256: `738adb503aae7fdfc7d1e1511aa0ce35052315f260a19531ef4c356708425db0`.
- Original adapter: `piano/transcribe_worker.py` decodes bounded audio, streams resampling, pins CPU ONNX execution, estimates tempo and emits JSON note events. The upstream package/model is installed, not modified.

Runtime dependencies and their exact tested versions are listed in `requirements-runtime.lock`. These packages retain their own installed license files. Major components: ONNX Runtime (MIT), librosa (ISC), NumPy/SciPy/scikit-learn (BSD), Mido (MIT), pySerial (BSD-3-Clause), SoundFile (BSD-3-Clause) and its packaged libsndfile (LGPL-2.1-or-later).

### Standalone Python bootstrap

The Linux installer can download CPython 3.11.14 from Astral's python-build-standalone release `20251014`. The archive SHA256 is `91ab434738647ab45d630aaa02e3808bb516239beeb52f7799c12a12d1557a38`. Its own license files remain inside the installed runtime. It is not bundled in the source archive.

## Firmware build dependencies

FastLED (https://github.com/FastLED/FastLED) and ArduinoJson (https://github.com/bblanchon/ArduinoJson) are MIT. Arduino ESP32 and its toolchain have their own retained package licenses. These dependencies are downloaded for builds and are not vendored in this source delivery. No compiled firmware is represented as hardware-tested.

## 蓝牙 MIDI（乐器数字接口）浏览器支持

### BLE-MIDI/WebMIDI

- 上游项目：https://github.com/BLE-MIDI/WebMIDI
- 版本：`0597f4092514607654ed3166527bea645d42188e`。
- 许可证：Apache-2.0，副本保存在 `licenses/BLE-MIDI-WebMIDI-LICENSE`。
- 接入内容：`static/ble_midi.js` 采用上游的浏览器连接流程并解析蓝牙 MIDI 数据包。它从浏览器直接打开标准蓝牙 MIDI 服务，因此不需要 Windows 先为设备创建 MIDI 输入端口。
- 运行要求：支持网页蓝牙的 Chromium（铬内核）浏览器，且钢琴正在广播蓝牙 MIDI 服务。手机应用可能占用设备连接；电脑连接前应先在手机端断开。

## Evaluated, not incorporated

PRamoneda/Automatic-Piano-Fingering (MIT research implementation), ByteDance piano_transcription and qiuqiangkong/piano_transcription_inference (separate code/model provenance), Chirality (AGPL with separate statistical-data considerations), onlaj/Piano-LED-Visualizer (MIT), serifpersia/pianolux-esp32 (MIT) and tiefenb/piano-vision-automatic-fingering-assignment (MIT) were reviewed as alternatives. No source code or pretrained weights from these projects is distributed here. A short upstream piano recording was used only in local validation and is excluded from deliverables.

## Online score search

`piano/midi_sources.py` is original standard-library provider code. It searches the official Mutopia website and preserves each score's title, composer, source URL and individual license. No website source code is copied. Individual downloaded scores keep their own licenses; the application's MIT license does not relicense music files. Only original synthetic audio is shipped as a test example; downloaded real performance evaluation audio/MIDI and cached search downloads are excluded from the application source archive.
