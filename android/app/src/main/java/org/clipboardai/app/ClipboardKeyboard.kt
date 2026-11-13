package org.clipboardai.app

import android.content.ClipboardManager
import android.graphics.Color
import android.inputmethodservice.InputMethodService
import android.view.Gravity
import android.view.View
import android.widget.Button
import android.widget.LinearLayout

class ClipboardKeyboard : InputMethodService() {
    override fun onCreateInputView(): View {
        val spanish = resources.configuration.locales[0].language == "es"
        return LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            setPadding(12, 12, 12, 12)
            setBackgroundColor(Color.rgb(48, 52, 70))
            addView(Button(this@ClipboardKeyboard).apply {
                text = if (spanish) "Escribir portapapeles" else "Type clipboard"
                isAllCaps = false
                setOnClickListener {
                    val clip = getSystemService(ClipboardManager::class.java).primaryClip
                    val content = (clipboardContent(clip) as? ClipboardContent.Text)?.value.orEmpty()
                    if (content.isNotEmpty()) currentInputConnection?.commitText(content, 1)
                }
            }, LinearLayout.LayoutParams(0, -2, 1f))
            addView(Button(this@ClipboardKeyboard).apply {
                text = "⌨"
                contentDescription = if (spanish) "Cambiar teclado" else "Switch keyboard"
                setOnClickListener {
                    if (android.os.Build.VERSION.SDK_INT >= 28) switchToNextInputMethod(false)
                    else (getSystemService(INPUT_METHOD_SERVICE) as android.view.inputmethod.InputMethodManager).showInputMethodPicker()
                }
            }, LinearLayout.LayoutParams(-2, -2).apply { gravity = Gravity.CENTER_VERTICAL })
        }
    }
}
