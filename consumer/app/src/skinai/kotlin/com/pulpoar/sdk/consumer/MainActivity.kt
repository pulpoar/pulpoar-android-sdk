package com.pulpoar.sdk.consumer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.pulpoar.skinai.kit.PulpoSkinAIAnalyticsConsent
import com.pulpoar.skinai.kit.PulpoSkinAIConfiguration
import com.pulpoar.skinai.kit.PulpoSkinAIKit
import com.pulpoar.skinai.ui.PulpoSkinAIUIConfiguration
import com.pulpoar.skinai.ui.PulpoSkinAIView

/** The SkinAI UI integration, nothing more: it only has to compile, link through R8 and package. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PulpoSkinAIKit.configure(
            applicationContext,
            PulpoSkinAIConfiguration(PulpoSkinAIAnalyticsConsent.DENIED),
        )
        setContent {
            PulpoSkinAIView(
                projectKey = intent.getStringExtra("project") ?: "skinai",
                configuration = PulpoSkinAIUIConfiguration(onClose = { finish() }),
            )
        }
    }
}
