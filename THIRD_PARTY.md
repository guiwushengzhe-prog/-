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
- 该实现现用于读取歌曲元数据和保留非 Windows 的旧兼容路径；Windows 的实际音频解密已替换为下述 taurusxin/ncmdump。原适配器仍验证可解码音频、保留源文件，非 MP3 音频由 FFmpeg 实际转码。
- `imageio-ffmpeg==0.6.0` is installed from PyPI; its wrapper is BSD-2-Clause, while the included FFmpeg binary and codecs retain their own upstream licenses. It is not included in this source archive.

### taurusxin/ncmdump

- 上游：https://github.com/taurusxin/ncmdump ，固定版本1.5.1，提交 `76a55d862f767ee20ae417ecd128fde442eea77f`。
- 许可证：MIT，原文保留于 `licenses/ncmdump-LICENSE`。
- Windows 使用上游官方64位动态库（其他程序可调用的组件）执行音频解密；不调用会改写音频标签的 `FixMetadata`，因此 MP3 音频字节保持原样。
- `piano/download_ncmdump.py` 在项目 `.runtime/tools/ncmdump` 下准备固定组件，校验压缩包和动态库的 SHA-256（文件内容校验值）。不安装到系统目录，不删除原始文件。
- 官方压缩包 SHA-256：`fecd4ef9e9baa6c48a6ada7a733b0df7633dccbbe0d6da457ba61304fae0477c`；动态库 SHA-256：`77ee6fb899cb118567a9908c6e018b1d696ba353de6ffd9e3f960fd367822865`。

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

## 在线曲谱搜索

`piano/midi_sources.py` 使用原创代码接入 [Mutopia Project](https://www.mutopiaproject.org/)、[Ichigo's Sheet Music](https://ichigos.com/search)、[8notes](https://www.8notes.com/)、[MIDIWorld](https://www.midiworld.com/) 及 [MIDI Collection](https://midicollection.com/)，没有复制网站程序。通过公开搜索表单取得结果；Ichigo's 与8notes只选页面标记为钢琴独奏的版本。MIDIWorld及MIDI Collection为综合乐器档案，候选下载后另用已安装的Mido读取实际发声乐器，只有全部音符使用钢琴音色且不含打击乐的文件才进入练习，不把乐队合奏所有声部强行当作钢琴独奏。

每首曲谱保留来源提供的曲名、作者、原作、整理者、来源页面、下载地址及逐曲许可；网站未注明的字段不猜测补齐。未确认开放许可的曲目明确记录“来源网站未注明开放许可”，不以应用的 MIT 许可替代乐曲权利。仅原创合成示例音频随源码提供；下载的曲谱、演奏验证音频及缓存均不进入源码发布包。真实接入验证包括 [Ichigo's《菊次郎之夏》曲谱页面](https://ichigos.com/sheets/374)、[8notes《D大调卡农》钢琴版](https://www.8notes.com/scores/7351.asp) 及两个综合曲库的公开文件。

## 标题手写字体

- 字体：Ma Shan Zheng（马善政手写体），来源 [Google Fonts 官方字体目录](https://github.com/google/fonts/tree/main/ofl/mashanzheng)。
- 许可：SIL Open Font License 1.1，完整文本保存在 `licenses/Ma-Shan-Zheng-OFL.txt`。
- 仅下载固定品牌与界面标题所需的字形子集，嵌入本地样式表；运行时不请求 Google 或其他字体服务。正文、谱面与数字使用系统字体。
- 子集字形：琴光练习曲库设备与设置添加目我的；字体字节 SHA-256：`0068fb615a56294ecb48426ea101724ebb1a9ddd220a857f3b099414643deac5`。
