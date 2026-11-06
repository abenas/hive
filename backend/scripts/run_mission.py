"""Executa uma missão de ponta a ponta pela API, aprovando os portões, e resume o resultado.

Uso: uv run python scripts/run_mission.py "Crie um site para a empresa X, do segmento Y..."
Útil para benchmark de modelos: compare as missões depois na aba Comparar do console.
"""

import os
import sys
import time
from datetime import datetime

import httpx

API = os.environ.get("HIVE_API", "http://localhost:8001/api")


def main(request: str) -> None:
    c = httpx.Client(timeout=30)
    t0 = time.time()
    mid = c.post(f"{API}/missions", json={"request": request, "requester": "benchmark"}).json()["id"]
    print("missão", mid, flush=True)

    def wait(targets: set[str], limit: int = 2400) -> str:
        last = None
        while time.time() - t0 < limit:
            status = c.get(f"{API}/missions/{mid}").json()["status"]
            if status != last:
                print(f"[{time.time() - t0:6.1f}s] {status}", flush=True)
                last = status
            if status in targets:
                return status
            time.sleep(2)
        return "timeout"

    for gate in ("plan", "deploy"):
        if wait({f"awaiting_{gate}_approval", "failed", "completed", "rejected"}) != f"awaiting_{gate}_approval":
            break
        c.post(f"{API}/missions/{mid}/approvals", json={"gate": gate, "approved": True, "actor": "benchmark"})
    status = wait({"completed", "failed", "rejected"})

    d = c.get(f"{API}/missions/{mid}").json()
    audit = c.get(f"{API}/missions/{mid}/audit").json()
    print(f"STATUS {status} | {time.time() - t0:.0f}s | erro: {d.get('error')}")
    print(f"trilha íntegra: {audit['chain']['valid']} ({audit['chain']['events']} eventos)")
    for t in d["tasks"]:
        dur = ""
        if t["started_at"] and t["finished_at"]:
            secs = (datetime.fromisoformat(t["finished_at"]) - datetime.fromisoformat(t["started_at"])).total_seconds()
            dur = f"{secs:.0f}s"
        print(f"  {t['agent']:15} tent={t['attempt']} {t['status']:8} {dur:>6} in={t['tokens_in']} out={t['tokens_out']}")
        for e in (t["result"] or {}).get("evidence", []):
            if e["passed"] is False:
                print("     ✗", e["title"], "|", e["detail"][:120])
        if t["feedback"]:
            print("     retrabalho:", t["feedback"].replace("\n", " | ")[:300])
    print(f"custo US$ {audit['costs']['total_usd']} | chamadas {audit['costs']['calls']} | site {d.get('deployment_url')}")


if __name__ == "__main__":
    main(" ".join(sys.argv[1:]))
