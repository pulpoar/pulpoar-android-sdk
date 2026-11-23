package com.pulpoar.sdk.consumer

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import com.pulpoar.tryon.PulpoAnalyticsConsent
import com.pulpoar.tryon.PulpoTryOn
import com.pulpoar.tryon.PulpoTryOnConfiguration
import com.pulpoar.tryon.ui.PulpoTryOnUIConfiguration
import com.pulpoar.tryon.ui.PulpoTryOnView

/** The integration the README describes, nothing more: it only has to compile, link and package. */
class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        PulpoTryOn.configure(
            applicationContext,
            PulpoTryOnConfiguration(analyticsConsent = PulpoAnalyticsConsent.DENIED),
        )
        setContent {
            PulpoTryOnView(
                projectSlug = "makeup",
                configuration = PulpoTryOnUIConfiguration(onClose = { finish() }),
            )
        }
    }
}
