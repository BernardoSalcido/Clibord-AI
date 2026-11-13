package org.clipboardai.app

import android.app.Activity
import android.app.AlertDialog
import android.app.StatusBarManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.ComponentName
import android.content.ServiceConnection
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.Icon
import android.os.Bundle
import android.os.IBinder
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File
import android.view.WindowInsets
import android.view.View
import android.view.DragEvent
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.CaptureActivity
import org.json.JSONObject
import android.util.LruCache
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private var dock: DockService? = null
    private var bound = false
    private val pendingActions = mutableListOf<(DockService) -> Unit>()
    private val observer: (String) -> Unit = { status ->
        if (!isDestroyed) { lastStatus = status; state.text = status; refresh() }
    }
    private val serviceBinding = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            if (!bound) return
            val service = (binder as DockService.LocalBinder).service
            dock = service
            service.observe(observer)
            if (!service.keepingConnection && getSharedPreferences("background", MODE_PRIVATE).getBoolean("enabled", false))
                startConnection()
            val actions = pendingActions.toList(); pendingActions.clear()
            actions.forEach { it(service) }
        }
        override fun onServiceDisconnected(name: ComponentName) {
            dock?.removeObserver(observer); dock = null
            state.text = "Recuperando conexión…"
        }
    }
    private lateinit var state: TextView
    private lateinit var deviceNames: TextView
    private lateinit var list: LinearLayout
    private lateinit var input: EditText
    private lateinit var composePanel: LinearLayout
    private lateinit var compactPanel: LinearLayout
    private lateinit var detailsPanel: LinearLayout
    private lateinit var actionsPanel: LinearLayout
    private lateinit var actionsScroll: ScrollView
    private lateinit var imageToggle: CheckBox
    private lateinit var screenshotToggle: CheckBox
    private lateinit var textModes: RadioGroup
    private lateinit var clearTextsButton: Button
    private var updatingSettings = false
    private var category = "text"
    private var lastStatus = ""
    private var exportId: String? = null
    private var refreshGeneration = 0
    private val thumbnails = object : LruCache<String, Bitmap>(8 * 1024 * 1024) {
        override fun sizeOf(key: String, value: Bitmap) = value.byteCount
    }
    private val thumbnailWorker = Executors.newFixedThreadPool(2)
    private val categoryButtons = mutableMapOf<String, Button>()
    private val themePrefs by lazy { getSharedPreferences("appearance", MODE_PRIVATE) }
    private val darkMode get() = themePrefs.getBoolean("dark", false)
    private val accentColor get() = if (darkMode) Color.rgb(17, 183, 197) else Color.rgb(40, 105, 131)
    private val foregroundColor get() = if (darkMode) Color.rgb(198, 206, 239) else Color.rgb(87, 82, 121)
    private fun tr(es: String, en: String) = if (resources.configuration.locales[0].language == "es") es else en

    override fun onCreate(savedInstanceState: Bundle?) {
        if (darkMode) setTheme(android.R.style.Theme_Material_NoActionBar)
        super.onCreate(savedInstanceState)
        if (lastStatus.isEmpty()) lastStatus = tr("Desconectado", "Disconnected")
        window.statusBarColor = if (darkMode) Color.rgb(41, 44, 60) else Color.rgb(230, 219, 209)
        window.navigationBarColor = if (darkMode) Color.rgb(41, 44, 60) else Color.rgb(230, 219, 209)
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(12), dp(18), dp(12))
            setBackgroundColor(if (darkMode) Color.rgb(48, 52, 70) else Color.rgb(238, 230, 221))
        }
        if (android.os.Build.VERSION.SDK_INT >= 30) {
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                view.setPadding(dp(18) + bars.left, dp(12) + bars.top, dp(18) + bars.right, dp(12) + bars.bottom)
                insets
            }
        }
        setContentView(root)
        if (resources.getBoolean(R.bool.accept_external_drops)) {
            root.setOnDragListener { _, event -> handleExternalDrop(event) }
        }
        val header = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
        }
        header.addView(TextView(this).apply {
            setText(R.string.app_name); textSize = 22f; setTextColor(foregroundColor)
            gravity = android.view.Gravity.CENTER_VERTICAL
        }, LinearLayout.LayoutParams(0, -1, 1f))
        header.addView(button(tr("⚙ Ajustes", "⚙ Settings")) { settingsDialog() },
            LinearLayout.LayoutParams(-2, dp(48)))
        root.addView(header, LinearLayout.LayoutParams(-1, dp(56)))
        val statusCard = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dp(16), dp(12), dp(16), dp(12))
            background = cardBackground()
        }
        state = TextView(this).apply { text = lastStatus; textSize = 16f; setTextColor(foregroundColor) }
        statusCard.addView(state)
        deviceNames = TextView(this).apply { text = tr("Cerebro sin conexión", "Brain disconnected"); textSize = 13f }
        statusCard.addView(deviceNames)
        root.addView(statusCard, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dp(8) })
        compactPanel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        root.addView(compactPanel)
        compactPanel.addView(TextView(this).apply {
            text = tr("Envía contenido al dock", "Send content to the dock"); textSize = 17f; setPadding(0, dp(20), 0, dp(6))
        })
        compactPanel.addView(button(tr("↗ Enviar portapapeles", "↗ Send clipboard")) { sendClipboard() }.apply {
            background = GradientDrawable().apply { setColor(accentColor); cornerRadius = dp(14).toFloat() }
            setTextColor(Color.WHITE)
        })
        compactPanel.addView(button(tr("＋ Añadir", "＋ Add")) { addDialog() })
        if (resources.getBoolean(R.bool.accept_external_drops)) compactPanel.addView(TextView(this).apply {
            text = tr("También puedes arrastrar aquí recortes y textos desde SuperHub", "You can also drag snippets and text here from SuperHub")
            textSize = 14f; setPadding(dp(8), dp(12), dp(8), dp(12))
        })
        composePanel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        input = EditText(this).apply {
            hint = tr("Pega o escribe el texto que quieres enviar", "Paste or type text to send")
            minLines = 2; maxLines = 4; setTextSize(16f)
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
        }
        composePanel.addView(input)
        val draft = savedInstanceState?.getString("draft") ?: getPreferences(MODE_PRIVATE).getString("draft", "")
        exportId = savedInstanceState?.getString("exportId")
        input.setText(draft)
        composePanel.addView(button(tr("Enviar texto", "Send text")) {
            val sent = input.text.toString()
            withDock { service -> service.connection.publish(sent) { success ->
                if (!isDestroyed && success && input.text.toString() == sent) { input.setText(""); composePanel.visibility = View.GONE }
            } }
        })
        compactPanel.addView(composePanel)
        val expansion = LinearLayout(this)
        lateinit var detailsButton: Button
        val actionsButton = button(tr("⚡ Acciones", "⚡ Actions")) { }
        actionsButton.setOnClickListener {
            if (detailsPanel.visibility == View.VISIBLE) {
                detailsPanel.visibility = View.GONE; compactPanel.visibility = View.VISIBLE; detailsButton.text = tr("Abrir dock", "Open dock")
            }
            actionsScroll.visibility = if (actionsScroll.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            actionsButton.text = if (actionsScroll.visibility == View.VISIBLE) tr("Ocultar acciones", "Hide actions") else tr("⚡ Acciones", "⚡ Actions")
        }
        detailsButton = button(tr("Abrir dock", "Open dock")) { }
        detailsButton.setOnClickListener {
            val opening = detailsPanel.visibility != View.VISIBLE
            detailsPanel.visibility = if (opening) View.VISIBLE else View.GONE
            compactPanel.visibility = if (opening) View.GONE else View.VISIBLE
            actionsScroll.visibility = View.GONE
            actionsButton.text = tr("⚡ Acciones", "⚡ Actions")
            detailsButton.text = if (opening) tr("Cerrar dock", "Close dock") else tr("Abrir dock", "Open dock")
            if (opening) refresh()
        }
        expansion.addView(actionsButton, LinearLayout.LayoutParams(0, -2, 1f))
        expansion.addView(detailsButton, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(expansion)
        actionsPanel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        imageToggle = CheckBox(this).apply {
            text = tr("▧ Imagen → Texto", "▧ Image → Text")
            setOnCheckedChangeListener { _, enabled ->
                if (!updatingSettings) withDock { it.connection.updateShared(image = enabled) }
            }
        }
        actionsPanel.addView(imageToggle)
        screenshotToggle = CheckBox(this).apply {
            text = tr("Detectar capturas nuevas", "Detect new screenshots")
            isChecked = getSharedPreferences("screenshots", MODE_PRIVATE).getBoolean("enabled", false)
            setOnCheckedChangeListener { _, enabled ->
                if (enabled) enableScreenshots() else withDock { it.setScreenshotCapture(false) }
            }
        }
        actionsPanel.addView(screenshotToggle)
        actionsPanel.addView(TextView(this).apply { text = tr("Corrección automática · Medio: ortografía · Alto: gramática con thinking", "Auto correction · Medium: spelling · High: grammar with thinking") })
        textModes = RadioGroup(this).apply { orientation = RadioGroup.HORIZONTAL }
        listOf(tr("Nada", "Off"), tr("Medio", "Medium"), tr("Alto", "High")).forEachIndexed { index, label ->
            textModes.addView(RadioButton(this).apply { id = View.generateViewId(); text = label; tag = listOf("none", "spelling", "grammar")[index] })
        }
        textModes.setOnCheckedChangeListener { group, id ->
            if (!updatingSettings) {
                val mode = group.findViewById<RadioButton>(id)?.tag as? String ?: return@setOnCheckedChangeListener
                withDock { it.connection.updateShared(textMode = mode) }
            }
        }
        actionsPanel.addView(textModes)
        actionsPanel.addView(button(tr("⌨ Portapapeles → Teclado", "⌨ Clipboard → Keyboard")) { keyboardSetup() })
        actionsScroll = ScrollView(this).apply { addView(actionsPanel); visibility = View.GONE }
        root.addView(actionsScroll, LinearLayout.LayoutParams(-1, 0, 1f))
        detailsPanel = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; visibility = View.GONE }
        detailsPanel.addView(TextView(this).apply { text = tr("Tu dock", "Your dock"); textSize = 20f; setPadding(0, dp(12), 0, dp(6)) })
        val categories = LinearLayout(this)
        listOf(tr("Textos", "Text") to "text", tr("Imágenes", "Images") to "image", tr("Archivos", "Files") to "file").forEach { (label, value) ->
            categories.addView(button(label) { category = value; updateCategoryButtons(); refresh() }.also { categoryButtons[value] = it },
                LinearLayout.LayoutParams(0, -2, 1f))
        }
        detailsPanel.addView(categories)
        clearTextsButton = button(tr("Borrar todos los textos", "Delete all text")) { clearTextsDialog() }
        detailsPanel.addView(clearTextsButton)
        clearTextsButton.visibility = View.VISIBLE
        updateCategoryButtons()
        list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        detailsPanel.addView(ScrollView(this).apply { addView(list) }, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(detailsPanel, LinearLayout.LayoutParams(-1, 0, 1f))
        handleShare(intent)
    }
    private fun withDock(action: (DockService) -> Unit) {
        val service = dock
        if (service != null) action(service) else pendingActions.add(action)
    }
    private fun startConnection() {
        if (android.os.Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), NOTIFICATION_REQUEST)
        }
        // This action originates in a visible Activity. Notification permission is optional for the service.
        try { startForegroundService(Intent(this, DockService::class.java).setAction(DockService.CONNECT)) }
        catch (_: RuntimeException) { state.text = "No se pudo iniciar la conexión. Vuelve a pulsar Conectar con la app abierta." }
    }
    private fun addClipboardTile() {
        if (android.os.Build.VERSION.SDK_INT < 33) {
            state.text = "Desliza dos veces desde arriba, pulsa Editar y añade Enviar portapapeles."
            return
        }
        val manager = getSystemService(StatusBarManager::class.java)
        if (manager == null) { state.text = "Abre Ajustes rápidos y añade Enviar portapapeles desde Editar."; return }
        manager.requestAddTileService(ComponentName(this, SendClipboardTile::class.java),
            "Enviar al dock", Icon.createWithResource(this, R.drawable.ic_send_clipboard),
            mainExecutor) { result ->
            if (!isDestroyed) state.text = when (result) {
                StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED -> "Botón añadido a Ajustes rápidos"
                StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED -> "El botón ya está en Ajustes rápidos"
                else -> "Puedes añadir el botón desde Editar en Ajustes rápidos"
            }
        }
    }
    private fun screenshotPermission(): String = if (android.os.Build.VERSION.SDK_INT >= 33)
        android.Manifest.permission.READ_MEDIA_IMAGES else android.Manifest.permission.READ_EXTERNAL_STORAGE

    private fun enableScreenshots() {
        if (android.os.Build.VERSION.SDK_INT < 29) {
            state.text = "La detección automática requiere Android 10 o posterior"
            screenshotToggle.isChecked = false
            return
        }
        if (checkSelfPermission(screenshotPermission()) == PackageManager.PERMISSION_GRANTED) {
            withDock { it.setScreenshotCapture(true) }
            return
        }
        val permissions = if (android.os.Build.VERSION.SDK_INT >= 34)
            arrayOf(android.Manifest.permission.READ_MEDIA_IMAGES,
                android.Manifest.permission.READ_MEDIA_VISUAL_USER_SELECTED)
            else arrayOf(screenshotPermission())
        requestPermissions(permissions, SCREENSHOT_REQUEST)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, results: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, results)
        if (requestCode == SCREENSHOT_REQUEST) {
            val granted = checkSelfPermission(screenshotPermission()) == PackageManager.PERMISSION_GRANTED
            if (granted) withDock { it.setScreenshotCapture(true) }
            else {
                screenshotToggle.setOnCheckedChangeListener(null)
                screenshotToggle.isChecked = false
                screenshotToggle.setOnCheckedChangeListener { _, enabled ->
                    if (enabled) enableScreenshots() else withDock { it.setScreenshotCapture(false) }
                }
                state.text = "Para detectar capturas futuras, permite acceso a todas las imágenes. También puedes añadir una imagen manualmente."
            }
        }
    }
    private fun backgroundHelp() {
        val harmony = resources.getBoolean(R.bool.accept_external_drops)
        val explanation = if (harmony) tr(
            "En la MatePad abre Ajustes y busca «Inicio de aplicaciones». En Clipboard AI desactiva «Gestionar automáticamente» y activa «Inicio automático», «Inicio secundario» y «Ejecutar en segundo plano». Busca también «Optimización de batería» y permite que Clipboard AI funcione sin optimización. Mantén activa la notificación de conexión. Huawei puede suspender la red aun con la notificación visible; el dock reintentará conectar cuando la red vuelva.",
            "On the MatePad, open Settings and search for ‘App launch’. Disable ‘Manage automatically’ for Clipboard AI and enable ‘Auto-launch’, ‘Secondary launch’, and ‘Run in background’. Also search for ‘Battery optimization’ and allow Clipboard AI to run without optimization. Keep the connection notification enabled. Huawei may still suspend network access; the dock retries when the network returns.")
        else tr(
            "Pulsa Conectar para mantener el enlace al bloquear el móvil. Puedes detenerlo con Pausar, aquí o en la notificación. Mantener la conexión consume batería.\n\nPara recibir sin retrasos tras mucho tiempo de reposo, permite que Clipboard AI funcione sin optimización de batería. En OnePlus comprueba también que permite la actividad en segundo plano. Esta opción no permite leer automáticamente el portapapeles de otras apps.",
            "Tap Connect to keep the link active while the screen is locked. You can stop it with Pause here or in the notification. This uses battery.\n\nFor prompt delivery after long idle periods, allow Clipboard AI to run without battery optimization. On OnePlus also allow background activity. This does not enable automatic reading of other apps' clipboards.")
        AlertDialog.Builder(this).setTitle(tr("Conexión con pantalla apagada", "Connection with screen off"))
            .setMessage(explanation)
            .setPositiveButton(tr("Ajustes de batería", "Battery settings")) { _, _ ->
                try { startActivity(Intent(android.provider.Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) }
                catch (_: android.content.ActivityNotFoundException) {
                    startActivity(Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        android.net.Uri.parse("package:$packageName")))
                }
            }.setNegativeButton(tr("Cerrar", "Close"), null).show()
    }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun cardBackground() = GradientDrawable().apply {
        setColor(if (darkMode) Color.rgb(41, 44, 60) else Color.rgb(230, 219, 209)); cornerRadius = dp(14).toFloat()
        setStroke(dp(1), if (darkMode) Color.rgb(81, 86, 108) else Color.rgb(209, 201, 194))
    }
    private fun button(label: String, action: () -> Unit) = Button(this).apply {
        text = label; isAllCaps = false; setOnClickListener { action() }
        minHeight = dp(48); setTextColor(foregroundColor)
        background = GradientDrawable().apply {
            setColor(if (darkMode) Color.rgb(65, 69, 89) else Color.rgb(220, 211, 203)); cornerRadius = dp(14).toFloat()
        }
        setPadding(dp(12), dp(9), dp(12), dp(9))
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(6) }
    }
    private fun updateCategoryButtons() {
        categoryButtons.forEach { (value, control) ->
            control.alpha = if (value == category) 1f else 0.63f
            control.setTextColor(if (value == category) (if (darkMode) Color.rgb(126, 222, 222) else accentColor)
                else (if (darkMode) foregroundColor else Color.rgb(55, 65, 75)))
        }
        if (::clearTextsButton.isInitialized) clearTextsButton.visibility = if (category == "text") View.VISIBLE else View.GONE
    }
    private fun clearTextsDialog() {
        withDock { service -> service.connection.textUsage { count, pending ->
            if (isDestroyed) return@textUsage
            if (count == 0) { Toast.makeText(this, tr("No hay textos que borrar", "No text to delete"), Toast.LENGTH_SHORT).show(); return@textUsage }
            AlertDialog.Builder(this).setTitle(tr("Borrar todos los textos", "Delete all text"))
                .setMessage(tr("Se borrarán $count textos de este dispositivo, incluidos $pending pendientes. No se borrarán textos de otros dispositivos ni imágenes o archivos.",
                    "$count texts will be deleted from this device, including $pending pending. Text on other devices, images, and files will remain."))
                .setPositiveButton(tr("Borrar", "Delete")) { _, _ ->
                    service.connection.clearTexts { if (!isDestroyed) refresh() }
                }.setNegativeButton(tr("Cancelar", "Cancel"), null).show()
        } }
    }
    private fun settingsDialog() {
        val options = mutableListOf(tr("Vincular ordenador", "Pair computer"), tr("Conectar", "Connect"), tr("Pausar conexión", "Pause connection"), tr("Dirección del cerebro", "Brain address"),
            tr("Conexión con pantalla apagada", "Connection with screen off"), tr("Limpiar archivos entregados", "Clear delivered files"), tr("Apariencia", "Appearance"), tr("Prompts de IA", "AI prompts"), tr("Añadir botón rápido", "Add quick tile"), tr("Aplicar ajustes pendientes", "Apply pending settings"), tr("Diagnóstico de conexión", "Connection diagnostics"))
        AlertDialog.Builder(this).setTitle(tr("Ajustes y conexión", "Settings and connection"))
            .setItems(options.toTypedArray()) { _, option ->
                when (option) {
                    0 -> pairingDialog()
                    1 -> startConnection()
                    2 -> withDock { it.pause() }
                    3 -> endpointDialog()
                    4 -> backgroundHelp()
                    5 -> clearDeliveredDialog()
                    6 -> appearanceDialog()
                    7 -> promptDialog()
                    8 -> addClipboardTile()
                    9 -> withDock { it.connection.retrySharedSettings() }
                    10 -> connectionDiagnostics()
                }
            }.setNegativeButton(tr("Cerrar", "Close"), null).show()
    }
    private fun connectionDiagnostics() {
        withDock { service -> service.connection.textUsage { _, pending ->
            if (isDestroyed) return@textUsage
            val host = service.connection.endpoint().ifBlank { tr("Sin dirección guardada", "No saved address") }
            val lifecycle = getSharedPreferences("background", MODE_PRIVATE)
            val restartTime = lifecycle.getLong("last_unexpected_restart", 0L)
            val restart = if (restartTime > 0L)
                tr("Servicio reiniciado mientras la conexión estaba activada: ", "Service restarted while connection was enabled: ") +
                    java.text.DateFormat.getDateTimeInstance().format(java.util.Date(restartTime))
                else tr("Sin reinicio inesperado registrado", "No unexpected restart recorded")
            val report = tr("Cerebro: $host:${service.connection.endpointPort()}\nEstado: $lastStatus\nTextos pendientes: $pending\n\nComprueba que el cerebro siga encendido y que ambos dispositivos mantengan su conexión de red o VPN.",
                "Brain: $host:${service.connection.endpointPort()}\nStatus: $lastStatus\nPending texts: $pending\n\nCheck that the brain is still running and both devices remain connected to their network or VPN.")
            AlertDialog.Builder(this).setTitle(tr("Diagnóstico de conexión", "Connection diagnostics"))
                .setMessage("$report\n\n$restart")
                .setPositiveButton(tr("Cerrar", "Close"), null).show()
        } }
    }
    private fun appearanceDialog() {
        AlertDialog.Builder(this).setTitle(tr("Apariencia", "Appearance"))
            .setSingleChoiceItems(arrayOf(tr("Paper Claro", "Paper Light"), tr("Paper Nocturno", "Paper Night")), if (darkMode) 1 else 0) { dialog, choice ->
                themePrefs.edit().putBoolean("dark", choice == 1).apply()
                dialog.dismiss(); recreate()
            }.show()
    }
    private fun keyboardSetup() {
        AlertDialog.Builder(this).setTitle(tr("Portapapeles → Teclado", "Clipboard → Keyboard"))
            .setMessage(tr("Activa el teclado Clipboard AI en los ajustes del sistema. Selecciónalo al escribir y toca «Escribir portapapeles». Solo escribe el texto cuando tú lo pulses.",
                "Enable the Clipboard AI keyboard in system settings. Select it while typing and tap ‘Type clipboard’. Text is entered only when you tap it."))
            .setPositiveButton(tr("Activar teclado", "Enable keyboard")) { _, _ -> startActivity(Intent(android.provider.Settings.ACTION_INPUT_METHOD_SETTINGS)) }
            .setNeutralButton(tr("Elegir teclado", "Choose keyboard")) { _, _ ->
                (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).showInputMethodPicker()
            }.setNegativeButton(tr("Cerrar", "Close"), null).show()
    }
    private fun clearDeliveredDialog() {
        withDock { service -> service.connection.deliveredUsage { count, bytes ->
            if (!isDestroyed) AlertDialog.Builder(this).setTitle(tr("Limpiar el dock", "Clear dock"))
                .setMessage(tr("Se borrarán $count copias locales ($bytes bytes). Los originales y las copias guardadas fuera del dock se conservarán.",
                    "$count local copies ($bytes bytes) will be removed. Originals and copies saved outside the dock will remain."))
                .setPositiveButton(tr("Borrar copias", "Remove copies")) { _, _ -> service.connection.clearDelivered() }
                .setNegativeButton(tr("Cancelar", "Cancel"), null).show()
        } }
    }
    private fun addDialog() {
        AlertDialog.Builder(this).setTitle(tr("Añadir al dock", "Add to dock"))
            .setItems(arrayOf(tr("Imágenes", "Images"), tr("Archivos", "Files"), tr("Escribir texto", "Write text"))) { _, option ->
                when (option) {
                    0 -> chooseImages()
                    1 -> startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE).setType("*/*")
                        .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true), FILE_REQUEST)
                    2 -> { composePanel.visibility = View.VISIBLE; input.requestFocus() }
                }
            }.show()
    }
    private fun chooseImages() {
        val picker = if (android.os.Build.VERSION.SDK_INT >= 33) {
            Intent(android.provider.MediaStore.ACTION_PICK_IMAGES).setType("image/*")
                .putExtra(android.provider.MediaStore.EXTRA_PICK_IMAGES_MAX,
                    minOf(MAX_BATCH, android.provider.MediaStore.getPickImagesMaxLimit()))
        } else Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
            .setType("image/*").putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
        startActivityForResult(picker, FILE_REQUEST)
    }
    private fun sendClipboard() {
        val clip = getSystemService(ClipboardManager::class.java).primaryClip
        val uris = clipboardUris(clip)
        if (uris.isNotEmpty()) importFiles(uris)
        else when (val content = clipboardContent(clip)) {
            is ClipboardContent.Text -> withDock { it.connection.publish(content.value) { } }
            is ClipboardContent.File -> importFiles(listOf(content.uri))
            null -> state.text = tr("No hay texto, imagen o archivo disponible en el portapapeles", "No text, image, or file is available on the clipboard")
        }
    }
    private fun pairingDialog() {
        AlertDialog.Builder(this).setTitle(tr("Vincular ordenador", "Pair computer"))
            .setItems(arrayOf(tr("Escanear QR", "Scan QR"), tr("Pegar bloque completo", "Paste full block"), tr("Introducir datos", "Enter details"))) { _, choice ->
                when (choice) {
                    0 -> try {
                        startActivityForResult(Intent(this, CaptureActivity::class.java)
                            .setAction(Intents.Scan.ACTION)
                            .putExtra(Intents.Scan.FORMATS, "QR_CODE")
                            .putExtra(Intents.Scan.PROMPT_MESSAGE, getString(R.string.scanner_hint))
                            .putExtra(Intents.Scan.ORIENTATION_LOCKED, false)
                            .putExtra(Intents.Scan.BEEP_ENABLED, false), SCANNER_REQUEST)
                    } catch (_: RuntimeException) { scannerError(getString(R.string.scanner_camera_error)) }
                    1 -> pastePairingDialog()
                    2 -> manualPairingDialog()
                }
            }.setNegativeButton(tr("Cancelar", "Cancel"), null).show()
    }
    private fun endpointDialog() {
        val fields = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
        val host = EditText(this).apply { hint = tr("IP o nombre privado del cerebro", "Brain IP or private name"); setText(dock?.connection?.endpoint().orEmpty()) }
        val port = EditText(this).apply {
            hint = tr("Puerto", "Port"); inputType = android.text.InputType.TYPE_CLASS_NUMBER
            setText((dock?.connection?.endpointPort() ?: 45821).toString())
        }
        fields.addView(host); fields.addView(port)
        val dialog = AlertDialog.Builder(this).setTitle(tr("Dirección del cerebro", "Brain address"))
            .setMessage(tr("Puedes usar la dirección privada de Tailscale. La identidad TLS ya vinculada se seguirá comprobando.", "You can use a private Tailscale address. The paired TLS identity will still be verified."))
            .setView(fields).setNegativeButton(tr("Cancelar", "Cancel"), null).setPositiveButton(tr("Guardar", "Save"), null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val (address, number) = PairingData.endpoint(host.text.toString(), port.text.toString())
                    withDock { it.connection.changeEndpoint(address, number) }
                    dialog.dismiss()
                } catch (e: IllegalArgumentException) { host.error = e.message }
            }
        }
        dialog.show()
    }
    private fun promptDialog() {
        withDock { service -> service.connection.sharedPrompts { prompts ->
            if (isDestroyed) return@sharedPrompts
            val fields = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
            val editors = listOf("image" to tr("Imagen → Texto", "Image → Text"), "spelling" to tr("Medio · Ortografía", "Medium · Spelling"),
                "grammar" to tr("Alto · Gramática", "High · Grammar")).associate { (key, label) ->
                fields.addView(TextView(this).apply { text = label })
                key to EditText(this).apply {
                    setText(prompts.optString(key)); minLines = 3; maxLines = 8
                    inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
                    fields.addView(this)
                }
            }
            val dialog = AlertDialog.Builder(this).setTitle(tr("Prompts compartidos", "Shared prompts"))
                .setMessage(tr("El cerebro usará estos textos al procesar cada función.", "The brain uses these prompts for each action."))
                .setView(ScrollView(this).apply { addView(fields) })
                .setNegativeButton(tr("Cancelar", "Cancel"), null).setPositiveButton(tr("Guardar", "Save"), null).create()
            dialog.setOnShowListener {
                dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                    val values = JSONObject()
                    val invalid = editors.values.firstOrNull { it.text.isBlank() || it.text.length > 8192 }
                    if (invalid != null) { invalid.error = tr("Introduce entre 1 y 8192 caracteres", "Enter 1 to 8192 characters"); return@setOnClickListener }
                    editors.forEach { (key, editor) -> values.put(key, editor.text.toString()) }
                    service.connection.updateShared(prompts = values)
                    dialog.dismiss()
                }
            }
            dialog.show()
        } }
    }
    private fun pastePairingDialog() {
        val data = EditText(this).apply {
            hint = tr("Bloque completo: desde { hasta }", "Full block: from { to }")
            minLines = 4; maxLines = 8
            inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_MULTI_LINE
        }
        val dialog = AlertDialog.Builder(this).setTitle(tr("Pegar bloque completo", "Paste full block"))
            .setMessage(tr("En Windows escribe pair. Copia todo el bloque: incluye dirección, puerto, huella y código. Pegar solo el valor de code no permite conectar.",
                "On Windows, type pair. Copy the entire block including address, port, fingerprint, and code. The code alone cannot pair the device."))
            .setView(data).setNegativeButton(tr("Cancelar", "Cancel"), null)
            .setPositiveButton(tr("Vincular", "Pair"), null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val pairing = PairingData.parse(data.text.toString())
                    withDock { it.pair(pairing) }; dialog.dismiss()
                }
                catch (e: IllegalArgumentException) { data.error = e.message }
            }
        }
        dialog.show()
    }
    private fun manualPairingDialog() {
        val fields = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), 0, dp(18), 0) }
        fun field(hint: String, initial: String = "", lines: Int = 1): EditText {
            val view = EditText(this).apply {
                this.hint = hint; setText(initial); minLines = lines; maxLines = lines + 1
                inputType = android.text.InputType.TYPE_CLASS_TEXT or android.text.InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            }
            fields.addView(view); return view
        }
        val host = field(tr("Dirección IP del ordenador", "Computer IP address"))
        val port = field(tr("Puerto", "Port"), "45821")
        val fingerprint = field(tr("Huella de seguridad · 64 caracteres", "Security fingerprint · 64 characters"), lines = 2)
        val code = field(tr("Código temporal", "Temporary code"))
        val error = TextView(this).apply { setTextColor(Color.rgb(170, 30, 30)) }
        fields.addView(error)
        val dialog = AlertDialog.Builder(this).setTitle(tr("Introducir datos", "Enter details"))
            .setMessage(tr("Los cuatro datos aparecen en la página del QR del ordenador. Genera un código nuevo con pair si han pasado más de cinco minutos.",
                "All four details appear on the computer's QR page. Generate a new code with pair if more than five minutes have passed."))
            .setView(ScrollView(this).apply { addView(fields) })
            .setNegativeButton(tr("Cancelar", "Cancel"), null).setPositiveButton(tr("Vincular", "Pair"), null).create()
        dialog.setOnShowListener {
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener {
                try {
                    val pairing = PairingData.fields(host.text.toString(), port.text.toString(), fingerprint.text.toString(), code.text.toString())
                    withDock { it.pair(pairing) }
                    dialog.dismiss()
                } catch (e: IllegalArgumentException) { error.text = e.message }
            }
        }
        dialog.show()
    }
    private fun scannerError(message: String) {
        AlertDialog.Builder(this).setTitle(tr("Vincular sin cámara", "Pair without camera")).setMessage(message)
            .setPositiveButton(tr("Pegar bloque", "Paste block")) { _, _ -> pastePairingDialog() }
            .setNeutralButton(tr("Introducir datos", "Enter details")) { _, _ -> manualPairingDialog() }
            .setNegativeButton(tr("Cerrar", "Close"), null).show()
    }
    @Deprecated("Native Activity result callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode == FILE_REQUEST && resultCode == RESULT_OK) {
            importFiles(incomingUris(data))
        } else if (requestCode == EXPORT_REQUEST) {
            val id = exportId; exportId = null
            if (resultCode == RESULT_OK && id != null) data?.data?.let { uri ->
                withDock { it.connection.exportFile(id, uri) { } }
            }
        } else if (requestCode == SCANNER_REQUEST) {
            val value = data?.getStringExtra(Intents.Scan.RESULT)
            if (resultCode == RESULT_OK && value != null) {
                try { val pairing = PairingData.parse(value); withDock { it.pair(pairing) } }
                catch (e: IllegalArgumentException) { scannerError(e.message ?: tr("El QR no contiene datos de vinculación válidos.", "The QR code has no valid pairing details.")) }
            } else {
                if (data?.getBooleanExtra(Intents.Scan.MISSING_CAMERA_PERMISSION, false) == true)
                    scannerError(getString(R.string.scanner_permission_error))
            }
        } else super.onActivityResult(requestCode, resultCode, data)
    }
    private fun refresh() {
        val service = dock ?: return
        service.connection.devices { names ->
            if (!isDestroyed && dock === service) deviceNames.text =
                if (names.isEmpty()) tr("Cerebro sin conexión", "Brain disconnected") else names.joinToString("\n")
        }
        service.connection.sharedSettings { image, mode, pending ->
            if (isDestroyed || dock !== service) return@sharedSettings
            updatingSettings = true
            imageToggle.isChecked = image
            val selected = (0 until textModes.childCount).map { textModes.getChildAt(it) as RadioButton }
                .firstOrNull { it.tag == mode }
            if (selected != null) textModes.check(selected.id)
            updatingSettings = false
            imageToggle.contentDescription = if (pending) tr("Imagen a texto · ajuste pendiente", "Image to text · setting pending") else tr("Imagen a texto", "Image to text")
        }
        if (detailsPanel.visibility != View.VISIBLE) return
        val request = ++refreshGeneration
        service.connection.history { items ->
            if (isDestroyed || dock !== service || request != refreshGeneration) return@history
            list.removeAllViews()
            categoryButtons["text"]?.text = "${tr("Textos", "Text")} (${items.size})"
            if (category == "text") items.forEach { addTextCard(it) }
            service.connection.fileHistory { files ->
                if (isDestroyed || dock !== service || request != refreshGeneration) return@fileHistory
                categoryButtons["image"]?.text = "${tr("Imágenes", "Images")} (${files.count { it.item.optString("mime").startsWith("image/") }})"
                categoryButtons["file"]?.text = "${tr("Archivos", "Files")} (${files.count { !it.item.optString("mime").startsWith("image/") }})"
                val visibleFiles = files.filter { file ->
                    val image = file.item.optString("mime").startsWith("image/")
                    category == "image" && image || category == "file" && !image
                }
                if (category == "text" && items.isEmpty() || category != "text" && visibleFiles.isEmpty())
                    list.addView(TextView(this).apply {
                        text = when (category) {
                            "image" -> tr("Aquí aparecerán las imágenes que envíes o recibas.", "Images you send or receive will appear here.")
                            "file" -> tr("Aquí aparecerán los documentos y otros archivos.", "Documents and other files will appear here.")
                            else -> tr("Todavía no hay textos en el dock.", "There is no text in the dock yet.")
                        }
                        setPadding(dp(12), dp(24), dp(12), dp(12))
                    })
                if (category == "image") visibleFiles.forEach { list.addView(imageCard(it)) }
                else if (category == "file") visibleFiles.forEach { addFileCard(it) }
            }
        }
    }
    private fun handleExternalDrop(event: DragEvent): Boolean = when (event.action) {
        DragEvent.ACTION_DRAG_STARTED -> true
        DragEvent.ACTION_DROP -> {
            val clip = event.clipData
            if (clip == null) false else {
                val uris = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).uri }.distinct()
                if (uris.isNotEmpty()) {
                    val grant = runCatching { requestDragAndDropPermissions(event) }.getOrNull()
                    importFiles(uris) { grant?.release() }
                    true
                } else {
                    val texts = (0 until clip.itemCount).mapNotNull { clip.getItemAt(it).text?.toString() }
                        .filter { it.isNotBlank() }
                    if (texts.isEmpty()) { state.text = "SuperHub no entregó una imagen o texto compatible"; false }
                    else {
                        texts.forEach { text -> withDock { it.connection.publish(text) { } } }
                        state.text = "${texts.size} texto(s) recibidos de SuperHub"
                        true
                    }
                }
            }
        }
        else -> true
    }
    private fun importFiles(uris: List<Uri>, completed: () -> Unit = {}) {
        if (uris.isEmpty()) { state.text = "No se recibió ninguna imagen o archivo"; completed(); return }
        val selected = uris.distinct().take(MAX_BATCH)
        val extra = uris.size - selected.size
        val resolver = applicationContext.contentResolver
        state.text = "Preparando ${selected.size} archivo(s) para el dock…"
        withDock { service ->
            var finished = 0
            var saved = 0
            selected.forEach { uri ->
                try { resolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                catch (_: SecurityException) { /* Photo Picker and Sharesheet can grant temporary access only. */ }
                service.connection.importFile(uri) { success ->
                    try { resolver.releasePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION) }
                    catch (_: SecurityException) { /* No persistable grant was taken. */ }
                    finished++
                    if (success) saved++
                    if (finished == selected.size) completed()
                    if (!isDestroyed) state.text = when {
                        finished < selected.size -> "Guardados $saved de $finished; quedan ${selected.size - finished} por preparar"
                        saved == selected.size -> "$saved archivo(s) en el dock" + if (extra > 0) " · $extra omitidos (máximo $MAX_BATCH)" else ""
                        else -> "$saved de ${selected.size} guardados; ${selected.size - saved} con error"
                    }
                }
            }
        }
    }
    private fun addTextCard(item: DockItem) {
        val value = item.value
        val text = value.optString("text")
        val card = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL; setPadding(dp(10), dp(4), dp(6), dp(4)); background = cardBackground() }
        val summary = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        summary.addView(TextView(this).apply { this.text = text.replace('\n', ' ').take(130); textSize = 15f; maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END; setTextColor(foregroundColor) })
        summary.addView(TextView(this).apply { this.text = "${if (item.delivered) tr("Sincronizado", "Synced") else tr("Pendiente", "Pending")} · ${value.optString("created")}"; textSize = 12f; setTextColor(foregroundColor); alpha = 0.7f })
        card.addView(summary, LinearLayout.LayoutParams(0, -2, 1f))
        card.setOnClickListener {
            val content = TextView(this).apply { this.text = text; setTextIsSelectable(true); setPadding(dp(16), dp(8), dp(16), dp(8)) }
            AlertDialog.Builder(this).setTitle(tr("Texto completo", "Full text")).setView(ScrollView(this).apply { addView(content) }).setPositiveButton(tr("Cerrar", "Close"), null).show()
        }
        if (resources.getBoolean(R.bool.accept_external_drops)) card.setOnLongClickListener {
            card.startDragAndDrop(ClipData.newPlainText("Clipboard AI", text), View.DragShadowBuilder(card), null, View.DRAG_FLAG_GLOBAL)
        }
        card.addView(button("⋮") {
            val choices = if (item.delivered) arrayOf(tr("Copiar", "Copy"), tr("Compartir", "Share"), tr("Borrar del dock", "Remove from dock")) else arrayOf(tr("Copiar", "Copy"), tr("Compartir", "Share"))
            AlertDialog.Builder(this).setTitle(tr("Texto del dock", "Dock text")).setItems(choices) { _, option -> when (option) {
                0 -> {
            getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Clipboard AI", text))
            if (resources.getBoolean(R.bool.accept_external_drops))
                Toast.makeText(this, tr("✓ Portapapeles actualizado", "✓ Clipboard updated"), Toast.LENGTH_SHORT).show()
                }
                1 -> startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), tr("Compartir texto", "Share text")))
                else -> withDock { it.connection.delete(value.getString("id")) }
            }
            }.show()
        }, LinearLayout.LayoutParams(dp(48), dp(48)))
        list.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(4) })
    }
    private fun fileStatus(file: DockFile): String {
        val state = when (file.state) {
            "pending" -> tr("Pendiente", "Pending")
            "sending" -> tr("Enviando", "Sending")
            "receiving" -> tr("Recibiendo", "Receiving")
            "delivered" -> tr("Entregado", "Delivered")
            "cancelled" -> tr("Cancelado", "Cancelled")
            "error" -> tr("Error", "Error")
            else -> file.state
        }
        val percent = if (file.state == "delivered") 100 else (100 * file.offset / maxOf(1, file.size)).toInt()
        return "$state · $percent%"
    }
    private fun canOpen(file: DockFile) = file.state == "delivered" ||
        file.direction == "out" && file.state in listOf("pending", "sending")
    private fun imageCard(file: DockFile): LinearLayout {
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL; setPadding(dp(6), dp(4), dp(6), dp(4))
            background = cardBackground()
        }
        val preview = ImageView(this).apply {
            scaleType = ImageView.ScaleType.CENTER_CROP
            setBackgroundColor(if (darkMode) Color.rgb(65, 69, 89) else Color.rgb(220, 211, 203))
            contentDescription = "${tr("Vista previa de", "Preview of")} ${file.item.optString("name")}"
        }
        card.addView(preview, LinearLayout.LayoutParams(dp(52), dp(52)))
        if (canOpen(file)) loadThumbnail(file, preview)
        val summary = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(10), 0, 0, 0) }
        summary.addView(TextView(this).apply {
            text = file.item.optString("name"); textSize = 14f; maxLines = 1
            ellipsize = android.text.TextUtils.TruncateAt.END; setTextColor(foregroundColor)
        })
        summary.addView(TextView(this).apply { text = fileStatus(file); textSize = 12f; setTextColor(foregroundColor); alpha = 0.7f })
        card.addView(summary, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(button("⋮") { fileOptions(file) }, LinearLayout.LayoutParams(dp(48), dp(48)))
        card.setOnClickListener { if (canOpen(file)) openFile(file, false) else fileOptions(file) }
        card.layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(4) }
        return card
    }
    private fun loadThumbnail(file: DockFile, target: ImageView) {
        val source = File(file.path)
        if (!source.isFile) return
        val key = "${file.id}:${source.length()}:${source.lastModified()}"
        target.tag = key
        thumbnails.get(key)?.let { target.setImageBitmap(it); return }
        thumbnailWorker.execute {
            val bitmap = runCatching {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
                BitmapFactory.decodeFile(source.path, bounds)
                if (bounds.outWidth <= 0 || bounds.outHeight <= 0) null else {
                    var sample = 1
                    while (maxOf(bounds.outWidth, bounds.outHeight) / sample > 512) sample *= 2
                    val options = BitmapFactory.Options().apply { inSampleSize = sample }
                    BitmapFactory.decodeFile(source.path, options)
                }
            }.getOrNull() ?: return@execute
            thumbnails.put(key, bitmap)
            runOnUiThread { if (!isDestroyed && target.tag == key) target.setImageBitmap(bitmap) }
        }
    }
    private fun addFileCard(file: DockFile) {
        val name = file.item.getString("name")
        val direction = if (file.direction == "out") tr("Al ordenador", "To computer") else tr("Del ordenador", "From computer")
        val card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL; setPadding(dp(10), dp(4), dp(6), dp(4))
            background = cardBackground()
        }
        card.addView(TextView(this).apply { text = "▤"; textSize = 23f; setTextColor(accentColor) }, LinearLayout.LayoutParams(dp(44), -2))
        val summary = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        summary.addView(TextView(this).apply { text = name; textSize = 15f; maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END; setTextColor(foregroundColor) })
        summary.addView(TextView(this).apply { text = "$direction · ${fileStatus(file)} · ${file.size} bytes"; textSize = 12f; maxLines = 1; ellipsize = android.text.TextUtils.TruncateAt.END; setTextColor(foregroundColor); alpha = 0.7f })
        card.addView(summary, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(button("⋮") { fileOptions(file) }, LinearLayout.LayoutParams(dp(48), dp(48)))
        card.setOnClickListener { if (canOpen(file)) openFile(file, false) else fileOptions(file) }
        list.addView(card, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dp(4) })
    }
    private fun fileOptions(file: DockFile) {
        val choices = if (canOpen(file)) arrayOf(tr("Abrir", "Open"), tr("Guardar copia", "Save copy"), tr("Compartir", "Share"), tr("Quitar del dock", "Remove from dock"))
            else arrayOf(tr("Cancelar o quitar del dock", "Cancel or remove from dock"))
        AlertDialog.Builder(this).setTitle(file.item.optString("name")).setItems(choices) { _, selected ->
            if (canOpen(file)) when (selected) {
                0 -> openFile(file, false)
                1 -> {
                    exportId = file.id
                    startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType(file.item.optString("mime").ifEmpty { "application/octet-stream" })
                        .putExtra(Intent.EXTRA_TITLE, file.item.optString("name")), EXPORT_REQUEST)
                }
                2 -> openFile(file, true)
                else -> removeFile(file)
            } else removeFile(file)
        }.show()
    }
    private fun removeFile(file: DockFile) {
        val action = if (file.state in listOf("delivered", "cancelled")) "delete" else "cancel"
        withDock { it.connection.fileAction(file.id, action) }
    }
    private fun openFile(file: DockFile, share: Boolean) {
        try {
            val uri = FileProvider.getUriForFile(this, "$packageName.files", File(file.path), file.item.getString("name"))
            val mime = file.item.getString("mime").ifEmpty { "application/octet-stream" }
            val action = if (share) Intent(Intent.ACTION_SEND).setType(mime).putExtra(Intent.EXTRA_STREAM, uri)
                else Intent(Intent.ACTION_VIEW).setDataAndType(uri, mime)
            action.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            action.clipData = ClipData.newRawUri(tr("Archivo", "File"), uri)
            startActivity(Intent.createChooser(action, if (share) tr("Compartir archivo", "Share file") else tr("Abrir archivo", "Open file")))
        } catch (_: android.content.ActivityNotFoundException) {
            AlertDialog.Builder(this).setMessage(tr("No hay una aplicación compatible. Puedes guardar el archivo y abrirlo después.", "No compatible app is available. You can save the file and open it later."))
                .setPositiveButton(tr("Cerrar", "Close"), null).show()
        } catch (_: IllegalArgumentException) { state.text = tr("No se pudo abrir el archivo", "Could not open the file") }
    }
    private fun handleShare(value: Intent?) {
        if (value != null && value.action in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE, Intent.ACTION_PROCESS_TEXT)) {
            val uris = incomingUris(value)
            if (uris.isNotEmpty()) importFiles(uris)
            else if (value.type == "text/plain") {
                val text = value.getCharSequenceExtra(if (value.action == Intent.ACTION_PROCESS_TEXT)
                    Intent.EXTRA_PROCESS_TEXT else Intent.EXTRA_TEXT)?.toString().orEmpty()
                if (text.isNotEmpty()) withDock { it.connection.publish(text) { } }
            }
            value.action = Intent.ACTION_MAIN
        }
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); setIntent(intent); handleShare(intent) }
    override fun onStart() {
        super.onStart()
        bound = bindService(Intent(this, DockService::class.java), serviceBinding, BIND_AUTO_CREATE)
    }
    override fun onStop() {
        getPreferences(MODE_PRIVATE).edit().putString("draft", input.text.toString()).apply()
        dock?.removeObserver(observer); dock = null
        if (bound) { unbindService(serviceBinding); bound = false }
        super.onStop()
    }
    override fun onSaveInstanceState(outState: Bundle) {
        outState.putString("exportId", exportId)
        outState.putString("draft", input.text.toString()); super.onSaveInstanceState(outState)
    }
    override fun onDestroy() {
        thumbnailWorker.shutdownNow()
        thumbnails.evictAll()
        super.onDestroy()
    }
    companion object {
        private const val MAX_BATCH = 20
        private const val SCANNER_REQUEST = 4101
        private const val NOTIFICATION_REQUEST = 4102
        private const val SCREENSHOT_REQUEST = 4105
        private const val FILE_REQUEST = 4103
        private const val EXPORT_REQUEST = 4104
    }
}
