# =============================================================
# DROPNODE MX — navegador.py  (v1.0)
# Un solo lugar para abrir Chromium "como una persona":
#   - User-Agent y cabeceras sec-ch-ua coherentes con la versión REAL de Chromium
#     (un UA de Chrome/124 en un Chromium nuevo delata al bot)
#   - sin la marca de automatización (navigator.webdriver, plugins, idiomas)
#   - proxy opcional (PROXY_URL=http://usuario:clave@host:puerto)
# Usado por github_scraper_ml.py, scraper_multi.py y diagnostico.py
# =============================================================
import os, logging
from urllib.parse import urlparse, unquote

logger = logging.getLogger(__name__)

INIT_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = window.chrome || {runtime: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['es-MX', 'es', 'en-US']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
"""


def proxy_cfg():
    """PROXY_URL -> dict para Playwright, o None."""
    p = os.environ.get("PROXY_URL", "").strip()
    if not p:
        return None
    u = urlparse(p)
    if not u.hostname:
        return None
    cfg = {"server": f"{u.scheme or 'http'}://{u.hostname}:{u.port or 80}"}
    if u.username:
        cfg["username"] = unquote(u.username)
        cfg["password"] = unquote(u.password or "")
    return cfg


def lanzar(pw, proxy=None, ahorrar_datos=False):
    """(browser, page) listos. `proxy` = dict de proxy_cfg(). `ahorrar_datos` evita bajar imágenes/video/fuentes."""
    kw = dict(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
                                   "--disable-gpu", "--disable-blink-features=AutomationControlled"])
    if proxy:
        kw["proxy"] = proxy
    browser = pw.chromium.launch(**kw)
    try:
        mayor = str(browser.version).split(".")[0]
    except Exception:
        mayor = "131"
    ua = (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          f"Chrome/{mayor}.0.0.0 Safari/537.36")
    ctx = browser.new_context(
        user_agent=ua, locale="es-MX", timezone_id="America/Mexico_City",
        viewport={"width": 1366, "height": 800},
        extra_http_headers={
            "Accept-Language": "es-MX,es;q=0.9,en;q=0.7",
            "sec-ch-ua": f'"Chromium";v="{mayor}", "Not A(Brand";v="24", "Google Chrome";v="{mayor}"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        })
    ctx.add_init_script(INIT_JS)
    page = ctx.new_page()
    if ahorrar_datos or proxy:
        try:
            page.route("**/*", lambda route: route.abort()
                       if route.request.resource_type in ("image", "media", "font") else route.continue_())
        except Exception:
            pass
    return browser, page
