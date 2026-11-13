package org.clipboardai.app

import android.content.ComponentName
import android.content.Intent
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class MainLayoutTest {
    @Test fun headerDoesNotConsumeTheScreenAndShowsTitleBesideSettings() {
        val app = RuntimeEnvironment.getApplication()
        val service = Robolectric.buildService(DockService::class.java).create()
        shadowOf(app).setComponentNameAndServiceForBindService(
            ComponentName(app, DockService::class.java), service.get().onBind(Intent()))
        val controller = Robolectric.buildActivity(MainActivity::class.java).setup()
        try {
            val activity = controller.get()
            val root = activity.findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as LinearLayout
            val width = View.MeasureSpec.makeMeasureSpec(1080, View.MeasureSpec.EXACTLY)
            val height = View.MeasureSpec.makeMeasureSpec(2400, View.MeasureSpec.EXACTLY)
            root.measure(width, height)
            root.layout(0, 0, 1080, 2400)
            val header = root.getChildAt(0) as LinearLayout
            val status = root.getChildAt(1)
            val density = activity.resources.displayMetrics.density
            assertEquals((56 * density).toInt(), header.height)
            assertEquals(header.bottom + (8 * density).toInt(), status.top)
            assertTrue(status.top < (100 * density).toInt())
            assertTrue((header.getChildAt(0) as TextView).width > 0)
            assertTrue((header.getChildAt(1) as Button).width < header.width / 2)
        } finally {
            controller.pause().stop().destroy()
            service.destroy()
        }
    }
}
