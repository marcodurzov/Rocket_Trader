# Rocket_Trader
Trading MDV PS

Rocket Trader

Bot de trading algorítmico autónomo, inicialmente para acciones de EE.UU. mediante Alpaca.

Arquitectura inicial

• rocket_trader_core.py: seguridad, riesgo, decisión, benchmark y ejecución desacoplada.
• data/: auditoría y datos generados localmente; no contiene credenciales.
• tests/: pruebas del sistema.
• requirements.txt: dependencias Python.
• .env.example: variables de entorno de ejemplo.

Reglas iniciales

• Mercado inicial: acciones/ETFs de EE.UU. vía Alpaca.
• Ejecución: PAPER.
• LIVE bloqueado explícitamente.
• LONG-only.
• CASH-only; no se usa buying power de margen para dimensionar posiciones.
• Stop-loss obligatorio.
• Take-profit obligatorio.
• Kill-switch automático.
• Benchmark contra precedentes de traders exitosos.
• Si no hay precedente suficiente: escenario NOVEL y presupuesto de riesgo reducido.
• Distribución mensual de utilidad: 10% reserva / 70% reinversión / 20% flujo personal.

Seguridad

No guardar API keys en Git. Usar variables de entorno o un secret manager.