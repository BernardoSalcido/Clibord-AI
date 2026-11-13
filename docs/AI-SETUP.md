# IA local con LM Studio (Bionic)

Clipboard AI usa la **Local API** de LM Studio/Bionic en el ordenador que actúa
como cerebro. El modelo se descarga y configura en LM Studio; la app puede
solicitar su carga y calentamiento al iniciar. Los prompts de Imagen → Texto,
corrección media y corrección alta están en Clipboard AI y se envían en cada
petición. No hay que fijar un prompt global de transcripción en Bionic.

## Configuración probada en Windows

Equipo de prueba: **NVIDIA RTX 4070 Laptop GPU, 8 GB de VRAM**. Modelo:
`qwen/qwen3.5-9b`, cuantización **Q4_K_M**.

| Ajuste de modelo en Bionic | Valor observado |
| --- | ---: |
| Automatic Optimize Based on Hardware | Desactivado |
| Context Length | 15 000 tokens |
| GPU Offload | 32 |
| CPU Thread Pool Size | 5 |
| Evaluation Batch Size | 512 |
| Physical Batch Size | 128 |
| Max Concurrent Predictions | 1 |
| Flash Attention | Activado |

Son los ajustes de **una prueba**, no garantías de velocidad, memoria o
precisión para otras GPU. En la captura Bionic muestra que el modelo admite
hasta 262 144 tokens, pero el valor **cargado** era 15 000.

**Contexto separado en Clipboard AI:** en **Ajustes → IA local**, Clipboard AI
tiene su propio valor «Contexto al cargar» (2048 por defecto). Si la app carga
el modelo, envía ese valor a la API; por tanto, el valor 15 000 de la captura
no se aplica automáticamente. Para reproducir la prueba, pon **15 000** también
en Clipboard AI y comprueba el uso real de VRAM. Aumentar el contexto puede
elevar el consumo de memoria y reducir la velocidad.

## Primer uso

1. Instala LM Studio/Bionic y descarga un modelo con capacidad de visión.
2. Activa **Local API** en Bionic. Comprueba la dirección local real; en el
   equipo de prueba se usó `http://127.0.0.1:1235`.
3. En Clipboard AI abre **Ajustes → IA local**, selecciona la dirección, el
   modelo y el contexto, y pulsa **Guardar**. Activa la carga al inicio si
   quieres evitar el primer arranque lento.
4. Prueba Imagen → Texto y revisa la transcripción antes de reutilizarla. La
   corrección media hace una pasada ortográfica; la alta usa razonamiento.

El endpoint de la API debe ser local al cerebro. Los clientes móviles hablan
con el cerebro de Clipboard AI; no necesitan acceso directo a Bionic. Si la
API requiere un token, configura `CLIPBOARD_AI_API_TOKEN` en el entorno del
cerebro. Ese token no se guarda en `ai.json`.
