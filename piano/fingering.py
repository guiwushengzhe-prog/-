"""Automatic hand routing and fingering for a two-hand practice arrangement.

Uses Marco Musy's MIT PianoPlayer optimizer, then enumerates physically ordered
chord assignments to guarantee unique fingers and respect notes still held.
No model download, paid API, or manual editing is needed. This is an automatic
practice fingering, not a claim about a composer's or performer's fingering.

Vendor layout: this module next to vendor/pianoplayer/{hand,models,__init__}.py.
Source: https://github.com/marcomusy/pianoplayer
Pinned revision: 6fb0e2114d7b21f75c0be5208172e1243a57323e (3.0.2).
"""
from __future__ import annotations

import math
from itertools import combinations
from functools import lru_cache
from statistics import mean

try:
    from .vendor.pianoplayer.hand import Hand
    from .vendor.pianoplayer.models import INote
except ImportError:
    # Also allow importing this module directly when running standalone checks.
    from vendor.pianoplayer.hand import Hand
    from vendor.pianoplayer.models import INote

UPSTREAM_VERSION = "3.0.2"
UPSTREAM_REVISION = "6fb0e2114d7b21f75c0be5208172e1243a57323e"
# Real white-key centers and intervening black-key centers, in white-key widths.
_KEY_X = (0.5, 1.0, 1.5, 2.0, 2.5, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5)
_CHORD_TOLERANCE = 0.025
_MAX_BEAM = 12


def key_x(pitch: int) -> float:
    return (pitch // 12 * 7.0 + _KEY_X[pitch % 12]) * (16.5 / 7.0)


def _validate(notes):
    source = []
    seen = set()
    for i, raw in enumerate(notes):
        n = dict(raw)
        n.setdefault("id", i)
        if not isinstance(n["id"], (int, str)) or isinstance(n["id"], bool):
            raise ValueError("每个音符的 id 必须是整数或字符串")
        if n["id"] in seen:
            raise ValueError("音符 id 不能重复")
        seen.add(n["id"])
        pitch = n.get("pitch")
        if isinstance(pitch, bool) or not isinstance(pitch, int) or not 21 <= pitch <= 108:
            raise ValueError(f"音符 {n['id']} 超出 88 键钢琴音域（MIDI 21–108）")
        for field in ("start", "end"):
            value = n.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"音符 {n['id']} 的 {field} 必须是有限秒数")
            n[field] = float(value)
        if n["start"] < 0 or n["end"] <= n["start"]:
            raise ValueError(f"音符 {n['id']} 的时间范围无效")
        velocity = n.get("velocity", 80)
        if isinstance(velocity, bool) or not isinstance(velocity, (int, float)) or not math.isfinite(velocity):
            raise ValueError(f"音符 {n['id']} 的力度无效")
        n["velocity"] = max(1, min(127, round(velocity)))
        if n.get("source_hand") not in (None, "L", "R"):
            raise ValueError("源曲谱手别必须是 L 或 R")
        source.append(n)
    return sorted(source, key=lambda n: (n["start"], n["pitch"], str(n["id"])))


def _groups(notes):
    groups = []
    for n in notes:
        if not groups or n["start"] - groups[-1][0]["start"] > _CHORD_TOLERANCE:
            groups.append([n])
        else:
            groups[-1].append(n)
    return [sorted(g, key=lambda n: (n["pitch"], n["start"])) for g in groups]


_PAIR_SPANS = {(3, 4): 5, (4, 5): 5, (2, 3): 6, (2, 4): 7,
               (3, 5): 8, (2, 5): 11, (1, 2): 12, (1, 3): 14, (1, 4): 16}


def _pairs_playable(pitches, fingers, max_span):
    if len(pitches) > 5 or len(set(fingers)) != len(fingers):
        return False
    if pitches and key_x(pitches[-1]) - key_x(pitches[0]) > max_span + 1e-9:
        return False
    hf = max_span / 21.0
    for i, p in enumerate(pitches):
        for j in range(i + 1, len(pitches)):
            threshold = _PAIR_SPANS.get(tuple(sorted((fingers[i], fingers[j]))))
            if threshold is not None and key_x(pitches[j]) - key_x(p) > threshold * hf / 0.8 + 1e-9:
                return False
    return True


