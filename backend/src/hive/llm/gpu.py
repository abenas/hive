"""Árbitro de GPU: várias chamadas de LLM podem compartilhar a placa; geração de imagem exige exclusividade.

Na mesma GPU de 16 GB não cabem o LLM (~14 GB com duas vagas) e o SDXL (~8 GB) ao mesmo tempo. Quem pede
uso exclusivo tem prioridade: novas chamadas de LLM esperam, as que estão em andamento terminam.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class GpuArbiter:
    def __init__(self) -> None:
        self._cond = asyncio.Condition()
        self._shared = 0
        self._exclusive = False
        self._waiting_exclusive = 0

    @asynccontextmanager
    async def shared(self) -> AsyncIterator[None]:
        async with self._cond:
            await self._cond.wait_for(lambda: not self._exclusive and not self._waiting_exclusive)
            self._shared += 1
        try:
            yield
        finally:
            async with self._cond:
                self._shared -= 1
                self._cond.notify_all()

    @asynccontextmanager
    async def exclusive(self) -> AsyncIterator[None]:
        async with self._cond:
            self._waiting_exclusive += 1
            try:
                await self._cond.wait_for(lambda: not self._exclusive and self._shared == 0)
            finally:
                self._waiting_exclusive -= 1
            self._exclusive = True
        try:
            yield
        finally:
            async with self._cond:
                self._exclusive = False
                self._cond.notify_all()
