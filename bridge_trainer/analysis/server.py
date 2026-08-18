"""Local analysis server: serves the analyze page and runs the engine.

The deployed BridgeTrainer app is a static site + Firestore with no
compute backend, and the analysis needs DDS + NumPy — so analysis runs on
the user's machine behind a tiny stdlib HTTP server (zero new
dependencies, zero recurring cost; DECISIONS.md §2.7):

    trainer analyze [--port 8765] [--reports-dir reports/analysis]

Endpoints:
    GET  /                  the analyze page (webui.py)
    POST /api/analyze       {dealer, vul, my_seat, my_hand, auction,
                             system, scoring, decision_indices, overrides,
                             narration?} -> per-decision-point reports
    GET  /reports/<name>    saved report files (html/pdf/json)
"""
from __future__ import annotations

import json
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .llm_narrator import llm_narrate
from .pdf import export_pdf
from .pipeline import AnalysisRequest, run_analysis
from .report import build_facts, facts_to_json, narrate_all, render_report
from .webui import analyze_page

_MAX_BODY = 1 << 20   # 1 MB is far beyond any legitimate request


def analyze_decision_points(payload: dict, reports_dir: Path) -> list[dict]:
    """Run one analysis per requested decision point; write html/json/pdf."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    indices = (payload.get("decision_indices")
               or [payload.get("decision_index",
                               len(payload.get("auction", [])))])
    overrides = {int(k): v for k, v in (payload.get("overrides") or {}).items()}
    narration = payload.get("narration", "template")
    out = []
    for idx in indices:
        req = AnalysisRequest(
            dealer=payload["dealer"], vul=payload["vul"],
            my_seat=payload["my_seat"], my_hand=payload["my_hand"],
            auction=list(payload["auction"]), decision_index=int(idx),
            system=payload.get("system", "two_over_one"),
            scoring=payload.get("scoring", "IMP"),
            candidates=payload.get("candidates"),
            overrides=overrides,
            seed=int(payload.get("seed", 1)),
            max_deals=int(payload.get("max_deals", 2000)),
        )
        result = run_analysis(req)
        facts = build_facts(result)
        prose = llm_narrate(facts) if narration == "llm" else narrate_all(facts)
        html_doc = render_report(facts, prose)

        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = f"{stamp}-dp{idx + 1}"
        html_path = reports_dir / f"{base}.html"
        html_path.write_text(html_doc, encoding="utf-8")
        (reports_dir / f"{base}.json").write_text(
            facts_to_json(facts), encoding="utf-8")
        pdf_path = export_pdf(html_path, reports_dir / f"{base}.pdf")

        out.append({
            "decision_index": int(idx),
            "actual": result.actual_call,
            "recommended": result.recommended,
            "n_deals": result.n_deals,
            "html_url": f"/reports/{base}.html",
            "json_url": f"/reports/{base}.json",
            "pdf_url": f"/reports/{base}.pdf" if pdf_path else None,
            "narrator": prose.get("narrator", "template"),
        })
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "BridgeTrainerAnalyze/1.0"
    reports_dir: Path = Path("reports/analysis")

    # -- helpers ---------------------------------------------------------
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def log_message(self, fmt, *args):   # quieter default logging
        print(f"[analyze] {self.address_string()} {fmt % args}")

    # -- routes ----------------------------------------------------------
    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, analyze_page().encode(),
                       "text/html; charset=utf-8")
            return
        if self.path == "/assets/bt-analyze-ui.js":
            from importlib import resources
            src = (resources.files("bridge_trainer") / "web"
                   / "bt-analyze-ui.js").read_text(encoding="utf-8")
            self._send(200, src.encode(),
                       "text/javascript; charset=utf-8")
            return
        if self.path.startswith("/reports/"):
            name = Path(self.path[len("/reports/"):]).name  # no traversal
            f = (self.reports_dir / name)
            if f.is_file():
                ctype = {"html": "text/html; charset=utf-8",
                         "pdf": "application/pdf",
                         "json": "application/json; charset=utf-8"}.get(
                    f.suffix.lstrip("."), "application/octet-stream")
                self._send(200, f.read_bytes(), ctype)
                return
        self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:
        if self.path != "/api/analyze":
            self._json(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not (0 < length <= _MAX_BODY):
                raise ValueError("bad request size")
            payload = json.loads(self.rfile.read(length))
            reports = analyze_decision_points(payload, self.reports_dir)
            self._json(200, {"ok": True, "reports": reports})
        except Exception as e:                      # surface to the UI
            traceback.print_exc()
            self._json(400, {"ok": False, "error": str(e)})


def serve(port: int = 8765, reports_dir: str | Path = "reports/analysis",
          open_browser: bool = True) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,),
                   {"reports_dir": Path(reports_dir)})
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    print(f"analysis UI: http://127.0.0.1:{port}/  (Ctrl-C to stop)")
    if open_browser:
        import webbrowser
        threading.Timer(
            0.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    return httpd


def main(port: int = 8765,
         reports_dir: str | Path = "reports/analysis") -> None:
    httpd = serve(port, reports_dir)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