@lru_cache(maxsize=2048)
def _ordered_assignments(pitches, max_span, side):
    if len(pitches) > 5:
        return ()
    possible = []
    for fs in combinations(range(1, 6), len(pitches)):
        fingers = fs if side == "R" else fs[::-1]
        if _pairs_playable(pitches, fingers, max_span):
            possible.append(fingers)
    return tuple(possible)


def _feasible(notes, max_span):
    pitches = tuple(n["pitch"] for n in notes)
    # A mirrored left hand has a different long-thumb edge than the right.
    return bool(_ordered_assignments(pitches, max_span, "L") or _ordered_assignments(pitches, max_span, "R"))


def _importance(n, group):
    # Preserve melody and bass before inner harmony in a dense arrangement.
    extreme = n["pitch"] in (group[0]["pitch"], group[-1]["pitch"])
    return 20.0 + 80.0 * extreme + n["velocity"] / 127 + min(2.0, n["end"] - n["start"])


def _best_subset(notes, group, max_span):
    if _feasible(notes, max_span):
        return notes
    best = []
    best_value = -1.0
    for lo in range(len(notes)):
        window = [n for n in notes[lo:] if key_x(n["pitch"]) - key_x(notes[lo]["pitch"]) <= max_span + 1e-9]
        keep = sorted(sorted(window, key=lambda n: _importance(n, group), reverse=True)[:5], key=lambda n: n["pitch"])
        while keep and not _feasible(keep, max_span):
            least = min(keep, key=lambda n: _importance(n, group))
            keep.remove(least)
        value = sum(_importance(n, group) for n in keep)
        if value > best_value:
            best, best_value = keep, value
    return best


def _routes(group, max_span):
    # Equal-pitch simultaneous duplicates are one physical key. Retain one event
    # and account for all omitted source events explicitly in the metadata.
    by_pitch = {}
    for n in group:
        if n["pitch"] not in by_pitch or (n["velocity"], n["end"]) > (by_pitch[n["pitch"]]["velocity"], by_pitch[n["pitch"]]["end"]):
            by_pitch[n["pitch"]] = n
    unique = sorted(by_pitch.values(), key=lambda n: n["pitch"])
    fixed_left = [n for n in unique if n.get("source_hand") == "L"]
    fixed_right = [n for n in unique if n.get("source_hand") == "R"]
    unknown = [n for n in unique if n.get("source_hand") is None]

    def split_notes(split):
        return (sorted(fixed_left + unknown[:split], key=lambda n: n["pitch"]),
                sorted(fixed_right + unknown[split:], key=lambda n: n["pitch"]))

    full = []
    for split in range(len(unknown) + 1):
        left, right = split_notes(split)
        if _ordered_assignments(tuple(n["pitch"] for n in left), max_span, "L") and _ordered_assignments(tuple(n["pitch"] for n in right), max_span, "R"):
            full.append((left, right))
    if full:
        return full
    candidates = []
    for split in range(len(unknown) + 1):
        raw_left, raw_right = split_notes(split)
        left = _best_subset(raw_left, unique, max_span)
        right = _best_subset(raw_right, unique, max_span)
        for side, ns in (("L", left), ("R", right)):
            while ns and not _ordered_assignments(tuple(n["pitch"] for n in ns), max_span, side):
                ns.remove(min(ns, key=lambda n: _importance(n, unique)))
        candidates.append((left, right))
    return candidates


def _route_cost(left, right, group, last_centers, last_mono_hand):
    centers = list(last_centers)
    kept = {n["id"] for n in left + right}
    cost = sum(_importance(n, group) for n in group if n["id"] not in kept) * 1000.0
    for h, ns in enumerate((left, right)):
        if not ns:
            continue
        center = mean(n["pitch"] for n in ns)
        # Smooth hand travel, with only a weak register prior. This can route
        # either hand through middle C rather than using a fixed pitch cutoff.
        cost += abs(center - centers[h]) * 0.7
        cost += ((center - (48 if h == 0 else 72)) / 12.0) ** 2 * 0.4
        cost += 0.05 if h == 0 else 0.0
        centers[h] = center
    mono_hand = ("L" if left else "R") if len(left) + len(right) == 1 else None
    if mono_hand and last_mono_hand and mono_hand != last_mono_hand:
        cost += 7.0
    return cost, tuple(centers), mono_hand


