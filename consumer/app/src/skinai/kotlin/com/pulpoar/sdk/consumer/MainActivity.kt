package com.pulpoar.sdk.consumer

import android.app.Activity
import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import com.pulpoar.skinai.kit.PulpoSkinAIAnalyticsConsent
import com.pulpoar.skinai.kit.PulpoSkinAIConfiguration
import com.pulpoar.skinai.kit.PulpoSkinAIKit
import com.pulpoar.skinai.kit.PulpoSkinAIProject
import com.pulpoar.skinai.kit.PulpoSkinAnalyzer
import kotlinx.coroutines.*

/** The SkinAI Kit integration, nothing more: it only has to compile, link through R8 and package. */
class MainActivity : Activity() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private var analyzer: PulpoSkinAnalyzer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PulpoSkinAIKit.configure(
            applicationContext,
            PulpoSkinAIConfiguration(PulpoSkinAIAnalyticsConsent.DENIED),
        )
        val current = PulpoSkinAnalyzer()
        analyzer = current
        val status =
            TextView(this).apply { text = "SkinAI ${PulpoSkinAIKit.sdkVersion}; analytics denied" }
        val start =
            Button(this).apply {
                text = "Load project and analyze a gray photo"
                setOnClickListener {
                    scope.launch {
                        try {
                            val project =
                                PulpoSkinAIProject.load(
                                    intent.getStringExtra("project") ?: "skinai"
                                )
                            status.text = "Live view: ${project.theme().features.showsLiveView}"
                            val photo =
                                Bitmap.createBitmap(720, 720, Bitmap.Config.ARGB_8888).apply {
                                    eraseColor(Color.GRAY)
                                }
                            try {
                                current.analyze(photo)
                            } finally {
                                photo.recycle()
                            }
                        } catch (error: Exception) {
                            status.text = error.message
                        }
                    }
                }
            }
        setContentView(
            LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                addView(status)
                addView(start)
            }
        )
    }

    override fun onDestroy() {
        analyzer?.close()
        analyzer = null
        scope.cancel()
        super.onDestroy()
    }
}
