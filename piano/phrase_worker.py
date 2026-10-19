"""Run actual loop-miner code; leave playback notes and fingering untouched."""
from __future__ import annotations

from bisect import bisect_right, bisect_left
from collections import defaultdict
import io
import json
import math
import os
from pathlib import Path
import sys

from .phrases import REVISION, SSMS_REVISION


def make_midi(project):
    import mido
    points = project.get("tempo_map") or [{"time": 0, "beat": 0,
                                            "tempo": round(60000000 / project["bpm"])}]
    points = sorted(points, key=lambda point: point["time"])
    times = [p["time"] for p in points]

    def beat_at(seconds):
        p = points[max(0, bisect_right(times, seconds) - 1)]
        return p["beat"] + (seconds - p["time"]) * 1000000 / p["tempo"]

    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    events = [(round(p["beat"] * 480), 0, mido.MetaMessage("set_tempo", tempo=p["tempo"])) for p in points]
    signatures = project.get("time_signature_map") or [{"beat": 0, "numerator": 4, "denominator": 4}]
    for p in signatures:
        events.append((round(p["beat"] * 480), 0, mido.MetaMessage(
            "time_signature", numerator=p["numerator"], denominator=p["denominator"])))
    for note in project["notes"]:
        start = round(beat_at(note["start"]) * 480)
        end = max(start + 1, round(beat_at(note["end"]) * 480))
        events.append((start, 2, mido.Message("note_on", note=note["pitch"], velocity=note["velocity"])))
        events.append((end, 1, mido.Message("note_off", note=note["pitch"], velocity=0)))
    previous = 0
    for tick, _, message in sorted(events, key=lambda event: event[:2]):
        track.append(message.copy(time=tick - previous))
        previous = tick
    buffer = io.BytesIO()
    midi.save(file=buffer)
    return buffer.getvalue(), beat_at


def sections_from_candidates(project, candidates, beat_at, bar_beats):
    """Retain the upstream boundaries; merge only complete matching passages."""
    groups = project["groups"]
    times = [g["time"] for g in groups]
    note_by_id = {str(n["id"]): n for n in project["notes"]}
    # source_notes can include removed overlapping notes. Only current score IDs
    # participate in practice, while musical identity uses their original pitch.
    signatures = []
    for group in groups:
        pitches = sorted({(note_by_id[str(i)]["pitch"], round((beat_at(note_by_id[str(i)]["end"]) -
                          beat_at(note_by_id[str(i)]["start"])) * 24))
                          for i in group["note_ids"] if str(i) in note_by_id})
        signatures.append((tuple(pitches), beat_at(group["time"])))

    def occurrence(start, end):
        left = bisect_left(times, start - 0.002)
        right = bisect_left(times, end - 0.002)
        if left >= right:
            return None
        # Align to the application's actual onset groups, including notes close
        # to a quantized boundary. The next group remains outside this loop.
        return {"startGroup": left, "endGroup": right, "start": times[left],
                "end": times[right] if right < len(times) else project["duration"]}

    buckets = defaultdict(list)
    unique = set()
    for start, end in candidates:
        value = occurrence(start, end)
        if not value or (value["startGroup"], value["endGroup"]) in unique:
            continue
        left, right = value["startGroup"], value["endGroup"]
        unique.add((left, right))
        origin = signatures[left][1]
        # Full pitch + rhythmic content validates repeats beyond upstream's
        # bookend criterion. Color, finger and hand assignments are irrelevant.
        key = tuple((pitches, round((beat - origin) * 24)) for pitches, beat in signatures[left:right])
        buckets[key].append(value)

    repeated = []
    for values in buckets.values():
        values.sort(key=lambda item: item["start"])
        separated = []
        for value in values:
            if not separated or value["startGroup"] >= separated[-1]["endGroup"]:
                separated.append(value)
        if len(separated) > 1:
            repeated.append(separated)
    repeated.sort(key=lambda values: -(values[0]["endGroup"] - values[0]["startGroup"]) * (len(values) - 1))
    covered = [False] * len(groups)
    sections = []
    for values in repeated:
        available = [v for v in values if not any(covered[v["startGroup"]:v["endGroup"]])]
        if len(available) < 2:
            continue
        sections.append({"kind": "repeat", "occurrences": available})
        for value in available:
            covered[value["startGroup"]:value["endGroup"]] = [True] * (value["endGroup"] - value["startGroup"])
    # Unmatched material is still covered, in short meter-aligned practice units.
    start = 0
    while start < len(groups):
        if covered[start]:
            start += 1
            continue
        end = start + 1
        meters = project.get("time_signature_map") or [{"beat": 0, "numerator": 4, "denominator": 4}]
        meter = next((m for m in reversed(meters) if m["beat"] <= signatures[start][1]), meters[0])
        length = meter["numerator"] * 4 / meter["denominator"]
        bar_end = meter["beat"] + (math.floor((signatures[start][1] - meter["beat"]) / length) + 2) * length
        next_meter = next((m["beat"] for m in meters if m["beat"] > signatures[start][1]), float("inf"))
        bar_end = min(bar_end, next_meter)
        while end < len(groups) and not covered[end] and signatures[end][1] < bar_end and end - start < 40:
            end += 1
        sections.append({"kind": "single", "occurrences": [{"startGroup": start, "endGroup": end,
                         "start": times[start], "end": times[end] if end < len(times) else project["duration"]}]})
        start = end
    sections.sort(key=lambda section: section["occurrences"][0]["start"])
    for index, section in enumerate(sections):
        section["id"] = index
        section["groupCount"] = section["occurrences"][0]["endGroup"] - section["occurrences"][0]["startGroup"]
    return sections