def _route_hands(groups, max_span):
    # Beam-search complete onset groups, including continuity across groups.
    # Backpointers avoid quadratic copying of long songs.
    beam = [(0.0, (48.0, 72.0), None, None)]
    for group in groups:
        choices = _routes(group, max_span)
        next_states = []
        for score, centers, mono_hand, parent in beam:
            for left, right in choices:
                extra, new_centers, new_mono = _route_cost(left, right, group, centers, mono_hand)
                node = (parent, left, right, group)
                next_states.append((score + extra, new_centers, new_mono, node))
        next_states.sort(key=lambda state: state[0])
        beam = next_states[:_MAX_BEAM]
    if not beam:
        return [], []
    node = min(beam, key=lambda state: state[0])[3]
    routed = []
    omitted = []
    while node:
        node, left, right, group = node
        kept = {n["id"] for n in left + right}
        for n in group:
            if n["id"] not in kept:
                reason = "duplicate_simultaneous_pitch" if any(k["pitch"] == n["pitch"] for k in left + right) else "two_hand_capacity_or_span"
                omitted.append({**n, "reason": reason})
        routed.append((left, right))
    return list(reversed(routed)), list(reversed(omitted))


def _upstream_proposals(routed, side, hand_size):
    seq = []
    for gid, (left, right) in enumerate(routed):
        notes = left if side == "L" else right
        for k, n in enumerate(notes):
            seq.append(INote(
                pitch=n["pitch"], x=key_x(n["pitch"]), time=n["start"],
                duration=n["end"] - n["start"], noteID=len(seq),
                isBlack=n["pitch"] % 12 in (1, 3, 6, 8, 10),
                isChord=len(notes) > 1, chordID=gid, chordnr=k, NinChord=len(notes),
            ))
    hand = Hand(seq, side="left" if side == "L" else "right", size=hand_size)
    hand.verbose = False
    hand.autodepth = False
    hand.depth = 5  # bounded CPU; still real combinatorial motion optimization
    # Call the upstream optimizer at every event. Its CLI generate() reuses a
    # nine-note tail, which can yield zero fingers with a smaller fixed depth.
    # The API here keeps the actual optimizer but avoids that tail assumption.
    if side == "L":
        for n in seq:
            n.x = -n.x
    carry = 0
    for i, n in enumerate(seq):
        upcoming = seq[i:i + 7]
        # Chords have up to five fingers; a melodic phrase benefits from seeing
        # an octave ahead. Repeated single pitches need no large search tree.
        limit = 5 if any(n.isChord for n in upcoming) else 7
        if len({n.pitch for n in upcoming}) <= 1:
            limit = 3
        window = list(upcoming[:limit])
        count = len(window)
        hand.depth = max(3, min(limit, count))
        while len(window) < 9:
            last = window[-1]
            window.append(INote(pitch=last.pitch, x=last.x, time=last.time + 0.5,
                                duration=0.4, isBlack=last.isBlack))
        fings, cost = hand.optimize_seq(window, carry)
        n.fingering = fings[0]
        n.cost = cost
        carry = fings[1] if count > 1 else 0
        hand.set_fingers_positions(fings, window, 0)
    proposals = {}
    i = 0
    for left, right in routed:
        for n in left if side == "L" else right:
            proposals[n["id"]] = seq[i].fingering
            i += 1
    return proposals, hand


