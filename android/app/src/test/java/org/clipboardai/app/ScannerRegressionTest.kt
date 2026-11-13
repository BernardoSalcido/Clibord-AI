package org.clipboardai.app

import android.Manifest
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.CaptureActivity
import android.content.Intent
import org.junit.Test
import org.junit.Before
import org.junit.After
import android.content.ComponentName
import org.robolectric.android.controller.ServiceController
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import android.app.AlertDialog
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.os.Looper
import org.junit.Assert.*
import org.robolectric.shadows.ShadowAlertDialog

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class ScannerRegressionTest {
    private lateinit var service: ServiceController<DockService>
    @Before fun bindRealService() {
        service = Robolectric.buildService(DockService::class.java).create()
        val app = RuntimeEnvironment.getApplication()
        shadowOf(app).setComponentNameAndServiceForBindService(
            ComponentName(app, DockService::class.java), service.get().onBind(Intent()))
    }
    @After fun closeService() { service.destroy() }

    @Test fun scannerOpensAfterCameraPermissionOnAndroid14() {
        val application = RuntimeEnvironment.getApplication()
        shadowOf(application).grantPermissions(Manifest.permission.CAMERA)
        val intent = Intent(application, CaptureActivity::class.java).setAction(Intents.Scan.ACTION)
            .putExtra(Intents.Scan.ORIENTATION_LOCKED, false).putExtra(Intents.Scan.BEEP_ENABLED, false)
        val controller = Robolectric.buildActivity(CaptureActivity::class.java, intent)
        controller.setup().visible()
        controller.pause().stop().destroy()
    }

    private fun descendants(view: View): List<View> = listOf(view) +
        if (view is ViewGroup) (0 until view.childCount).flatMap { descendants(view.getChildAt(it)) } else emptyList()

    private fun openPairingFromSettings(activity: MainActivity) {
        descendants(activity.window.decorView).filterIsInstance<Button>().first {
            it.text.toString().contains("Ajustes") || it.text.toString().contains("Settings")
        }.performClick()
        ShadowAlertDialog.getLatestAlertDialog().listView.performItemClick(null, 0, 0)
    }

    @Test fun mainScreenLaunchesScannerAndSurvivesLeavingForCamera() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        try {
            val activity = controller.get()
            openPairingFromSettings(activity)
            val dialog = ShadowAlertDialog.getLatestAlertDialog()
            dialog.listView.performItemClick(null, 0, 0)
            val started = shadowOf(activity).nextStartedActivityForResult
            assertEquals(CaptureActivity::class.java.name, started.intent.component!!.className)
            controller.pause().stop().start().resume()
        } finally { controller.pause().stop().destroy() }
    }

    @Test fun codeAloneKeepsPairingDialogOpenWithExplanation() {
        val controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        try {
            val activity = controller.get()
            openPairingFromSettings(activity)
            ShadowAlertDialog.getLatestAlertDialog().listView.performItemClick(null, 1, 1)
            shadowOf(Looper.getMainLooper()).idle()
            val dialog = ShadowAlertDialog.getLatestAlertDialog()
            val input = descendants(dialog.window!!.decorView).filterIsInstance<EditText>().first()
            input.setText("local_pairing_code_123456")
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).performClick()
            assertTrue(dialog.isShowing)
            assertTrue(input.error.toString().contains("bloque completo") || input.error.toString().contains("full block"))
            dialog.dismiss()
        } finally { controller.pause().stop().destroy() }
    }
}
