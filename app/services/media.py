# file: app/services/media.py
"""Storage de mídia local (D-85) — primeiro upload de arquivo do produto.

Até aqui o sistema só guardava URLs de terceiros (`attachments.url` aponta para
a Evolution; `public_info.logo_url` é colado à mão). A foto do profissional
precisa de arquivo próprio, então este módulo é o storage:

- **Onde:** `MEDIA_ROOT` (volume do host montado no container). Um subdiretório
  por org — `org{id}/` — para que nada cruze tenant nem colida de nome.
- **Nome:** derivado SÓ de ids numéricos (`barber-{id}.webp`). O nome enviado
  pelo cliente é **descartado** — é a defesa contra path traversal
  (`../../etc/...`) e contra `.php`/`.svg` disfarçados.
- **O que grava:** sempre **WebP quadrado** normalizado pelo Pillow, nunca os
  bytes originais. Isso (a) impede que um arquivo executável/SVG com script
  chegue ao disco — se o Pillow não decodifica como imagem, é 422; (b) apaga o
  EXIF, que em foto de celular carrega **geolocalização**; (c) derruba 4 MB de
  câmera para ~60 KB, o que importa no 4G do cliente.
- **URL:** o banco guarda o caminho relativo (`org1/barber-7.webp?v=...`) e a
  URL pública é montada na leitura com `MEDIA_PUBLIC_BASE` — trocar domínio ou
  storage não invalida dado gravado. O `?v=` (mtime) é cache-busting: o nome do
  arquivo é estável, então sem ele o browser/nginx serviria a foto antiga.
"""

from __future__ import annotations

import io
import logging
import mimetypes
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

# Foto de iPhone é HEIC e o Pillow não decodifica sozinho. Registro opcional:
# sem o pacote, HEIC sai da lista de formatos aceitos e o usuário recebe uma
# mensagem coerente em vez de "não conseguimos ler esta imagem".
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIC_SUPPORTED = True
except ImportError:  # pragma: no cover — ambiente sem a dep opcional
    HEIC_SUPPORTED = False

# O `mimetypes` do Python resolve `.webp` a partir do /etc/mime.types do SO, que
# NÃO existe na imagem `python:3.12-slim` — sem este registro o StaticFiles serve
# a foto como `application/octet-stream` (pegado no smoke de prod do D-85; passa
# despercebido em dev, onde o macOS tem o arquivo).
mimetypes.add_type("image/webp", ".webp")

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MB: foto de celular moderna cabe
OUTPUT_SIZE = 800                   # lado do quadrado final, em px
OUTPUT_QUALITY = 82

# Aceita só o que o Pillow decodifica com segurança como foto. SVG fica fora de
# propósito (é XML — vetor de script), e o formato real é reconferido no decode.
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
if HEIC_SUPPORTED:
    ALLOWED_CONTENT_TYPES |= {"image/heic", "image/heif"}

_FORMATS_PT = "JPG, PNG, WebP ou HEIC" if HEIC_SUPPORTED else "JPG, PNG ou WebP"


class MediaError(Exception):
    """Falha atribuível ao arquivo enviado (vira 422 na API)."""


def media_root() -> Path:
    return Path(settings.media_root)


def public_url(relative_path: Optional[str]) -> Optional[str]:
    """Caminho relativo do banco → URL que o browser consegue abrir."""
    if not relative_path:
        return None
    base = settings.media_public_base.rstrip("/")
    return f"{base}/{relative_path.lstrip('/')}"


def _target(org_id: int, barber_id: int) -> Path:
    return media_root() / f"org{org_id}" / f"barber-{barber_id}.webp"


def save_barber_photo(org_id: int, barber_id: int, raw: bytes, content_type: str | None) -> str:
    """Normaliza e grava a foto; devolve o caminho relativo a gravar no banco.

    Levanta `MediaError` para tudo que é culpa do arquivo (tipo, tamanho, bytes
    corrompidos) — o chamador traduz em 422.
    """
    if not raw:
        raise MediaError("Arquivo vazio.")
    if len(raw) > MAX_UPLOAD_BYTES:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise MediaError(f"Imagem muito grande (máximo {mb} MB).")
    if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
        raise MediaError(f"Formato não suportado. Envie {_FORMATS_PT}.")

    try:
        with Image.open(io.BytesIO(raw)) as img:
            # Respeita a orientação do EXIF antes de recortar (foto de celular
            # deitada viraria de lado) e já descarta o resto do EXIF.
            img = ImageOps.exif_transpose(img)
            # Recorte quadrado centralizado + resize numa passada.
            square = ImageOps.fit(
                img.convert("RGB"), (OUTPUT_SIZE, OUTPUT_SIZE), method=Image.LANCZOS
            )
            buffer = io.BytesIO()
            square.save(buffer, format="WEBP", quality=OUTPUT_QUALITY, method=6)
    except UnidentifiedImageError as exc:
        raise MediaError(f"Não conseguimos ler esta imagem. Envie {_FORMATS_PT}.") from exc
    except OSError as exc:  # arquivo truncado/corrompido no meio do decode
        raise MediaError("Imagem corrompida ou incompleta.") from exc

    path = _target(org_id, barber_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escreve em temporário e renomeia: um upload concorrente (ou um erro no
    # meio da escrita) nunca deixa a foto meio gravada sendo servida.
    tmp = path.with_suffix(".webp.tmp")
    tmp.write_bytes(buffer.getvalue())
    tmp.replace(path)

    # mtime em NANOssegundos: dois uploads dentro do mesmo segundo ainda geram
    # `?v=` distintos (com segundos inteiros, a 2ª troca não furaria o cache).
    version = path.stat().st_mtime_ns
    return f"org{org_id}/barber-{barber_id}.webp?v={version}"


def delete_barber_photo(org_id: int, barber_id: int) -> None:
    """Remove o arquivo. Ausente = sucesso (idempotente)."""
    try:
        _target(org_id, barber_id).unlink(missing_ok=True)
    except OSError:  # pragma: no cover — disco/permissão: o campo já foi limpo
        logger.warning(
            "media: falha ao remover foto do barbeiro %s (org %s)", barber_id, org_id, exc_info=True
        )