def _chord_assignments(notes, active, side, proposals, hand, last_center, last_note):
    ordered_active = sorted(active, key=lambda n: n["pitch"])
    # PianoPlayer already optimizes chords. Keep its complete proposal whenever
    # it passes the physical checks, including notes held from earlier onsets.
    # Enumerate replacements only when that proposal actually conflicts.
    proposed_fingers = tuple(proposals[n["id"]] for n in notes)
    proposed = [{**n, "finger": f, "hand": side}
                for n, f in zip(notes, proposed_fingers)]
    combined = sorted(ordered_active + proposed, key=lambda n: n["pitch"])
    combined_fingers = tuple(n["finger"] for n in combined)
    if (all(isinstance(f, int) and 1 <= f <= 5 for f in combined_fingers)
            and combined_fingers == tuple(sorted(combined_fingers, reverse=side == "L"))
            and _pairs_playable(tuple(n["pitch"] for n in combined), combined_fingers,
                                hand.max_span_cm)):
        center = mean(key_x(n["pitch"]) - (1 if side == "R" else -1) * hand.frest[n["finger"]]
                      for n in combined)
        return 0.0, proposed, center
    best = None
    for fingers in _ordered_assignments(tuple(n["pitch"] for n in notes), hand.max_span_cm, side):
        new = [{**n, "finger": f, "hand": side} for n, f in zip(notes, fingers)]
        all_notes = sorted(ordered_active + new, key=lambda n: n["pitch"])
        all_fs = [n["finger"] for n in all_notes]
        if len(set(all_fs)) != len(all_fs):
            continue
        if all_fs != sorted(all_fs, reverse=side == "L"):
            continue
        # Check every finger pair, including fingers holding earlier notes.
        if not _pairs_playable(tuple(n["pitch"] for n in all_notes), tuple(all_fs), hand.max_span_cm):
            continue
        centers = [key_x(n["pitch"]) - (1 if side == "R" else -1) * hand.frest[n["finger"]] for n in all_notes]
        center = mean(centers)
        cost = sum((v - center) ** 2 for v in centers)
        cost += sum(abs(f - proposals[n["id"]]) * 20.0 for n, f in zip(notes, fingers))
        cost += abs(center - last_center) * 1.0 if last_center is not None else 0.0
        cost += sum(1.0 for n, f in zip(notes, fingers) if f == 1 and n["pitch"] % 12 in (1, 3, 6, 8, 10))
        if last_note is not None and len(notes) == 1:
            a, b = last_note, new[0]
            sign = 1 if side == "R" else -1
            na = INote(pitch=a["pitch"], x=sign * key_x(a["pitch"]), duration=a["end"] - a["start"],
                       isBlack=a["pitch"] % 12 in (1, 3, 6, 8, 10))
            nb = INote(pitch=b["pitch"], x=sign * key_x(b["pitch"]),
                       isBlack=b["pitch"] % 12 in (1, 3, 6, 8, 10))
            if b["start"] - a["end"] < 0.3 and hand.skip(a["finger"], b["finger"], na, nb, hand.hf, hand.LR, 1):
                cost += 50.0
        if best is None or cost < best[0]:
            best = cost, new, center
    return best


def _verify_assignments(notes, max_span):
    """Reject conflicting output independently of the optimizer/repair search."""
    active = {"L": [], "R": []}
    for note in sorted(notes, key=lambda n: (n["start"], n["pitch"], str(n["id"]))):
        side, finger = note.get("hand"), note.get("finger")
        if side not in active or isinstance(finger, bool) or not isinstance(finger, int) or not 1 <= finger <= 5:
            raise ValueError("指法最终校验失败：手别或手指编号无效")
        if note["end"] <= note["start"]:
            raise ValueError("指法最终校验失败：音符时长无效")
        held = [n for n in active[side] if n["end"] > note["start"] + 1e-9]
        for previous in held:
            if previous["finger"] == finger:
                raise ValueError("指法最终校验失败：同一手指同时占用两个琴键")
            order = (note["pitch"] - previous["pitch"]) * (finger - previous["finger"])
            if order * (1 if side == "R" else -1) <= 0:
                raise ValueError("指法最终校验失败：同时按键的手指顺序冲突")
            if abs(key_x(note["pitch"]) - key_x(previous["pitch"])) > max_span + 1e-9:
                raise ValueError("指法最终校验失败：同时按键超过所选手型跨度")
        active[side] = held + [note]


