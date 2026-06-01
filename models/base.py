"""Base declarativa compartilhada por todos os models.

Todos os models herdam de `Base`, garantindo um único `registry`. Isso permite
que os `relationship()` resolvam classes-alvo entre módulos por nome (string),
sem imports circulares — desde que todos os módulos sejam importados antes da
configuração dos mappers (feito em `models/__init__.py`).
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
