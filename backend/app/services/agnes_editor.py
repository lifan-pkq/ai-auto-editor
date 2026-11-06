"""Agnes editing pipeline.

upload video -> ffprobe metadata -> Agnes OpenAI-compatible plan (heuristic fallback)
-> ffmpeg cut/concat -> export.
Credentials come from AGNES_API_BASE / AGNES_API_KEY env vars only (never hardcoded).
Blocking work (subprocess / HTTP) is expected to be run via asyncio.to_thread.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import httpx

AGNES_MODEL_ENV = "AGNES_MODEL"
DEFAULT_AGNES_MODEL = "agnes-3.0-flash"

FFPROBE_TIMEOUT_SECONDS = 120
FFMPEG_BASE_TIMEOUT_SECONDS = 300
FFMPEG_TIMEOUT_PER_SOURCE_SECOND = 10.0
MAX_PLAN_SEGMENTS = 6
MIN_SEGMENT_SECONDS = 0.5
HEURISTIC_TARGET_RATIO = 0.2
HEURISTIC_TARGET_CAP_SECONDS = 60.0


class AgnesPlanError(Exception):
    pass


@dataclass
class VideoMeta:
    duration: float
    width: int
    height: int
    has_audio: bool
    codec: str


@dataclass
class Segment:
    start: float
    end: float


def get_agnes_credentials() -> Tuple[str, str]:
    return os.getenv("AGNES_API_BASE", ""), os.getenv("AGNES_API_KEY", "")


def probe_video(video_path: Path) -> VideoMeta:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=FFPROBE_TIMEOUT_SECONDS)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()[:500]}")
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError(f"no video stream in {video_path}")
    duration = float(payload.get("format", {}).get("duration") or video.get("duration") or 0.0)
    if duration <= 0:
        raise RuntimeError("could not determine video duration")
    return VideoMeta(
        duration=duration,
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        codec=str(video.get("codec_name") or "unknown"),
    )


def heuristic_plan(duration: float, target_seconds: Optional[float] = None) -> List[Segment]:
    """Keep short, evenly distributed segments totaling the requested (or default) length."""
    if duration <= 0:
        raise AgnesPlanError("video duration must be positive")
    if target_seconds and target_seconds > 0:
        target = min(float(target_seconds), duration)
    else:
        target = min(HEURISTIC_TARGET_RATIO * duration, HEURISTIC_TARGET_CAP_SECONDS)
    if target < MIN_SEGMENT_SECONDS:
        target = duration
    n = max(1, min(MAX_PLAN_SEGMENTS, round(duration / 10.0)))
    if duration <= n:
        n = 1
    seg_len = target / n
    step = duration / n
    plan: List[Segment] = []
    for i in range(n):
        center = i * step + step / 2.0
        start = max(0.0, center - seg_len / 2.0)
        end = min(duration, start + seg_len)
        if end - start >= MIN_SEGMENT_SECONDS:
            plan.append(Segment(round(start, 3), round(end, 3)))
    if not plan:
        plan = [Segment(0.0, round(duration, 3))]
    return plan


def parse_plan(content: Optional[str], duration: float) -> List[Segment]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise AgnesPlanError("no JSON object in model reply")
    data = json.loads(match.group(0))
    raw = data.get("segments")
    if not isinstance(raw, list) or not raw:
        raise AgnesPlanError("missing or empty 'segments' list")

    plan: List[Segment] = []
    for item in raw[: MAX_PLAN_SEGMENTS + 2]:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        start = max(0.0, min(start, duration))
        end = max(start, min(end, duration))
        if end - start >= MIN_SEGMENT_SECONDS:
            plan.append(Segment(round(start, 3), round(end, 3)))
    if not plan:
        raise AgnesPlanError("no valid segments")

    plan.sort(key=lambda s: s.start)
    merged: List[Segment] = [plan[0]]
    for seg in plan[1:]:
        if seg.start < merged[-1].end:
            merged[-1] = Segment(merged[-1].start, round(max(merged[-1].end, seg.end), 3))
        else:
            merged.append(seg)

    total = sum(s.end - s.start for s in merged)
    if total >= duration - 0.25:
        raise AgnesPlanError("plan is not shorter than the source")
    return merged


def request_agnes_plan(
    api_base: str,
    api_key: str,
    model: str,
    meta: VideoMeta,
    target_seconds: Optional[float] = None,
) -> List[Segment]:
    base = api_base.rstrip("/")
    meta_json = {
        "duration_seconds": round(meta.duration, 3),
        "width": meta.width,
        "height": meta.height,
        "video_codec": meta.codec,
        "has_audio": meta.has_audio,
        "target_duration_seconds": round(target_seconds, 1) if target_seconds else None,
    }
    target_rule = (
        f"- Aim for a total edited length near {target_seconds:.1f} seconds (not longer than the source).\n"
        if target_seconds and target_seconds > 0
        else "- The final clip must be shorter than the source and focus on the most valuable parts.\n"
    )
    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": "You are a precise video editing assistant. Reply with a single JSON object only."},
            {
                "role": "user",
                "content": (
                    "Create a short, clean cut of this video.\n"
                    f"Video metadata: {json.dumps(meta_json)}\n"
                    "Rules:\n"
                    f"{target_rule}"
                    "- Prefer clean cut points (avoid jumping mid-action where possible).\n"
                    f"- Return JSON: {{\"segments\": [{{\"start\": <seconds>, \"end\": <seconds>}}]}} with 1 to {MAX_PLAN_SEGMENTS} segments,\n"
                    f"  where 0 <= start < end <= {meta.duration:.1f} and segments do not overlap.\n"
                    "Reply with the JSON object only, no prose."
                ),
            },
        ],
    }
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AgnesPlanError("unexpected chat/completions response shape")
    return parse_plan(content, meta.duration)


def _trim_plan_to_target(plan: List[Segment], target_seconds: Optional[float]) -> List[Segment]:
    if not target_seconds or target_seconds <= 0 or not plan:
        return plan
    kept: List[Segment] = []
    used = 0.0
    for seg in plan:
        remaining = target_seconds - used
        if remaining <= MIN_SEGMENT_SECONDS:
            break
        length = seg.end - seg.start
        if length <= remaining:
            kept.append(seg)
            used += length
        else:
            kept.append(Segment(seg.start, round(seg.start + remaining, 3)))
            break
    return kept or plan[:1]


def build_edit_plan(meta: VideoMeta, target_seconds: float | None = None) -> Tuple[List[Segment], str]:
    """Return (plan, note). Uses Agnes when configured, otherwise / on failure the heuristic plan."""
    api_base, api_key = get_agnes_credentials()
    if not api_base or not api_key:
        plan = heuristic_plan(meta.duration, target_seconds)
        total = round(sum(s.end - s.start for s in plan), 1)
        return plan, f"heuristic plan: {len(plan)} segment(s), ~{total}s (target={target_seconds})"
    model = os.getenv(AGNES_MODEL_ENV, DEFAULT_AGNES_MODEL)
    try:
        plan = request_agnes_plan(api_base, api_key, model, meta, target_seconds)
        plan = _trim_plan_to_target(plan, target_seconds)
        total = round(sum(s.end - s.start for s in plan), 1)
        return plan, f"Agnes plan: {len(plan)} segment(s), ~{total}s of {meta.duration:.1f}s (target={target_seconds})"
    except AgnesPlanError as exc:
        plan = heuristic_plan(meta.duration, target_seconds)
        return plan, f"Agnes plan unusable ({exc}), using heuristic plan"
    except Exception as exc:
        plan = heuristic_plan(meta.duration, target_seconds)
        return plan, f"Agnes request failed ({exc}), using heuristic plan"


ASPECT_TARGETS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def _aspect_filter(aspect_ratio: Optional[str]) -> str:
    """Return a scale+crop chain that ends ready for further labels, or empty string."""
    if not aspect_ratio or aspect_ratio not in ASPECT_TARGETS:
        return ""
    tw, th = ASPECT_TARGETS[aspect_ratio]
    # scale to cover, then center-crop to target
    return (
        f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
        f"crop={tw}:{th}"
    )


def _subtitle_filter(enable: bool, text: str = "AI Auto Edit") -> str:
    if not enable:
        return ""
    safe = text.replace(":", "\\:").replace("'", "")
    # drawtext is widely available; fall back handled by caller if filter fails
    return (
        f"drawtext=text='{safe}':fontsize=36:fontcolor=white:borderw=2:"
        f"bordercolor=black:x=(w-text_w)/2:y=h-80"
    )


def _ffmpeg_command(
    video_path: Path,
    segments: List[Segment],
    meta: VideoMeta,
    output_path: Path,
    aspect_ratio: Optional[str] = None,
    subtitles: bool = False,
) -> List[str]:
    n = len(segments)
    parts: List[str] = []
    for i, seg in enumerate(segments):
        parts.append(f"[0:v]trim=start={seg.start:.3f}:end={seg.end:.3f},setpts=PTS-STARTPTS[v{i}]")
        if meta.has_audio:
            parts.append(f"[0:a]atrim=start={seg.start:.3f}:end={seg.end:.3f},asetpts=PTS-STARTPTS[a{i}]")
    post = []
    af = _aspect_filter(aspect_ratio)
    if af:
        post.append(af)
    sf = _subtitle_filter(subtitles)
    if sf:
        post.append(sf)
    post_chain = ",".join(post)

    if meta.has_audio:
        parts.append(
            "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][outa]"
        )
        if post_chain:
            parts.append(f"[cv]{post_chain}[outv]")
        else:
            parts.append("[cv]null[outv]")
        map_args = ["-map", "[outv]", "-map", "[outa]"]
        audio_args = ["-c:a", "aac", "-b:a", "128k"]
    else:
        parts.append("".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[cv]")
        if post_chain:
            parts.append(f"[cv]{post_chain}[outv]")
        else:
            parts.append("[cv]null[outv]")
        map_args = ["-map", "[outv]"]
        audio_args = ["-an"]
    return [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-filter_complex",
        ";".join(parts),
        *map_args,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "21",
        "-pix_fmt",
        "yuv420p",
        *audio_args,
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def edit_segments(
    video_path: Path,
    segments: List[Segment],
    meta: VideoMeta,
    output_path: Path,
    aspect_ratio: Optional[str] = None,
    subtitles: bool = False,
) -> None:
    """Cut segments and concat them into a re-encoded intermediate mp4 (clean cuts)."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH")
    if not segments:
        raise RuntimeError("empty edit plan")
    cmd = _ffmpeg_command(video_path, segments, meta, output_path, aspect_ratio, subtitles)
    timeout = FFMPEG_BASE_TIMEOUT_SECONDS + int(meta.duration * FFMPEG_TIMEOUT_PER_SOURCE_SECOND)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0 and subtitles:
        # Retry without drawtext if font/filter unavailable
        cmd = _ffmpeg_command(video_path, segments, meta, output_path, aspect_ratio, False)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:])
        raise RuntimeError(f"ffmpeg edit failed: {tail}")
    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced no output file")


def export_to_output(intermediate_path: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if intermediate_path == output_path:
        return
    shutil.move(str(intermediate_path), str(output_path))
    if not output_path.is_file():
        raise RuntimeError("export failed: output.mp4 missing")