def annotate(notes, hand_size="M"):
    """Return ``(practice_notes, metadata, warnings)`` without a manual step.

    Each output keeps the input fields and adds ``hand`` (R/L) and ``finger``
    (thumb=1 to little finger=5). Unplayable simultaneous density is automatically
    reduced and every omitted/shortened event remains in the metadata audit.
    Invalid inputs raise ValueError; they are never silently ignored.
    """
    if hand_size not in Hand._SIZE_FACTORS:
        raise ValueError("hand_size 必须是 XXS/XS/S/M/L/XL/XXL")
    source = _validate(notes)
    max_span = 21.0 * Hand.size_factor(hand_size)
    routed, omitted = _route_hands(_groups(source), max_span)
    proposals = {}
    hands = {}
    for side in ("L", "R"):
        prop, hand = _upstream_proposals(routed, side, hand_size)
        proposals.update(prop)
        hands[side] = hand
    result = []
    shortened = {}
    repaired = 0
    for side, index in (("L", 0), ("R", 1)):
        active = []
        center = None
        last_note = None
        for group_index, pair in enumerate(routed):
            group = pair[index]
            if not group:
                continue
            onset = min(n["start"] for n in group)
            pitches = {n["pitch"] for n in group}
            active = [n for n in active if n["end"] > onset + 1e-9]
            # A repeated key must be released before striking it again.
            for n in active[:]:
                if n["pitch"] in pitches:
                    shortened.setdefault(n["id"], {"id": n["id"], "source_end": n["end"], "practice_end": onset, "reason": "rearticulated_pitch"})
                    n["end"] = onset
                    active.remove(n)
            best = _chord_assignments(group, active, side, proposals, hands[side], center, last_note)
            if best is None and active:
                # Acoustic/pedal tails can imply >5 held fingers. Generate a
                # detached practice articulation automatically, preserving timing.
                for n in active:
                    shortened.setdefault(n["id"], {"id": n["id"], "source_end": n["end"], "practice_end": onset, "reason": "release_for_next_position"})
                    n["end"] = onset
                active = []
                best = _chord_assignments(group, active, side, proposals, hands[side], center, last_note)
            if best is None:
                # Never invent duplicate fingers for an impossible chord.
                raise ValueError("该和弦无法在所选手型的约束内自动编配；请使用更大手型或自动转为旋律练习")
            _, assigned, center = best
            repaired += sum(n["finger"] != proposals[n["id"]] for n in assigned)
            for note in assigned:
                note["onset_group"] = group_index
                note["hand_origin"] = "source-label" if note.get("source_hand") else "inferred"
            result.extend(assigned)
            active.extend(assigned)
            last_note = assigned[-1]
    result.sort(key=lambda n: (n["start"], n["pitch"], str(n["id"])))
    _verify_assignments(result, max_span)
    simplified_ids = {n["id"] for n in omitted} | set(shortened)
    warnings = []
    if omitted:
        warnings.append(f"已自动生成简化练习版：省略 {len(omitted)} 个重复或超过双手容量/跨度的音符，明细已保留。")
    if shortened:
        warnings.append(f"已自动调整 {len(shortened)} 个音符的松键时刻，避免延音重叠导致同一手指同时按不同键；原始时长已保留。")
    metadata = {
        "engine": "pianoplayer+constrained-hand-routing",
        "pianoplayer_version": UPSTREAM_VERSION,
        "pianoplayer_revision": UPSTREAM_REVISION,
        "pianoplayer_license": "MIT",
        "hand_size": hand_size,
        "source_note_count": len(source),
        "practice_note_count": len(result),
        "simplified_count": len(simplified_ids),
        "omitted_note_count": len(omitted),
        "omitted_notes": omitted,
        "shortened_note_count": len(shortened),
        "shortened_notes": list(shortened.values()),
        "trimmed_note_count": len(shortened),
        "trimmed_notes": list(shortened.values()),
        "chord_constraint_repairs": repaired,
        "proposal_policy": "preserve_valid_upstream_repair_conflicts_only",
        "constraint_validation": "passed",
        "source_hand_note_count": sum(n.get("source_hand") in ("L", "R") for n in source),
        "hand_routing": "explicit_labels_then_pitch_onset_span_continuity",
        "arrangement": "simplified_practice" if simplified_ids else "automatic_fingering",
        "fingering_kind": "automatic_practice_suggestion",
        "lookahead_notes": 7,
        "chord_lookahead_notes": 5,
        "chord_group_tolerance_seconds": _CHORD_TOLERANCE,
    }
    return result, metadata, warnings
