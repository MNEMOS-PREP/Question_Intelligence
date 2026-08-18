"""M05 — Question Intelligence · standalone application.

Runs this module ALONE on its reserved port, for focused development without
the other 18 in the way:

    uvicorn backend_M05_Question_Intelligence.app:app --reload --port 8105

The same router is also mounted into the gateway on :8000. Identical behaviour
either way. Ports: PORTS.txt.

**The ontology loads at startup, and a broken one fails the boot.** Deliberate:
an empty concept list makes every item untaggable and every selection
unconstrained, while every endpoint keeps answering. Failing loudly on a
machine is the cheap version of discovering that in a session.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from ai_core.modules_meta import ModuleStatus, module_status
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import bank as bank_module
from . import ontology
from .router import router

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    concepts = ontology.load()
    loaded = bank_module.load()
    log.info(
        "M05 ready — %d concepts (%s, reviewed=%s), %d items, %d in the fallback playlist",
        len(concepts),
        concepts.source,
        concepts.reviewed,
        len(loaded.questions),
        len(loaded.playlist),
    )
    yield


app = FastAPI(title="M05 — Question Intelligence", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    concepts = ontology.load()
    loaded = bank_module.load()
    return {
        "status": "ok",
        "module": "M05",
        "ontology_version": concepts.version,
        "ontology_source": concepts.source,
        # Said out loud because M04 §14 gates Phase-1 exit on the faculty walk,
        # and a bank tagged against an unreviewed ontology is a known state
        # rather than a surprise.
        "ontology_reviewed": concepts.reviewed,
        "bank_items": len(loaded.questions),
        # No calibration is fitted in this slice and saying so is the point:
        # every item's parameters come from the band table and the spacing
        # prior (§6.5), which `params_source` reports per selection.
        "calibration": "none",
    }


@app.get("/status", response_model=ModuleStatus, tags=["meta"])
def status() -> ModuleStatus:
    return module_status("M05")
