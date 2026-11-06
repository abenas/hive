"""Cliente do ComfyUI (API HTTP) para gerar imagens SDXL na GPU local e entregá-las em WebP."""

import asyncio
import io
import time
import uuid
from dataclasses import dataclass

import httpx
from PIL import Image

from hive.config import Settings


class ImageError(RuntimeError):
    pass


@dataclass
class RenderedImage:
    data: bytes  # WebP pronto para publicar
    width: int
    height: int
    seconds: float


def sdxl_workflow(s: Settings, prompt: str, negative: str, seed: int) -> dict:
    """Workflow texto→imagem do SDXL no formato de API do ComfyUI (nós numerados)."""
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": s.comfyui_checkpoint}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage",
              "inputs": {"width": s.comfyui_width, "height": s.comfyui_height, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": s.comfyui_steps, "cfg": s.comfyui_cfg, "sampler_name": "dpmpp_2m",
            "scheduler": "karras", "denoise": 1.0, "model": ["4", 0], "positive": ["6", 0],
            "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "hive", "images": ["8", 0]}},
    }


def to_webp(png: bytes, max_width: int, quality: int) -> tuple[bytes, int, int]:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    if img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=quality, method=6)
    return out.getvalue(), img.width, img.height


class ComfyUIClient:
    def __init__(self, settings: Settings):
        self.s = settings
        self.http = httpx.AsyncClient(base_url=settings.comfyui_url, timeout=60)

    async def available(self) -> bool:
        try:
            return (await self.http.get("/system_stats")).status_code == 200
        except httpx.HTTPError:
            return False

    async def render(self, prompt: str, negative: str, seed: int, timeout_s: float = 600) -> RenderedImage:
        start = time.perf_counter()
        try:
            r = await self.http.post("/prompt", json={"prompt": sdxl_workflow(self.s, prompt, negative, seed),
                                                      "client_id": uuid.uuid4().hex})
        except httpx.ConnectError as e:
            raise ImageError(f"ComfyUI indisponível em {self.s.comfyui_url}") from e
        if r.status_code != 200:
            raise ImageError(f"ComfyUI recusou o workflow ({r.status_code}): {r.text[:300]}")
        prompt_id = r.json()["prompt_id"]
        while True:
            history = (await self.http.get(f"/history/{prompt_id}")).json().get(prompt_id)
            if history:
                status = history.get("status", {})
                if status.get("status_str") == "error":
                    raise ImageError(f"ComfyUI falhou ao gerar: {status.get('messages', [])[-1:]}")
                images = history.get("outputs", {}).get("9", {}).get("images", [])
                if images:
                    break
            if time.perf_counter() - start > timeout_s:
                raise ImageError(f"ComfyUI não terminou em {timeout_s:.0f} s")
            await asyncio.sleep(1)
        ref = images[0]
        png = (await self.http.get("/view", params={"filename": ref["filename"], "subfolder": ref["subfolder"],
                                                    "type": ref["type"]})).content
        data, width, height = to_webp(png, self.s.image_max_width, self.s.image_quality)
        return RenderedImage(data=data, width=width, height=height, seconds=time.perf_counter() - start)

    async def free(self) -> None:
        """Libera a VRAM do ComfyUI para o LLM voltar a carregar."""
        try:
            await self.http.post("/free", json={"unload_models": True, "free_memory": True})
        except httpx.HTTPError:
            pass


def placeholder_webp(palette: dict, seed: str, width: int, height: int, max_width: int, quality: int) -> bytes:
    """Plano B raster quando a geração falha: gradiente diagonal com as cores do design system."""
    import hashlib

    def rgb(hex_color: str) -> tuple[int, int, int]:
        h = hex_color.lstrip("#")
        return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    a, b = rgb(palette.get("primary", "#7c3aed")), rgb(palette.get("secondary", "#06b6d4"))
    bg = rgb(palette.get("background", "#0b0b16"))
    shift = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % 100 / 100
    w, h = 320, round(320 * height / width)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = min(1.0, max(0.0, (x / w + y / h) / 2 + shift - 0.5))
            glow = max(0.0, 1 - abs((x / w) - (y / h) - shift + 0.5) * 3)
            px[x, y] = tuple(int(bg[i] * (1 - glow) + (a[i] * (1 - t) + b[i] * t) * glow) for i in range(3))
    img = img.resize((min(max_width, width), round(min(max_width, width) * height / width)), Image.BICUBIC)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=quality)
    return out.getvalue()
