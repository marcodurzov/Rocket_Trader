# Tutorial: desplegar Rocket Trader en Oracle Cloud (gratis)

**Para:** Marco · **Versión:** 2026-11-23 · **Modo:** Paper / solo observación (no envía órdenes; LIVE bloqueado)
**Tiempo estimado:** 60–90 minutos (más la espera de activación de la cuenta Oracle)

Este procedimiento se ensayó completo en máquinas ARM iguales a las de Oracle (corridas 45222927425 y siguientes). Si algo no coincide con lo que ves en pantalla, detente y copia el mensaje exacto.

---

## Parte 0 — Antes de empezar

| Necesitas | Para qué | Anotaciones |
|---|---|---|
| Celular y tarjeta | Verificación de identidad de Oracle | Oracle puede hacer un cargo temporal de verificación; no cobra mientras no actualices la cuenta |
| Tus llaves **Paper** de Alpaca (Key ID y Secret) | Que el sistema lea tu cuenta Paper | Ver Parte 0.1 |
| Navegador en computadora | Todo se hace desde la consola web de Oracle | No necesitas instalar nada en tu PC |

### 0.1 Llaves Paper de Alpaca
1. Entra a https://app.alpaca.markets y cambia a la cuenta **Paper** (selector arriba a la izquierda).
2. En la página principal, en el panel **API Keys**, verás tu **Key ID**. El **Secret** solo se muestra una vez al generarlo.
3. Si **tienes guardado** el Secret: úsalo y salta al paso 5.
4. Si **no lo tienes**: pulsa **Regenerate**/**Generate New Keys** y copia ambos valores a un lugar seguro. **Importante:** regenerar invalida las llaves anteriores, así que también debes actualizarlas en GitHub:
   - github.com/marcodurzov/Rocket_Trader → **Settings → Secrets and variables → Actions**.
   - En `ALPACA_API_KEY` pulsa el lápiz → pega el nuevo Key ID → **Update secret**.
   - En `ALPACA_SECRET_KEY` igual con el nuevo Secret.
5. Nunca pegues estas llaves en el chat ni en el repositorio.

---

## Parte 1 — Crear la cuenta de Oracle Cloud
1. Ve a https://www.oracle.com/cloud/free/ → **Start for free**.
2. País: **Mexico**. Nombre, correo → verifica el correo con el enlace que te llega.
3. Contraseña y **Cloud Account Name** (ej. `rockettrader`).
4. **Home Region:** elige **Mexico Central (Querétaro)**. ⚠️ No se puede cambiar después y las máquinas gratuitas solo existen en esa región.
5. Dirección, teléfono y tarjeta para verificación → **Start my free trial**.
6. Espera el correo "Your account is ready" (minutos u horas).

---

## Parte 2 — Crear la máquina virtual
1. Entra a https://cloud.oracle.com con tu cuenta.
2. Menú ☰ (arriba a la izquierda) → **Compute → Instances** → **Create instance**.
3. **Name:** `rocket-trader`.
4. **Image and shape → Edit:**
   - **Change image** → **Ubuntu** → **Canonical Ubuntu 24.04** → **Select image**.
   - **Change shape** → **Ampere** → **VM.Standard.A1.Flex** → **OCPUs: 2**, **Memory: 8 GB** → **Select shape**.
   - Confirma que aparece la etiqueta **Always Free-eligible**. Si no aparece, no continúes.
5. **Networking:** deja "Create new virtual cloud network" y **Assign a public IPv4 address = Yes**.
6. **Add SSH keys:** elige **Generate a key pair for me** → **Save private key**. Guarda ese archivo (`ssh-key-….key`): es la llave para entrar a la máquina. No lo compartas.
7. **Boot volume:** deja el tamaño por defecto (≈47–50 GB).
8. **Create**. Espera a que el estado diga **Running** y copia la **Public IP address**.
   - Si sale **"Out of capacity"**: es falta temporal de máquinas gratis en la región. Reintenta más tarde (otro día u otra hora). No actualices la cuenta para resolverlo sin avisarme.

---

## Parte 3 — Conectarte a la máquina (desde el navegador)
1. En la consola de Oracle, arriba a la derecha, abre **Developer tools (icono `>_`) → Cloud Shell**. Espera a que aparezca la terminal abajo.
2. En la barra de Cloud Shell, menú ⚙️ → **Upload** → elige tu archivo `ssh-key-….key`.
3. Escribe (cambia `IP` por tu IP pública):
   ```bash
   chmod 600 ssh-key-*.key
   ssh -i ssh-key-*.key ubuntu@IP
   ```
4. Si pregunta `Are you sure you want to continue connecting`, escribe `yes`. Verás un prompt como `ubuntu@rocket-trader:~$`.

---

## Parte 4 — Instalar Rocket Trader
Copia y pega **una línea a la vez**:

1. Descargar el sistema:
   ```bash
   git clone https://github.com/marcodurzov/Rocket_Trader.git && cd Rocket_Trader
   ```
2. Instalar Docker (≈3–5 min):
   ```bash
   deploy/rocket_trader_deploy.sh install
   ```
3. Al terminar escribe `exit`, vuelve a conectarte (Parte 3, paso 3) y entra a la carpeta:
   ```bash
   cd Rocket_Trader
   ```
4. Guardar tus llaves Paper (no se verán al pegar el Secret; es normal):
   ```bash
   deploy/rocket_trader_deploy.sh init-env
   ```
5. Génesis contable (crea los libros con MXN 1,000; verifica que la cuenta Paper no tenga posiciones ni órdenes abiertas):
   ```bash
   deploy/rocket_trader_deploy.sh genesis
   ```
   Debe terminar con `Genesis complete.` Si dice `GENESIS REFUSED`, copia el mensaje y mándamelo.
6. Arrancar los 6 servicios (la primera vez tarda ≈10 min compilando):
   ```bash
   deploy/rocket_trader_deploy.sh up
   ```
7. Espera 5 minutos y revisa:
   ```bash
   deploy/rocket_trader_deploy.sh status
   ```
8. Cuando `rocket-trader-alpaca-activity-sse` diga `healthy`, crea el ancla de efectivo y activa la conciliación completa:
   ```bash
   deploy/rocket_trader_deploy.sh anchor
   deploy/rocket_trader_deploy.sh enable-cash-ledger
   ```

---

## Parte 5 — Respaldo diario automático
1. Escribe `crontab -e`. Si pregunta editor, elige **1** (nano).
2. Baja al final y pega esta línea:
   ```
   17 3 * * * cd /home/ubuntu/Rocket_Trader && deploy/rocket_trader_deploy.sh backup >> /home/ubuntu/backup.log 2>&1
   ```
3. Guarda con **Ctrl+O**, **Enter**, y sal con **Ctrl+X**.
4. Prueba manual una vez:
   ```bash
   deploy/rocket_trader_deploy.sh backup && deploy/rocket_trader_deploy.sh restore-test
   ```

---

## Parte 6 — Qué mandarme
- La salida de `deploy/rocket_trader_deploy.sh status` (copiar y pegar).
- Cualquier mensaje de error completo.
- **Nunca** el contenido de `.env` ni tus llaves.

Puedes cerrar el navegador: los servicios siguen corriendo en la máquina y se reinician solos si la máquina se reinicia.

---

## Riesgos conocidos y qué hacer

| Riesgo | Qué significa | Qué hacer |
|---|---|---|
| Recuperación por inactividad | Oracle puede detener/borrar máquinas gratis que parezcan inactivas 7 días (CPU, red y memoria muy bajas) | Si llega un correo de Oracle sobre "idle", avísame. La opción documentada es actualizar a **Pay As You Go** (el uso Always Free sigue sin costo). Nunca generar carga artificial |
| Sin capacidad | "Out of capacity" al crear la máquina | Reintentar otro día/hora |
| GDELT en "unhealthy" | La fuente de noticias GDELT limita solicitudes | Esperado en algunos entornos; no afecta la seguridad |
| `rocket-trader-paper-observer` en "unhealthy" antes del paso 4.8 | Por diseño, no se declara sano hasta tener la conciliación completa | Completa el paso 4.8 y espera ~15 min |
