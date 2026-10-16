# Piano Light Studio · 钢琴灯光练习台

面向普通钢琴的本地测试版，支持两条路径：

1. 输入曲名 → 自动从公开曲库搜索、下载 MIDI → 安排双手指法 → 简谱与指法颜色灯光。
2. 导入 NCM/MP3 → 本地格式转换 → 钢琴专用模型识别音符 → 安排双手指法 → 简谱与指法颜色灯光。

无需账号或付费 API。音频和模型在本机处理；搜索 MIDI 时需要联网。

电脑负责转谱、左右手与指法、简谱和播放时间；ESP32 只接收灯珠编号、RGB 颜色和亮度。

软件不设置逐音修改的必经步骤，可以自动生成并预览完整练习。默认转谱模型为 Transkun V2；两首官方真实钢琴演奏对照的音高+起音 F1 为 98.85% / 99.71%，另测完整 MP3 为 98.80%。这些是小样本结果，不保证每段录音或生成的指法都正确。指法是程序安排的练习方案，音频和普通 MIDI 本身不记录原演奏者用了哪根手指。过密和弦、过大跨度和踏板残响会自动处理为简化练习版，省略和缩短记录随项目保留。验证范围见 [VALIDATION.md](VALIDATION.md)。

## 使用

完成下方安装并启动后，在运行软件的电脑浏览器打开 **http://127.0.0.1:18766**：

1. 输入曲名，例如“致爱丽丝”，点击“自动找 MIDI 并生成指法”；也可导入自己的 NCM/MP3/MIDI，或先体验示例曲。
2. 等待自动生成，选择慢速自动引导或手动逐组推进。
3. 谱面、琴键、指法图例和灯珠共享同一套颜色。左右手均以 1=拇指、2=食指、3=中指、4=无名指、5=小指编号。
4. 首次安装实体灯带时，在灯条设置中校准琴键与灯珠位置；校准会保存在当前浏览器，之后各首曲子复用。
5. 需要保存时，导出项目 JSON、灯光事件或 MIDI。

普通钢琴没有电子按键信号；当前提供定速引导、慢速、循环及手动下一组。暂停、拖动时间轴、切换练习和断开串口时会清灯。

指法优化复用 PianoPlayer；合格方案原样保留，冲突时才修复，最后独立检查持续音占指。MIDI 明确标有 RH/LH、Right Hand/Left Hand 或右手/左手时保留手别；其余音符按音高、同时发声、手型跨度与前后连续性自动推断。这个推断是启发式练习编配，尚无对照标准左右手的准确率。当前应用导入 MIDI；上游 PianoPlayer 的 MusicXML 功能尚未接入界面。

### 安装到另一台 Linux 电脑

```bash
git clone https://github.com/guiwushengzhe-prog/-.git piano-light-studio
cd piano-light-studio
./setup.sh
./run.sh
```

打开 http://127.0.0.1:18766 。`setup.sh` 在项目内安装依赖；Linux x86_64 缺少 Python 3.11 时，会下载经过 SHA256 校验的独立 Python。系统 Python 和系统软件包不会改变。初始化需要联网下载开源依赖及约 56 MB 的模型权重；权重从原作者的固定版本下载并进行 SHA256 校验，不存入 Git 历史。安装完成后的运行和转谱无需云服务。

运行端口可以通过 `./run.sh --port 18766` 指定。已有环境也可设置 `PIANO_PYTHON=/absolute/path/to/python ./run.sh`。转谱独立解释器可通过 `PIANO_ENGINE_PYTHON` 指定；默认使用同一环境。导入数据默认保存在项目 `.runtime/`，可通过环境变量 `PIANO_DATA_DIR` 更换目录。

### Windows / macOS

