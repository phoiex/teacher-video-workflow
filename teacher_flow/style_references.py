"""读取本机 Dify 上传的图片/视频，用实际画面准备风格参考。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps

from .common import course_dir, digest, save
from . import network_retry

MAX_FILES = 3
MAX_BYTES = 100 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


def validate_files(files):
    if files is None:
        return []
    if not isinstance(files, list) or len(files) > MAX_FILES:
        raise ValueError("参考图片和视频合计最多3个")
    if any(not isinstance(file, dict) for file in files):
        raise ValueError("参考素材格式不正确，请重新上传")
    return files


def local_file_url(value):
    """只读取 Dify 本机签名文件入口，不接收任意本机路径或网页地址。"""
    url = urllib.parse.urlsplit(str(value or ""))
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "localhost")
            or url.port != 8788 or url.username or url.password
            or not re.fullmatch(r"/files/[A-Za-z0-9_/-]+", url.path)):
        raise ValueError("请使用文件上传；网页链接暂不能作为参考素材")
    return urllib.parse.urlunsplit(url)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("参考素材发生跳转，请重新上传文件")


def download(file, folder):
    return network_retry.call(lambda _: _download_once(file, folder))


def _download_once(file, folder):
    url = local_file_url(file.get("url"))
    extension = Path(str(file.get("filename") or file.get("name") or "")).suffix.lower()
    if not extension:
        extension = str(file.get("extension") or "").lower()
    if extension not in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
        raise ValueError("支持PNG、JPG、WebP、GIF等图片，以及MP4、MOV、WebM视频")
    if int(file.get("size") or 0) > MAX_BYTES:
        raise ValueError("单个参考素材请控制在100MB以内")
    target = folder / ("source" + extension)
    if target.exists():
        return target
    partial = folder / ("source" + extension + ".part")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(url, timeout=30) as response, partial.open("wb") as out:
            total = 0
            while chunk := response.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("单个参考素材请控制在100MB以内")
                out.write(chunk)
        if not total:
            raise ValueError("参考素材为空，请重新上传")
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def thumbnail(source, target):
    with Image.open(source) as image:
        image.seek(0)
        if image.width * image.height > 24_000_000:
            raise ValueError("图片像素较大，请缩小到2400万像素以内")
        image.load()
        image = ImageOps.exif_transpose(image).convert("RGB")
        image.thumbnail((1280, 720))
        image.save(target, "JPEG", quality=88)


def executable(name):
    value = shutil.which(name)
    if not value or not Path(value).is_file():
        raise ValueError("视频读取工具尚未准备好，可先上传截图")
    return value


def video_frames(source, folder):
    result = subprocess.run([
        executable("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe",
        "-select_streams", "v:0", "-show_entries", "format=duration:stream=codec_type,avg_frame_rate",
        "-of", "json", str(source),
    ], capture_output=True, timeout=30, check=True)
    info = json.loads(result.stdout)
    duration = float(info.get("format", {}).get("duration") or 0)
    if not info.get("streams") or not math.isfinite(duration) or not 0 < duration <= 1800:
        raise ValueError("请上传有画面的短视频，最长30分钟")
    # 三组连续画面用于观察局部运动，时间戳留给模型和老师，不当作全片观看。
    step = min(.4, duration / 16)
    rate = str(info["streams"][0].get("avg_frame_rate") or "0/1").split("/")
    fps = float(rate[0]) / (float(rate[1]) or 1) if len(rate) == 2 else float(rate[0])
    last_sample = max(0, duration - max(.1, 2 / fps if fps > 0 else .2))
    times = sorted({round(min(max(0, duration * p + offset * step), last_sample), 3)
                    for p in (.15, .5, .85) for offset in (-1, 0, 1, 2)})
    frames = []
    for i, timestamp in enumerate(times):
        target = folder / f"frame-{i + 1:02}.jpg"
        subprocess.run([
            executable("ffmpeg"), "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
            "-ss", str(max(0, timestamp)), "-i", str(source), "-frames:v", "1",
            "-vf", "scale=1280:720:force_original_aspect_ratio=decrease", "-q:v", "3",
            "-y", str(target),
        ], capture_output=True, timeout=30, check=True)
        if not target.is_file():
            raise ValueError("视频画面读取不完整，请换一个片段")
        frames.append((target, timestamp))
    return frames, duration


def prepare(cid, files):
    assets, images, issues = [], [], []
    for index, file in enumerate(validate_files(files), 1):
        name = str(file.get("filename") or file.get("name") or f"素材{index}")
        folder = course_dir(cid) / "references" / digest(file)[:20]
        folder.mkdir(parents=True, exist_ok=True)
        try:
            source = download(file, folder)
            if source.suffix.lower() in IMAGE_EXTENSIONS:
                target = folder / "image.jpg"
                thumbnail(source, target)
                frames, duration = [(target, None)], None
                kind = "image"
            else:
                frames, duration = video_frames(source, folder)
                kind = "video"
            ids = []
            for frame_index, (path, timestamp) in enumerate(frames, 1):
                image_id = f"ref{index:02}_{frame_index:02}"
                ids.append(image_id)
                images.append({"image_id": image_id, "path": str(path),
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                               "source_name": name, "timestamp_seconds": timestamp})
            assets.append({"name": name, "kind": kind, "duration_seconds": duration,
                           "image_ids": ids, "sample_times": [t for _, t in frames if t is not None]})
        except Exception as exc:
            if network_retry.is_network_error(exc):
                raise
            # 错误只显示可用操作，不暴露签名URL、终端输出或本机路径。
            message = str(exc) if isinstance(exc, ValueError) else "素材未能读取，请换成截图或较短的视频文件"
            issues.append({"name": name, "message": message})
    result = {"assets": assets, "images": images, "issues": issues}
    save(course_dir(cid) / "references" / "manifest.json", result)
    return result


def style_description(data, image_ids):
    if not isinstance(data, dict):
        raise ValueError("未收到完整风格说明")
    evidence = data.get("evidence_ids")
    if not isinstance(evidence, list) or not evidence or not set(evidence).issubset(image_ids):
        raise ValueError("风格说明缺少对应画面，参考素材已保留")
    labels = {"summary": "整体", "palette": "配色", "typography": "文字",
              "composition": "布局", "motion": "动效", "adaptation": "用于本课"}
    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("未收到完整风格说明")
    lines = []
    for key, label in labels.items():
        value = data.get(key, "")
        if not isinstance(value, str) or len(value) > 1600:
            raise ValueError("风格说明格式不完整")
        if value.strip():
            lines.append(label + "：" + value.strip())
    return "\n".join(lines)