def run(project, runtime):
    os.environ.setdefault("MPLBACKEND", "Agg")
    upstream = runtime / "tools" / "loop-miner-src"
    if not (upstream / "installed.json").is_file():
        raise ValueError("分段引擎尚未安装，请运行 安装自动分段.ps1。")
    sys.path.insert(0, str(upstream))
    import numpy as np
    import pretty_midi
    import symusic
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    from loop_miner.structure import StructureAnalyser
    from loop_miner.loop_detection import extract_loops
    from loop_miner import core, loop_detection

    data, beat_at = make_midi(project)
    pm = pretty_midi.PrettyMIDI(io.BytesIO(data))
    signature = pm.time_signature_changes[0]
    meter_label = " → ".join(dict.fromkeys(f"{s.numerator}/{s.denominator}" for s in pm.time_signature_changes))
    bar_beats = signature.numerator * 4 / signature.denominator
    native_meter = all(s.numerator == 4 and s.denominator == 4 for s in pm.time_signature_changes)
    warnings = []
    if native_meter:
        pm = StructureAnalyser(device="cpu").analyse(pm)
        method = "model"
    else:
        # Upstream's learned hierarchy assumes binary 4/4 meter. Preserve the
        # source meter and use its bar boundaries with the SAME loop detector.
        layer = pretty_midi.Instrument(0, is_drum=True, name="Layers4")
        for index, meter in enumerate(pm.time_signature_changes):
            first = int(pm.time_to_tick(meter.time))
            end = int(pm.time_to_tick(pm.time_signature_changes[index + 1].time)) if index + 1 < len(pm.time_signature_changes) else int(pm.time_to_tick(project["duration"])) + 1
            ticks_per_bar = round(meter.numerator * 4 / meter.denominator * pm.resolution)
            for tick in range(first, end, ticks_per_bar):
                start = pm.tick_to_time(tick)
                layer.notes.append(pretty_midi.Note(127, 36, start, start + 0.02))
        pm.instruments.append(layer)
        method = "source-meter"
        warnings.append(f"原曲为 {meter_label} 拍，使用原谱小节边界和上游循环检测；未套用仅适合 4/4 的模型边界。")
    if not project.get("time_signature_map"):
        warnings.append("原转谱未提供拍号，暂按 4/4 估计，分段边界可手动微调。")
    structured = io.BytesIO()
    pm.write(structured)
    sm = symusic.Score.from_midi(structured.getvalue())

    # Compatibility correction: upstream sums pitch classes over the wrong
    # axis (11 octave bins). Keep exact pitch information for a teaching score.
    upstream_features = core.get_piano_roll_features

    def teaching_features(score, tpq):
        _, boundaries = upstream_features(score, tpq)
        musical = score.copy()
        musical.tracks = [t for t in musical.tracks if not t.name.startswith("Layers") and not t.is_drum]
        roll = musical.resample(tpq=tpq, min_dur=1).pianoroll(modes=["frame"], pitch_range=[0, 128])[0]
        pitches = (roll.sum(axis=0) > 0).astype(np.int8)
        # Layer tracks may extend the complete score beyond the musical notes.
        pitches = np.pad(pitches, ((0, 0), (0, max(0, boundaries.shape[1] - pitches.shape[1]))))
        return pitches[:, :boundaries.shape[1]], boundaries

    loop_detection.get_piano_roll_features = teaching_features
    # The upstream broadcast builds pitch × time × time temporary arrays.
    # scipy computes the identical Manhattan distances with bounded memory.
    from scipy.spatial.distance import cdist
    loop_detection.distance_matrix = lambda roll: cdist(roll.T, roll.T, metric="cityblock")
    # Bound resolution for the upstream O(time²) matrix on long/fast pieces.
    beats = beat_at(project["duration"])
    resolution = 4 if beats * 4 < 4500 else (2 if beats * 2 < 4500 else 1)
    accepted_lengths = tuple({bars * meter.numerator / meter.denominator for bars in (1, 2, 4, 8)
                              for meter in pm.time_signature_changes})
    records = extract_loops(sm, resolution, 4, 1, accepted_lengths, 0.5)
    candidates = []
    for record in records:
        if record["start_tick"] < 0 or record["end_tick"] <= record["start_tick"]:
            continue
        start = pm.tick_to_time(record["start_tick"])
        end = min(project["duration"], pm.tick_to_time(record["end_tick"]))
        if end > start:
            candidates.append((start, end))
    sections = sections_from_candidates(project, candidates, beat_at, bar_beats)
    return {"sections": sections, "repeated": sum(s["kind"] == "repeat" for s in sections),
            "occurrences": sum(len(s["occurrences"]) for s in sections if s["kind"] == "repeat"),
            "groupCount": len(project["groups"]), "engine": "loop-miner", "revision": REVISION,
            "structure_revision": SSMS_REVISION, "boundary_method": method,
            "meter": meter_label,
            "candidate_count": len(candidates), "warnings": warnings}


if __name__ == "__main__":
    try:
        source, target, runtime = map(Path, sys.argv[1:4])
        result = run(json.loads(source.read_text(encoding="utf-8")), runtime)
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
    except Exception as error:
        import traceback
        traceback.print_exc()
        print(json.dumps({"error": f"自动分段未完成：{error}"}, ensure_ascii=True), flush=True)
        sys.exit(1)
