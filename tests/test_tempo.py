"""MIDI tempo integration must survive automatic shortening of held notes."""
import io
import unittest

import mido

from piano.music import build_project, read_midi


def midi_bytes(messages):
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    track.extend(messages)
    data = io.BytesIO()
    midi.save(file=data)
    return data.getvalue()


def leap_midi():
    return midi_bytes([
        mido.MetaMessage("set_tempo", tempo=500000),
        mido.Message("note_on", note=36, velocity=90),
        mido.Message("note_on", note=72, velocity=90),
        mido.MetaMessage("set_tempo", tempo=1000000, time=480),
        mido.Message("note_on", note=21, velocity=90),
        mido.Message("note_on", note=108, velocity=90),
        mido.Message("note_off", note=36, time=480),
        mido.Message("note_off", note=72),
        mido.Message("note_off", note=21),
        mido.Message("note_off", note=108),
    ])


class TempoTests(unittest.TestCase):
    def test_shortened_notes_use_actual_tempo_segments(self):
        notes, bpm, metadata = read_midi(leap_midi())
        self.assertEqual(metadata["tempo_map"], [
            {"time": 0.0, "beat": 0.0, "tempo": 500000},
            {"time": .5, "beat": 1.0, "tempo": 1000000},
        ])
        project = build_project(notes, bpm=bpm, tonic=0,
                                transcription={"engine": "Mido MIDI", **metadata})
        by_pitch = {note["pitch"]: note for note in project["notes"]}
        for pitch in (36, 72):
            self.assertEqual(by_pitch[pitch]["end"], .5)
            self.assertEqual(by_pitch[pitch]["beat_duration"], 1.0)
        for pitch in (21, 108):
            self.assertEqual(by_pitch[pitch]["beat_start"], 1.0)
            self.assertEqual(by_pitch[pitch]["beat_duration"], 1.0)
        self.assertEqual(project["notation"]["beat_timing"], "midi-tempo-map")
        rebuilt = build_project(project["source_notes"], bpm=80, tonic=0,
                                transcription=project["transcription"])
        self.assertEqual([(n["beat_start"], n["beat_duration"]) for n in rebuilt["notes"]],
                         [(n["beat_start"], n["beat_duration"]) for n in project["notes"]])

    def test_multiple_changes_integrate_inside_segments(self):
        notes = [{"id": "a", "pitch": 60, "start": .75, "end": 2.25, "velocity": 90}]
        metadata = {"tempo_map": [
            {"time": 0, "beat": 0, "tempo": 500000},
            {"time": .5, "beat": 1, "tempo": 1000000},
            {"time": 1.5, "beat": 2, "tempo": 250000},
        ]}
        project = build_project(notes, bpm=120, tonic=0, transcription=metadata)
        self.assertEqual(project["notes"][0]["beat_start"], 1.25)
        self.assertEqual(project["notes"][0]["beat_duration"], 3.75)

    def test_first_late_tempo_event_does_not_replace_default_initial_bpm(self):
        data = midi_bytes([
            mido.Message("note_on", note=60, velocity=90),
            mido.MetaMessage("set_tempo", tempo=1000000, time=480),
            mido.Message("note_off", note=60, time=480),
        ])
        notes, bpm, metadata = read_midi(data)
        self.assertEqual(bpm, 120)
        self.assertEqual(metadata["source_initial_bpm"], 120)
        self.assertEqual(notes[0]["end"], 1.5)
        self.assertEqual(notes[0]["source_beat_duration"], 2)

    def test_last_tempo_at_zero_is_effective_initial_tempo(self):
        data = midi_bytes([
            mido.MetaMessage("set_tempo", tempo=600000),
            mido.MetaMessage("set_tempo", tempo=750000),
            mido.Message("note_on", note=60, velocity=90),
            mido.Message("note_off", note=60, time=480),
        ])
        notes, bpm, metadata = read_midi(data)
        self.assertEqual(bpm, 80)
        self.assertEqual(notes[0]["end"], .75)
        self.assertEqual(metadata["tempo_map"], [{"time": 0, "beat": 0, "tempo": 750000}])

    def test_legacy_trimmed_beats_are_marked_estimated(self):
        notes, bpm, metadata = read_midi(leap_midi())
        metadata.pop("tempo_map")
        project = build_project(notes, bpm=bpm, tonic=0, transcription=metadata)
        self.assertTrue(project["notation"]["trimmed_beats_estimated"])
        self.assertTrue(all(n.get("beat_duration_estimated") for n in project["notes"] if n["pitch"] in (36, 72)))
        self.assertTrue(any("变速映射" in warning for warning in project["warnings"]))

    def test_invalid_tempo_metadata_is_rejected(self):
        notes = [{"pitch": 60, "start": 0, "end": 1}]
        for tempo_map in ([], [{"time": 0, "beat": 0, "tempo": 0}],
                          [{"time": 0, "beat": 0, "tempo": 500000},
                           {"time": .5, "beat": 2, "tempo": 1000000}]):
            with self.subTest(tempo_map=tempo_map), self.assertRaises(ValueError):
                build_project(notes, transcription={"tempo_map": tempo_map})


if __name__ == "__main__":
    unittest.main()
