"""One timed note representation for notation, fingering and physical lights."""
from __future__ import annotations

import io
import heapq
import math
from bisect import bisect_right
from collections import defaultdict

PALETTE = {
    "L1": "#FF2020", "L2": "#FF8000", "L3": "#FFFF00",
    "L4": "#80FF00", "L5": "#00FF00",
    "R1": "#00FFFF", "R2": "#0040FF", "R3": "#8000FF",
    "R4": "#FF00FF", "R5": "#FFFFFF",
}
KEY_NAMES = ["C", "D♭", "D", "E♭", "E", "F", "G♭", "G", "A♭", "A", "B♭", "B"]
DEGREES = ["1", "#1", "2", "#2", "3", "4", "#4", "5", "#5", "6", "#6", "7"]


def validate_notes(notes):
    if not isinstance(notes, list) or not notes or len(notes) > 20000:
        raise ValueError("音符数量应为 1–20000。")
    result = []
    for i, original in enumerate(notes):
        try:
            pitch = int(original["pitch"])
            start, end = float(original["start"]), float(original["end"])
            velocity = int(original.get("velocity", 80))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"第 {i + 1} 个音符的数据无效。") from exc
        if not all(map(math.isfinite, (start, end))) or not 0 <= start < end <= 900:
            raise ValueError("音符时间必须在 0–900 秒内，结束晚于开始。")
        if not 21 <= pitch <= 108 or not 1 <= velocity <= 127:
            raise ValueError("音符应在钢琴 A0–C8 范围内，力度为 1–127。")
        note = dict(original)
        note.update(id=str(original.get("id", i)), pitch=pitch, start=start,
                    end=end, velocity=velocity)
        result.append(note)
    if len({n["id"] for n in result}) != len(result):
        raise ValueError("音符 id 不可重复。")
    return sorted(result, key=lambda n: (n["start"], n["pitch"], n["end"]))


def estimate_tonic(notes):
    # Major profile also yields an unambiguous numbered-score reference for minor music.
    # It is a notation reference, not a claim to have identified the original key.
    profile = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
    chroma = [0.] * 12
    for n in notes:
        chroma[n["pitch"] % 12] += min(4., n["end"] - n["start"]) * n["velocity"]
    return max(range(12), key=lambda root: sum(chroma[(root + i) % 12] * profile[i] for i in range(12)))


