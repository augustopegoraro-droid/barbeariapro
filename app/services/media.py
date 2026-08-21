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
# Foto de feed não é retrato: preserva a proporção original (banner, cartaz,
# print de promoção) e só encolhe se for maior que isto.
FEED_MAX_WIDTH = 1280

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


def _relative(org_id: int, slug: str) -> str:
    return f"org{org_id}/{slug}.webp"


def _target(org_id: int, slug: str) -> Path:
    return media_root() / f"org{org_id}" / f"{slug}.webp"


def _validate_upload(raw: bytes, content_type: str | None) -> None:
    """Rejeita o que nem chega ao decode (vazio, grande demais, tipo proibido)."""
    if not raw:
        raise MediaError("Arquivo vazio.")
    if len(raw) > MAX_UPLOAD_BYTES:
        mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise MediaError(f"Imagem muito grande (máximo {mb} MB).")
    if content_type and content_type.split(";")[0].strip().lower() not in ALLOWED_CONTENT_TYPES:
        raise MediaError(f"Formato não suportado. Envie {_FORMATS_PT}.")


def _encode_webp(raw: bytes, transform) -> bytes:
    """Decodifica, aplica `transform` (Image → Image) e devolve WebP sem EXIF.

    O decode pelo Pillow é a barreira contra arquivo executável/SVG disfarçado;
    a reescrita descarta o EXIF (geolocalização) de tabela.
    """
    try:
        with Image.open(io.BytesIO(raw)) as img:
            # Respeita a orientação do EXIF antes de qualquer resize (foto de
            # celular deitada viraria de lado) e já descarta o resto do EXIF.
            img = ImageOps.exif_transpose(img)
            out = transform(img.convert("RGB"))
            buffer = io.BytesIO()
            out.save(buffer, format="WEBP", quality=OUTPUT_QUALITY, method=6)
    except UnidentifiedImageError as exc:
        raise MediaError(f"Não conseguimos ler esta imagem. Envie {_FORMATS_PT}.") from exc
    except OSError as exc:  # arquivo truncado/corrompido no meio do decode
        raise MediaError("Imagem corrompida ou incompleta.") from exc
    return buffer.getvalue()


def _write_atomic(org_id: int, slug: str, data: bytes) -> str:
    """Grava o WebP e devolve o caminho relativo com cache-busting."""
    path = _target(org_id, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Escreve em temporário e renomeia: um upload concorrente (ou um erro no
    # meio da escrita) nunca deixa a foto meio gravada sendo servida.
    tmp = path.with_suffix(".webp.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)

    # mtime em NANOssegundos: dois uploads dentro do mesmo segundo ainda geram
    # `?v=` distintos (com segundos inteiros, a 2ª troca não furaria o cache).
    version = path.stat().st_mtime_ns
    return f"{_relative(org_id, slug)}?v={version}"


def save_photo(org_id: int, slug: str, raw: bytes, content_type: str | None) -> str:
    """Normaliza e grava a foto (quadrada); devolve o caminho relativo do banco.

    `slug` é o nome do arquivo (sem extensão), sempre derivado de identificador
    do próprio sistema — nunca do nome enviado pelo cliente. Ver os wrappers
    `save_barber_photo`/`save_client_photo` para o porquê de cada escolha.

    Levanta `MediaError` para tudo que é culpa do arquivo (tipo, tamanho, bytes
    corrompidos) — o chamador traduz em 422.
    """
    _validate_upload(raw, content_type)
    data = _encode_webp(
        raw,
        # Recorte quadrado centralizado + resize numa passada.
        lambda img: ImageOps.fit(
            img, (OUTPUT_SIZE, OUTPUT_SIZE), method=Image.LANCZOS
        ),
    )
    return _write_atomic(org_id, slug, data)


def _fit_width(img: "Image.Image") -> "Image.Image":
    """Encolhe proporcionalmente até `FEED_MAX_WIDTH`; nunca amplia."""
    if img.width <= FEED_MAX_WIDTH:
        return img
    height = max(1, round(img.height * FEED_MAX_WIDTH / img.width))
    return img.resize((FEED_MAX_WIDTH, height), Image.LANCZOS)


def save_image_keep_ratio(
    org_id: int, slug: str, raw: bytes, content_type: str | None
) -> str:
    """Igual a `save_photo`, mas SEM crop: preserva a proporção original.

    Foto de rosto pode ser recortada em quadrado sem perda de sentido; um
    cartaz de promoção, não — cortar mata metade da informação. Mesma validação,
    mesmo WebP, mesmo descarte de EXIF, mesma escrita atômica.
    """
    _validate_upload(raw, content_type)
    data = _encode_webp(raw, _fit_width)
    return _write_atomic(org_id, slug, data)


def delete_photo(org_id: int, slug: str) -> None:
    """Remove o arquivo. Ausente = sucesso (idempotente)."""
    try:
        _target(org_id, slug).unlink(missing_ok=True)
    except OSError:  # pragma: no cover — disco/permissão: o campo já foi limpo
        logger.warning(
            "media: falha ao remover mídia %s (org %s)", slug, org_id, exc_info=True
        )


# ─── profissional (D-85) ──────────────────────────────────────────────────────
# Slug pelo id numérico: a foto do profissional é conteúdo de vitrine, aparece
# na listagem pública de qualquer jeito — enumerar não revela nada novo.

def save_barber_photo(org_id: int, barber_id: int, raw: bytes, content_type: str | None) -> str:
    return save_photo(org_id, f"barber-{barber_id}", raw, content_type)


def delete_barber_photo(org_id: int, barber_id: int) -> None:
    delete_photo(org_id, f"barber-{barber_id}")


# ─── cliente final (app nativo, Fase A) ───────────────────────────────────────
# Slug pelo `clients.public_id` (UUID), NUNCA pelo id numérico: `/media` é
# `StaticFiles` público sem autenticação, e id sequencial tornaria o acervo de
# fotos de rosto de clientes enumerável (`org1/client-1.webp`, `-2`, ...) —
# vazamento de dado pessoal sensível (LGPD). UUID não é adivinhável.

def save_client_photo(
    org_id: int, client_public_id, raw: bytes, content_type: str | None
) -> str:
    return save_photo(org_id, f"client-{client_public_id}", raw, content_type)


def delete_client_photo(org_id: int, client_public_id) -> None:
    delete_photo(org_id, f"client-{client_public_id}")


# ─── feed de novidades ────────────────────────────────────────────────────────
# Slug pelo id sequencial do post: é conteúdo de vitrine pública (o feed inteiro
# é aberto), então enumerar não revela nada que a rota pública já não entregue —
# ao contrário da foto de cliente, que é PII e usa UUID.
# Sem crop quadrado: um cartaz/banner perde sentido recortado.

def save_feed_image(org_id: int, post_id: int, raw: bytes, content_type: str | None) -> str:
    return save_image_keep_ratio(org_id, f"feed-{post_id}", raw, content_type)


def delete_feed_image(org_id: int, post_id: int) -> None:
    delete_photo(org_id, f"feed-{post_id}")
