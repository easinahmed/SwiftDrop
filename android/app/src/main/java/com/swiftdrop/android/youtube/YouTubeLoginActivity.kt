package com.swiftdrop.android.youtube

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.swiftdrop.android.data.Settings
import com.swiftdrop.android.ui.theme.SwiftDropTheme

/**
 * Signs in to YouTube in a WebView (like Seal). Once the account reaches youtube.com, its cookies
 * are saved for yt-dlp and the screen closes. Nothing leaves the phone.
 */
class YouTubeLoginActivity : ComponentActivity() {

    private var webView: WebView? = null
    private var finished = false

    @OptIn(ExperimentalMaterial3Api::class)
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContent {
            val settings by Settings.get(this).state.collectAsStateWithLifecycle()
            SwiftDropTheme(settings.theme) {
                var loading by remember { mutableStateOf(true) }
                var canGoBack by remember { mutableStateOf(false) }
                BackHandler(enabled = canGoBack) { webView?.goBack() }
                Scaffold(
                    topBar = {
                        TopAppBar(
                            title = { Text("Sign in to YouTube") },
                            navigationIcon = {
                                IconButton(onClick = { finish() }) {
                                    Icon(Icons.Filled.Close, contentDescription = "Close")
                                }
                            },
                            actions = {
                                TextButton(onClick = { tryFinish(manual = true) }) { Text("Done") }
                            },
                        )
                    },
                ) { padding ->
                    Column(Modifier.padding(padding).fillMaxSize()) {
                        Text(
                            "Your login stays on this phone and is only used for YouTube downloads.",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 6.dp),
                        )
                        if (loading) LinearProgressIndicator(Modifier.fillMaxWidth())
                        AndroidView(
                            modifier = Modifier.fillMaxSize(),
                            factory = { context ->
                                createWebView(context, onLoading = { loading = it }, onHistory = { canGoBack = it })
                            },
                        )
                        DisposableEffect(Unit) {
                            onDispose {
                                webView?.apply {
                                    stopLoading()
                                    destroy()
                                }
                                webView = null
                            }
                        }
                    }
                }
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun createWebView(
        context: android.content.Context,
        onLoading: (Boolean) -> Unit,
        onHistory: (Boolean) -> Unit,
    ): WebView = WebView(context).apply {
        settings.javaScriptEnabled = true
        settings.domStorageEnabled = true
        // Google refuses sign-in from user agents that announce an embedded WebView ("; wv").
        settings.userAgentString = WebSettings.getDefaultUserAgent(context).replace("; wv", "")
        CookieManager.getInstance().setAcceptCookie(true)
        CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
        webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                // Stay on the web: no app links or intent:// hand-offs from the sign-in pages.
                val scheme = request.url.scheme
                return scheme != "https" && scheme != "http"
            }

            override fun onPageStarted(view: WebView, url: String?, favicon: Bitmap?) {
                onLoading(true)
            }

            override fun onPageFinished(view: WebView, url: String?) {
                onLoading(false)
                onHistory(view.canGoBack())
                val host = url?.let { Uri.parse(it).host }.orEmpty()
                // accounts.youtube.com is a stop on the way back from sign-in; wait for YouTube itself.
                if (host == "youtube.com" || host == "www.youtube.com" || host == "m.youtube.com") tryFinish(manual = false)
            }
        }
        loadUrl(YouTubeAccount.LOGIN_URL)
        webView = this
    }

    private fun tryFinish(manual: Boolean) {
        if (finished) return
        if (YouTubeAccount.exportFromWebView(this)) {
            finished = true
            Toast.makeText(this, "Signed in to YouTube", Toast.LENGTH_SHORT).show()
            setResult(RESULT_OK)
            finish()
        } else if (manual) {
            Toast.makeText(this, "Finish signing in first, until YouTube opens.", Toast.LENGTH_LONG).show()
        }
    }
}
