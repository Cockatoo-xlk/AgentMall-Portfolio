"""Render an explicitly offline portfolio edit; requires optional Pillow/imageio-ffmpeg.

Reads an immutable source WebM and reviewed edit list. Does not run the application,
edit database facts, load credentials, synthesize a Provider response or overwrite media.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def render(source, edit_list, output, work, font_path):
    import imageio_ffmpeg
    from PIL import Image, ImageDraw, ImageFont

    edit = json.loads(edit_list.read_text())
    if hashlib.sha256(source.read_bytes()).hexdigest() != edit["source_sha256"]:
        raise ValueError("SOURCE_MEDIA_HASH_MISMATCH")
    if output.exists() or work.exists():
        raise FileExistsError("Preserve previous output/work directory")
    work.mkdir(parents=True, mode=0o700)
    output.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    title_font = ImageFont.truetype(str(font_path), 58)
    body_font = ImageFont.truetype(str(font_path), 36)
    label_font = ImageFont.truetype(str(font_path), 24)
    width, height = 1440, 1080

    def text_wrap(draw, value, y, font, color="#e9f2ef", max_width=1280):
        line = ""
        for char in value:
            if draw.textlength(line + char, font=font) > max_width:
                draw.text((80, y), line, font=font, fill=color)
                y += font.size + 16
                line = ""
            line += char
        draw.text((80, y), line, font=font, fill=color)
        return y + font.size + 30

    def panel(segment, overlay=False):
        canvas = Image.new(
            "RGBA", (width, height), (0, 0, 0, 0) if overlay else "#12352f"
        )
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((0, 0, width, 39), fill="#102723")
        draw.text(
            (24, 4),
            "OFFLINE MOCK DEMO | REAL BUSINESS API | REAL POSTGRESQL",
            font=label_font,
            fill="#d9f092",
        )
        if overlay:
            draw.rectangle((0, 1040, width, height), fill="#102723")
            draw.text((24, 1045), segment["caption"], font=label_font, fill="white")
        else:
            y = text_wrap(draw, segment["title"], 140, title_font, "#d9f092") + 45
            for line in segment["body"]:
                y = text_wrap(draw, line, y, body_font)
            draw.text(
                (80, 980),
                "自建合成业务 · 无真实付款退款 · 无真实 Provider 请求",
                font=label_font,
                fill="#b9cfca",
            )
        return canvas

    commands = []

    def run(name, args):
        command = [ffmpeg, "-hide_banner", "-nostdin", *args]
        result = subprocess.run(command, capture_output=True, check=False)
        (work / (name + ".log")).write_bytes(result.stdout + result.stderr)
        commands.append(
            {
                "name": name,
                "argv": command,
                "exit_code": result.returncode,
                "log_sha256": hashlib.sha256(result.stdout + result.stderr).hexdigest(),
            }
        )
        (work / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        if result.returncode:
            raise RuntimeError(f"MEDIA_COMMAND_FAILED:{name}")

    clips, cursor, chapters = [], 0, []
    for index, segment in enumerate(edit["segments"]):
        duration = segment["duration_seconds"]
        if type(duration) is not int or duration <= 0:
            raise ValueError("EDIT_DURATION_INVALID")
        clip, png = work / f"{index:02}.mp4", work / f"{index:02}.png"
        overlay = segment["kind"] == "source"
        panel(segment, overlay).save(png)
        if overlay:
            if (
                segment["source_start_seconds"] < 0
                or segment["source_start_seconds"] + duration > 415
            ):
                raise ValueError("SOURCE_TRIM_INVALID")
            inputs = [
                "-ss",
                str(segment["source_start_seconds"]),
                "-t",
                str(duration),
                "-i",
                str(source),
                "-loop",
                "1",
                "-i",
                str(png),
            ]
            filters = "[0:v]pad=1440:1080:0:40:black,setsar=1[base];[base][1:v]overlay=0:0:shortest=1[v]"
        else:
            inputs = ["-loop", "1", "-i", str(png)]
            filters = "[0:v]setsar=1[v]"
        run(
            f"segment-{index:02}",
            [
                *inputs,
                "-filter_complex",
                filters,
                "-map",
                "[v]",
                "-an",
                "-t",
                str(duration),
                "-r",
                "25",
                "-c:v",
                "libx264",
                "-preset",
                "fast",
                "-crf",
                "25",
                "-pix_fmt",
                "yuv420p",
                "-threads",
                "2",
                str(clip),
            ],
        )
        clips.append(clip)
        chapters.append((cursor, cursor + duration, segment["chapter"]))
        cursor += duration
    if not 180 <= cursor <= 300:
        raise ValueError("PORTFOLIO_DURATION_OUT_OF_RANGE")
    # ffmpeg concat list quoting, not shell quoting; paths are generated in the owned workspace.
    concat = work / "concat.txt"
    concat.write_text(
        "".join(
            "file '" + str(p.resolve()).replace("'", "'\\''") + "'\n" for p in clips
        )
    )
    metadata = work / "chapters.txt"
    metadata.write_text(
        ";FFMETADATA1\n"
        + "".join(
            f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={a * 1000}\nEND={b * 1000}\ntitle={title}\n"
            for a, b, title in chapters
        )
    )
    run(
        "concat",
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat),
            "-i",
            str(metadata),
            "-map_metadata",
            "1",
            "-map_chapters",
            "1",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
    )
    run("full-decode", ["-v", "error", "-i", str(output), "-f", "null", "-"])
    receipt = {
        "source_sha256": edit["source_sha256"],
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "bytes": output.stat().st_size,
        "duration_seconds": cursor,
        "width": width,
        "height": height,
        "fps": 25,
        "codec": "H264/yuv420p/MP4",
        "audio": "NONE_SILENT_CAPTIONED_EDIT",
        "source_recorder_exit_code": 1,
        "original_preserved": True,
        "card_kind": "EXPLANATORY_EVIDENCE_PROJECTION_NOT_RECORDED_TERMINAL",
        "chapters": chapters,
        "provider_requests": 0,
        "commands": commands,
    }
    (work / "render-receipt.json").write_text(
        json.dumps(receipt, indent=2, ensure_ascii=False) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in receipt.items() if k != "commands"}, ensure_ascii=False
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("source", "edit-list", "output", "work-dir", "font"):
        parser.add_argument("--" + arg, type=Path, required=True)
    args = parser.parse_args()
    render(args.source, args.edit_list, args.output, args.work_dir, args.font)