def numbered_pitch(pitch, tonic):
    relative = pitch - (60 + tonic)
    return {"degree": DEGREES[relative % 12], "octave": relative // 12}


def group_onsets(notes, tolerance=0.025):
    if notes and all("onset_group" in n for n in notes):
        by_group = {}
        for note in notes:
            group = by_group.setdefault(note["onset_group"], {"time": note["start"], "note_ids": []})
            group["time"] = min(group["time"], note["start"])
            group["note_ids"].append(note["id"])
        return sorted(by_group.values(), key=lambda group: group["time"])
    groups = []
    for note in notes:
        if not groups or note["start"] - groups[-1]["time"] > tolerance:
            groups.append({"time": note["start"], "note_ids": []})
        groups[-1]["note_ids"].append(note["id"])
    return groups


def _tempo_points(raw):
    """Validate seconds/quarter-note anchors before using imported metadata."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise ValueError("MIDI 变速映射应为非空列表。")
    result = []
    for point in raw:
        try:
            seconds, beat, tempo = (float(point[key]) for key in ("time", "beat", "tempo"))
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("MIDI 变速映射数据无效。") from exc
        if not all(map(math.isfinite, (seconds, beat, tempo))) or seconds < 0 or beat < 0 or not 0 < tempo <= 16777215:
            raise ValueError("MIDI 变速映射包含无效时间、拍数或速度。")
        if not result:
            if seconds != 0 or beat != 0:
                raise ValueError("MIDI 变速映射应从零秒、零拍开始。")
        else:
            previous_time, previous_beat, previous_tempo = result[-1]
            expected = previous_beat + (seconds - previous_time) * 1000000 / previous_tempo
            if seconds <= previous_time or not math.isclose(beat, expected, rel_tol=1e-8, abs_tol=1e-6):
                raise ValueError("MIDI 变速映射的时间或拍数不连续。")
        result.append((seconds, beat, tempo))
    return result


def _beat_at(seconds, points, times):
    """Integrate the active MIDI tempo segment at an arbitrary release time."""
    anchor_time, anchor_beat, tempo = points[bisect_right(times, seconds) - 1]
    return anchor_beat + (seconds - anchor_time) * 1000000 / tempo


def build_project(notes, title="新练习", bpm=100, tonic=None, hand_size="M", source=None,
                  transcription=None):
    from .fingering import annotate
    notes = validate_notes(notes)
    bpm = float(bpm)
    if not math.isfinite(bpm) or not 20 <= bpm <= 300:
        raise ValueError("节拍速度应在 20–300 BPM。")
    if tonic is None or int(tonic) == -1:
        tonic = estimate_tonic(notes)
    tonic = int(tonic)
    if not 0 <= tonic <= 11:
        raise ValueError("调号应为 0–11。")
    if hand_size not in ("XXS", "XS", "S", "M", "L", "XL", "XXL"):
        raise ValueError("手型尺寸无效。")
    source_notes = [dict(n) for n in notes]
    source_by_id = {n["id"]: n for n in source_notes}
    points = _tempo_points((transcription or {}).get("tempo_map"))
    tempo_times = [point[0] for point in points]
    annotated, fingering, warnings = annotate(notes, hand_size=hand_size)
    estimated_trimmed_beats = False
    for n in annotated:
        n["color"] = PALETTE[f'{n["hand"]}{n["finger"]}']
        n["jianpu"] = numbered_pitch(n["pitch"], tonic)
        original = source_by_id[n["id"]]
        if points:
            start_beat = _beat_at(n["start"], points, tempo_times)
            end_beat = _beat_at(n["end"], points, tempo_times)
            n["beat_start"] = round(start_beat, 4)
            n["beat_duration"] = round(end_beat - start_beat, 4)
        elif "source_beat_duration" in n:
            n["beat_start"] = round(n.get("source_beat_start", n["start"] * bpm / 60), 4)
            ratio = (n["end"] - n["start"]) / (original["end"] - original["start"])
            n["beat_duration"] = round(n["source_beat_duration"] * ratio, 4)
            if not math.isclose(ratio, 1.0, abs_tol=1e-9):
                # Legacy JSON may have source beats but no tempo anchors. Its
                # exact shortened beat duration cannot be recovered from a ratio.
                n["beat_duration_estimated"] = True
                estimated_trimmed_beats = True
        else:
            n["beat_start"] = round(n["start"] * bpm / 60, 4)
            n["beat_duration"] = round((n["end"] - n["start"]) * bpm / 60, 4)
        # Calibration is installation specific; the UI supplies actual mappings.
        n["leds"] = []
    if estimated_trimmed_beats:
        warnings.append("旧项目未保存 MIDI 变速映射，已缩短音符的拍长为平均速度估算；灯光仍按实际秒数运行。")
    return {
        "schema_version": 1, "title": str(title)[:160], "bpm": bpm,
        "tonic": tonic, "key_label": f"1={KEY_NAMES[tonic]}",
        "duration": max(n["end"] for n in annotated), "notes": annotated,
        "source_notes": source_notes,
        "groups": group_onsets(annotated), "palette": dict(PALETTE),
        "warnings": warnings, "fingering": fingering, "hand_size": hand_size,
        "source": source or {"kind": "notes"},
        "transcription": transcription or {"engine": "MIDI / 原始音符"},
        "notation": {"kind": "timed-jianpu", "meter": "4/4", "meter_assumed": True,
                     "timing": "original-seconds", "key": "auto-numbered-reference",
                     "beat_timing": "midi-tempo-map" if points else "reference-or-source-beats",
                     "trimmed_beats_estimated": estimated_trimmed_beats},
    }


def read_midi(data):
    import mido
    midi = mido.MidiFile(file=io.BytesIO(data))
    if midi.type == 2:
        raise ValueError("暂不支持各轨时间独立的 MIDI type 2。")
    tempo, seconds, beat = 500000, 0., 0.
    tempo_map = [{"time": 0.0, "beat": 0.0, "tempo": tempo}]
    time_signature_map = []
    active = defaultdict(list)
    notes, excluded = [], 0
    track_names = [next((msg.name for msg in track if msg.type == "track_name"), "")
                   for track in midi.tracks]
    hand_labels = {"rh": "R", "right hand": "R", "piano right hand": "R",
                   "右手": "R", "lh": "L", "left hand": "L",
                   "piano left hand": "L", "左手": "L"}

    def timed_track(track, index):
        tick = 0
        for order, message in enumerate(track):
            tick += message.time
            yield tick, index, order, message

    # Keep track provenance while merging, with the same stable tick/track
    # ordering as mido.merge_tracks. Track numbers/channels alone are not hands.
    previous_tick = 0
    streams = [timed_track(track, i) for i, track in enumerate(midi.tracks)]
    for tick, track_index, _, msg in heapq.merge(*streams):
        delta = tick - previous_tick
        previous_tick = tick
        seconds += mido.tick2second(delta, midi.ticks_per_beat, tempo)
        beat += delta / midi.ticks_per_beat
        if seconds > 900:
            raise ValueError("MIDI 超过 15 分钟，请导入较短片段。")
        if msg.type == "set_tempo":
            if not 0 < msg.tempo <= 16777215:
                raise ValueError("MIDI 速度事件应为正数。")
            tempo = msg.tempo
            point = {"time": seconds, "beat": beat, "tempo": tempo}
            # Several tracks can set tempo at the same tick. The merged event
            # order decides the effective tempo; no zero-length segment remains.
            if seconds == tempo_map[-1]["time"]:
                tempo_map[-1] = point
            else:
                tempo_map.append(point)
        if msg.type == "time_signature":
            point = {"time": seconds, "beat": beat, "numerator": msg.numerator,
                     "denominator": msg.denominator}
            if time_signature_map and time_signature_map[-1]["time"] == seconds:
                time_signature_map[-1] = point
            else:
                time_signature_map.append(point)
        if getattr(msg, "channel", None) == 9:
            continue
        if msg.type == "note_on" and msg.velocity > 0:
            active[(msg.channel, msg.note)].append((seconds, msg.velocity, beat, track_index))
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            key = (msg.channel, msg.note)
            if active[key]:
                # Prefer the matching track, but MIDI channels can also carry
                # a note-off in another track. Retain the note-on provenance.
                match = next((i for i, event in enumerate(active[key])
                              if event[3] == track_index), 0)
                start, velocity, start_beat, source_track = active[key].pop(match)
                if seconds <= start:
                    continue
                if not 21 <= msg.note <= 108:
                    excluded += 1
                    continue
                note = {"id": str(len(notes)), "pitch": msg.note, "start": start,
                        "end": seconds, "velocity": velocity,
                        "source_beat_start": start_beat,
                        "source_beat_duration": beat - start_beat,
                        "source_track": source_track, "source_channel": msg.channel,
                        "source_track_name": track_names[source_track]}
                hand = hand_labels.get(" ".join(track_names[source_track].lower().split()))
                if hand:
                    note["source_hand"] = hand
                    note["source_hand_origin"] = "explicit-track-label"
                notes.append(note)
                if len(notes) > 20000:
                    raise ValueError("MIDI 音符过多，请导入较短片段。")
    dangling = sum(len(v) for v in active.values())
    if dangling:
        raise ValueError("MIDI 存在缺失结束事件的音符，请使用完整的 MIDI 文件。")
    if not notes:
        raise ValueError("文件中没有钢琴音域内的音符。")
    initial_bpm = mido.tempo2bpm(tempo_map[0]["tempo"])
    return notes, min(300, max(20, initial_bpm)), {
        "excluded_nonpiano": excluded, "tempo_map": tempo_map,
        "time_signature_map": time_signature_map,
        "source_initial_bpm": initial_bpm,
        "hand_labelled_notes": sum("source_hand" in n for n in notes),
    }


def write_midi(project):
    import mido
    notes = validate_notes(project["notes"])
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.append(mido.MetaMessage("set_tempo", tempo=500000, time=0))
    events = []
    for n in notes:
        channel = 0 if n.get("hand", "R") == "R" else 1
        events.extend([(round(n["start"] * 960), 1, channel, n["pitch"], n["velocity"]),
                       (round(n["end"] * 960), 0, channel, n["pitch"], 0)])
    last = 0
    for tick, on, channel, pitch, velocity in sorted(events):
        track.append(mido.Message("note_on" if on else "note_off", channel=channel,
                                  note=pitch, velocity=velocity, time=tick-last))
        last = tick
    out = io.BytesIO()
    midi.save(file=out)
    return out.getvalue()


def demo_project():
    notes = []
    melody = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60]
    for i, pitch in enumerate(melody):
        notes.append({"id": f"r{i}", "pitch": pitch, "start": i * .6,
                      "end": i * .6 + .48, "velocity": 90})
    for i, pitches in enumerate([[48, 52, 55], [45, 48, 52], [43, 47, 50], [48, 52, 55]]):
        for j, pitch in enumerate(pitches):
            notes.append({"id": f"l{i}-{j}", "pitch": pitch, "start": i * 2.4,
                          "end": i * 2.4 + 1.9, "velocity": 65})
    return build_project(notes, title="双手音阶练习 · 原创示例", bpm=100, tonic=0,
                         source={"kind": "demo", "license": "CC0-1.0"})
