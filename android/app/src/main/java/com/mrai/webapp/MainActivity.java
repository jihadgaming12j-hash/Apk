package com.mrai.webapp;

import android.annotation.SuppressLint;
import android.content.Intent;
import android.content.pm.ActivityInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.webkit.CookieManager;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AppCompatActivity;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;
import androidx.webkit.WebViewAssetLoader;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;

public class MainActivity extends AppCompatActivity {

    private static final String ASSET_HOST = "appassets.androidplatform.net";

    private WebView webView;
    private SwipeRefreshLayout swipe;
    private ValueCallback<Uri[]> filePathCallback;
    private String startUrl = "about:blank";
    private boolean fileMode = false;
    private boolean showingError = false;

    private final ActivityResultLauncher<Intent> chooserLauncher = registerForActivityResult(
            new ActivityResultContracts.StartActivityForResult(), result -> {
                if (filePathCallback == null) return;
                Uri[] uris = WebChromeClient.FileChooserParams.parseResult(result.getResultCode(), result.getData());
                filePathCallback.onReceiveValue(uris);
                filePathCallback = null;
            });

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        boolean refresh = true;
        String orientation = "portrait";
        try {
            JSONObject c = new JSONObject(readAsset("config.json"));
            startUrl = c.optString("url", "about:blank");
            fileMode = "file".equals(c.optString("mode"));
            refresh = c.optBoolean("refresh", true);
            orientation = c.optString("orientation", "portrait");
        } catch (Exception ignored) {
        }

        if ("landscape".equals(orientation)) {
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE);
        } else if ("portrait".equals(orientation)) {
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_PORTRAIT);
        } else {
            setRequestedOrientation(ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        }

        webView = findViewById(R.id.webview);
        swipe = findViewById(R.id.swipe);

        WebSettings s = webView.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(false);
        s.setBuiltInZoomControls(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);

        CookieManager.getInstance().setAcceptCookie(true);
        CookieManager.getInstance().setAcceptThirdPartyCookies(webView, true);

        final WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        webView.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                return loader.shouldInterceptRequest(request.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleUrl(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleUrl(Uri.parse(url));
            }

            @Override
            public void onPageStarted(WebView view, String url, android.graphics.Bitmap favicon) {
                if (url != null && !url.startsWith("about:") && !url.startsWith("data:")) {
                    showingError = false;
                }
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                swipe.setRefreshing(false);
                if (!showingError) applyStatusBarFromPage(view);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) {
                    swipe.setRefreshing(false);
                    showingError = true;
                    view.loadDataWithBaseURL(null, errorHtml(), "text/html", "UTF-8", null);
                }
            }
        });

        webView.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView w, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePathCallback != null) filePathCallback.onReceiveValue(null);
                filePathCallback = callback;
                try {
                    chooserLauncher.launch(params.createIntent());
                } catch (Exception e) {
                    filePathCallback = null;
                    return false;
                }
                return true;
            }
        });

        webView.setDownloadListener((url, userAgent, contentDisposition, mimeType, contentLength) -> {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
            } catch (Exception ignored) {
            }
        });

        swipe.setEnabled(refresh);
        swipe.setOnChildScrollUpCallback((parent, child) -> webView.getScrollY() > 0);
        swipe.setOnRefreshListener(() -> {
            if (showingError) {
                showingError = false;
                webView.loadUrl(startUrl);
            } else {
                webView.reload();
            }
        });

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (webView.canGoBack() && !showingError) {
                    webView.goBack();
                } else {
                    setEnabled(false);
                    getOnBackPressedDispatcher().onBackPressed();
                }
            }
        });

        if (savedInstanceState == null) {
            webView.loadUrl(startUrl);
        } else {
            webView.restoreState(savedInstanceState);
        }
    }

    private boolean handleUrl(Uri uri) {
        String scheme = uri.getScheme() == null ? "" : uri.getScheme();
        if (scheme.equals("about") || scheme.equals("data") || scheme.equals("blob") || scheme.equals("javascript")) {
            return false;
        }
        if (scheme.equals("http") || scheme.equals("https")) {
            if (!fileMode || ASSET_HOST.equals(uri.getHost())) return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) {
        }
        return true;
    }

    // পেজের theme-color বা ব্যাকগ্রাউন্ড রং পড়ে স্ট্যাটাস বারে বসায় (সময়/ব্যাটারির জায়গা)
    private void applyStatusBarFromPage(WebView view) {
        final String js = "(function(){try{var m=document.querySelector('meta[name=\"theme-color\"]');"
                + "if(m&&m.content)return m.content;"
                + "var c=getComputedStyle(document.body||document.documentElement).backgroundColor;"
                + "if(!c||c==='transparent'||c.indexOf('rgba(0, 0, 0, 0)')===0){"
                + "c=getComputedStyle(document.documentElement).backgroundColor;}"
                + "return c||'';}catch(e){return '';}})()";
        view.evaluateJavascript(js, value -> {
            if (value == null || value.equals("null")) return;
            Integer color = parseCssColor(value.replace("\"", "").trim());
            if (color != null) setStatusBar(color);
        });
    }

    private static Integer parseCssColor(String s) {
        try {
            if (s.startsWith("#")) {
                String h = s.substring(1);
                if (h.length() == 3) {
                    h = "" + h.charAt(0) + h.charAt(0) + h.charAt(1) + h.charAt(1) + h.charAt(2) + h.charAt(2);
                }
                if (h.length() == 6) return Color.parseColor("#" + h);
                return null;
            }
            java.util.regex.Matcher m = java.util.regex.Pattern
                    .compile("rgba?\\(\\s*(\\d+)[,\\s]+(\\d+)[,\\s]+(\\d+)(?:[,/\\s]+([0-9.]+))?\\s*\\)")
                    .matcher(s);
            if (m.find()) {
                if (m.group(4) != null && Double.parseDouble(m.group(4)) < 0.5) return null;
                return Color.rgb(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)));
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private void setStatusBar(int color) {
        getWindow().setStatusBarColor(color);
        if (Build.VERSION.SDK_INT >= 23) {
            View decor = getWindow().getDecorView();
            int flags = decor.getSystemUiVisibility();
            double lum = (0.299 * Color.red(color) + 0.587 * Color.green(color) + 0.114 * Color.blue(color)) / 255.0;
            if (lum > 0.6) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            } else {
                flags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            }
            decor.setSystemUiVisibility(flags);
        }
    }

    private String errorHtml() {
        return "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='font-family:sans-serif;text-align:center;padding:60px 24px;color:#334155'>"
                + "<h2>ইন্টারনেট সংযোগ নেই</h2><p>No connection</p><br>"
                + "<button id='r' style='padding:12px 24px;font-size:16px;border:0;border-radius:12px;background:#059669;color:#fff'>আবার চেষ্টা করুন / Retry</button>"
                + "<script>document.getElementById('r').onclick=function(){location.href=" + JSONObject.quote(startUrl) + "};</script>"
                + "</body></html>";
    }

    private String readAsset(String name) throws IOException {
        try (InputStream in = getAssets().open(name); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        webView.saveState(outState);
    }

    @Override
    protected void onPause() {
        super.onPause();
        webView.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        webView.onResume();
    }

    @Override
    protected void onDestroy() {
        if (webView != null) {
            webView.stopLoading();
            webView.destroy();
        }
        super.onDestroy();
    }
}