源码可使用 Python 3.11；这两个平台尚未实际验证。Windows 示例：

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -r requirements-runtime.lock
.venv\Scripts\python -m pip install --no-deps --require-hashes -r requirements-basic-pitch.lock
.venv\Scripts\python -m pip install --index-url https://download.pytorch.org/whl/cpu -r requirements-piano.txt
.venv\Scripts\python piano\download_model.py
.venv\Scripts\python -m piano.server
```

锁文件已在 Linux x86_64/Python 3.11 实测，其他平台能否取得相应 wheel 仍需验证。

## 自动处理范围

- 曲名搜索：当前已验证的来源是 Mutopia Project，主要覆盖古典钢琴作品；支持部分常见中文曲名的别名查询。会检查曲名相关性、作品身份、钢琴独奏属性、下载来源与 MIDI 文件结构，找不到匹配时明确失败。不会声称已覆盖所有流行歌曲。保存来源与逐曲许可；真实“致爱丽丝”已自动下载并生成 905 音符的双手指法与灯光。
- NCM：通过 MIT 开源 `ncmdump-local` 核心在本地提取内层音频；内层已是 MP3 时保留音频字节，FLAC 等格式通过本地 FFmpeg 实际转码为 MP3，然后自动转谱。源文件保留；完成后可下载转换的 MP3。
- MP3、WAV、FLAC、OGG：本机 CPU 自动转谱，单文件上限 64 MB、10 分钟。
- MIDI：直接读取音符和变速事件，最长 15 分钟，最多 20000 个钢琴音域音符。忽略打击乐通道，保留原始秒级时间；不支持独立轨道时间的 type 2。
- 简谱：包含升号、高低八度、左右手、指法及按时值绘制的标记，采用时序分组显示。自动选择一个 `1=...` 的记谱参考；它不是对原曲调式、拍号、连音、装饰音和原版排谱的完整还原。4/4 是界面分组参考。
- 指法：根据手型尺寸、音符顺序、和弦、持续音和手的跨度自动安排；提供 S/M/L 等手型设置。
- 简化：在无法同时分配的密集片段保留旋律、低音和可弹的和声音；自动缩短导致指法冲突的延音。源音符全部保留在 `source_notes`，生成记录在 `fingering`，调整手型后从原始音符重新生成。

独奏钢琴录音是当前优先支持的输入。Transkun 采用作者默认的 No Pedal Extension 模型，处理速度比轻量模型慢；本机完整 67 秒 MP3 的模型推理约 96 秒，含加载与节拍估计约 119 秒。人声、鼓和多种乐器混在一起的商业歌曲不能保证转成准确的钢琴编曲。软件不要求人工纠错，但自动运行成功不等于逐音准确或经过钢琴教师审核。Basic Pitch 保留为显式可选的快速实验路径，可用 `PIANO_TRANSCRIPTION_ENGINE=basic-pitch` 配合相应 Python 环境启动。

## 实体灯带

固件位于 `firmware/piano_lights/piano_lights.ino`，使用 Arduino ESP32、FastLED、ArduinoJson 7。固件针对可逐灯寻址的 WS2812B/GRB 灯带示例，默认 `LED_DATA_PIN=4`、`LED_COUNT=144`；这些只是软件示例参数，实际板卡引脚、灯带型号、数量和供电仍须按安装确定。

软件通过电脑串口向 ESP32 发消息，不依赖板卡的 USB Host 功能。固件串口需与电脑可通信：原生 USB 或板载 USB-UART 的选项取决于开发板。更换引脚、灯带型号或 RGB 顺序后需要重新编译。

协议为 115200 波特率、每行一个 JSON：

```json
{"type":"frame","brightness":0.15,"pixels":[[37,96,165,250],[41,192,132,252]]}
{"type":"clear"}
```

`frame` 中列出当前亮的灯珠，未列出的全部熄灭。灯珠从 0 编号；颜色为 RGB，后端和固件均将亮度上限限定为 35%。固件两秒没有有效帧就清灯，开机默认熄灯。物理琴键位置和黑白键排列不能简单按半音等间距换算，设置中提供逐键校准。

目前没有连接实体 ESP32/灯带，实物接线、刷写、实际颜色及琴键位置尚未验证。编译与软件测试状态见 [VALIDATION.md](VALIDATION.md)。

## 开源来源

- [Transkun](https://github.com/Yujia-Yan/Transkun)：MIT，默认钢琴专用音频到音符模型，保留作者源代码、配置、许可证和固定版本信息；安装时下载并校验模型权重。
- [Spotify Basic Pitch](https://github.com/spotify/basic-pitch)：Apache-2.0，可选快速音频到音符模型。使用 0.4.0 官方发布及其 ONNX 模型，校验值见转谱元数据和安装锁文件。
- [PianoPlayer](https://github.com/marcomusy/pianoplayer)：MIT，运动成本指法优化器。项目中仅保留必要的上游模块，并补充双手分配、和弦指法约束和自动简化适配。
- [Mido](https://github.com/mido/mido)：MIT，MIDI 读写。
- [pySerial](https://github.com/pyserial/pyserial)：BSD-3-Clause，串口通信。
- [ncmdump-local](https://github.com/Calvin-Vollerei/ncmdump-local)：MIT，本地 NCM 容器读取；采用核心模块，保留原始文件。
- [imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg)：提供本地 FFmpeg 可执行文件，负责将内层 FLAC 等格式真实编码为 MP3。
- [FastLED](https://github.com/FastLED/FastLED)、[ArduinoJson](https://github.com/bblanchon/ArduinoJson)：MIT，固件依赖。

固定版本、修改记录和许可位置见 [THIRD_PARTY.md](THIRD_PARTY.md)。为避免上游安装元数据自动下载 TensorFlow，安装脚本先安装完整的 ONNX 运行依赖，再使用 `--no-deps` 安装带哈希的 Basic Pitch。该 ONNX 路线已实际运行；直接 `pip check` 可能仍报告上游 metadata 中未装的 TensorFlow，这不代表这里调用了 TensorFlow。

## 验证与开发

```bash
.venv/bin/python -m unittest discover -s tests -v
```

`examples/automatic-transcription-test.mp3` 是可自由使用的合成钢琴音色测试片段（原创、CC0-1.0），含五个独音和一个三音和弦。它用于验证自动流程，不用于证明真实歌曲准确率。完整边界见 [VALIDATION.md](VALIDATION.md)。
