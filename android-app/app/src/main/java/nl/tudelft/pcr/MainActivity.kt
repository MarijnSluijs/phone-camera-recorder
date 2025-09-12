package nl.tudelft.pcr

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.MediaStore
import android.hardware.camera2.CameraCharacteristics
import android.hardware.camera2.CameraManager
import android.util.Log
import android.os.Environment
import java.io.File
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.MediaStoreOutputOptions
import androidx.camera.video.PendingRecording
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.FallbackStrategy
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.camera.camera2.interop.Camera2CameraInfo
import android.widget.FrameLayout
import android.widget.TextView
import android.view.Gravity
import android.view.View
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.concurrent.Executors

class MainActivity : ComponentActivity() {
    private lateinit var previewView: PreviewView
    private val tag = "PCR/Main"
    private lateinit var overlay: TextView
    private var outputFile: File? = null

    private val cameraExecutor = Executors.newSingleThreadExecutor()
    private var recording: Recording? = null

    private val requestPermissions = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { perms ->
        if (perms.all { it.value }) {
            startFlow()
        } else {
            finish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        previewView = PreviewView(this)
        overlay = TextView(this).apply {
            text = ""
            setBackgroundColor(0x66FF0000)
            setTextColor(0xFFFFFFFF.toInt())
            textSize = 18f
            visibility = View.GONE
            setPadding(16, 8, 16, 8)
        }
        val root = FrameLayout(this)
        root.addView(previewView, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))
        val lp = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT)
        lp.gravity = Gravity.TOP or Gravity.CENTER_HORIZONTAL
        lp.topMargin = 24
        root.addView(overlay, lp)
        setContentView(root)
        checkPermissionsAndStart()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        // Re-evaluate extras when activity is re-used (launchMode=singleTop)
        checkPermissionsAndStart()
    }

    private fun checkPermissionsAndStart() {
        val needed = mutableListOf(Manifest.permission.CAMERA, Manifest.permission.RECORD_AUDIO)
        if (Build.VERSION.SDK_INT <= 28) {
            needed += Manifest.permission.WRITE_EXTERNAL_STORAGE
        }
        val missing = needed.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }
        if (missing.isEmpty()) startFlow() else requestPermissions.launch(missing.toTypedArray())
    }

    private fun startFlow() {
    val trigger = intent.getBooleanExtra("pcr_trigger", false)
        val startEpochUsExtra = intent.getLongExtra("pcr_start_epoch_us", Long.MIN_VALUE)
        val durationMsExtra = intent.getIntExtra("pcr_duration_ms", Int.MIN_VALUE)
        val lensExtra = intent.getStringExtra("pcr_lens")
    val noAudio = intent.getBooleanExtra("pcr_no_audio", false)
        if (!trigger || startEpochUsExtra == Long.MIN_VALUE || durationMsExtra == Int.MIN_VALUE) {
            // Launched manually; just show preview.
            Log.i(tag, "Manual launch or missing extras; showing preview")
            bindCameraAndMaybeRecord(null)
            return
        }
    val startEpochUs = startEpochUsExtra
    val durationMs = durationMsExtra
    val lens = lensExtra ?: "ultra-wide"
    Log.i(tag, "Parsed extras startUs=$startEpochUs durationMs=$durationMs lens=$lens noAudio=$noAudio")
    bindCameraAndMaybeRecord(Schedule(startEpochUs, durationMs, lens), noAudio)
    }

    data class Schedule(val startEpochUs: Long, val durationMs: Int, val lens: String)

    private fun bindCameraAndMaybeRecord(schedule: Schedule?, noAudio: Boolean = false) {
        Log.i(tag, "bindCameraAndMaybeRecord schedule=$schedule")
        val provider = ProcessCameraProvider.getInstance(this)
        provider.addListener({
            val cameraProvider = provider.get()
            val cameraSelector = selectCameraSelector(schedule?.lens?.lowercase())
            val preview = Preview.Builder().build().also {
                it.setSurfaceProvider(previewView.surfaceProvider)
            }

            val recorder = Recorder.Builder()
                .setQualitySelector(QualitySelector.from(Quality.FHD, FallbackStrategy.lowerQualityOrHigherThan(Quality.SD)))
                .build()
            val videoCapture = VideoCapture.withOutput(recorder)

            try {
                cameraProvider.unbindAll()

                fun tryBind(sel: CameraSelector): androidx.camera.core.Camera? = try {
                    cameraProvider.bindToLifecycle(this, sel, preview, videoCapture)
                } catch (e: Exception) {
                    Log.w(tag, "bind failed for selector: $sel -> ${e.message}")
                    null
                }

                var camera = tryBind(cameraSelector)
                if (camera == null) {
                    Log.w(tag, "Falling back to DEFAULT_BACK_CAMERA")
                    camera = tryBind(CameraSelector.DEFAULT_BACK_CAMERA)
                }
                if (camera == null) {
                    Log.w(tag, "Falling back to DEFAULT_FRONT_CAMERA")
                    camera = tryBind(CameraSelector.DEFAULT_FRONT_CAMERA)
                }
                if (camera == null) {
                    Log.e(tag, "Unable to bind any camera; finishing")
                    finish()
                    return@addListener
                }

                val lensPref = schedule?.lens?.lowercase()
                if (lensPref == null || lensPref == "ultra-wide") {
                    val current = camera.cameraInfo.zoomState.value
                    val minZoom = current?.minZoomRatio
                    if (minZoom != null) {
                        camera.cameraControl.setZoomRatio(minZoom)
                    } else {
                        camera.cameraInfo.zoomState.observe(this) { state ->
                            camera.cameraControl.setZoomRatio(state.minZoomRatio)
                            camera.cameraInfo.zoomState.removeObservers(this)
                        }
                    }
                }

                if (schedule != null) {
                    startScheduledRecording(videoCapture, schedule, noAudio)
                }
            } catch (e: Exception) {
                Log.e(tag, "Unexpected error during camera bind: ${e.message}")
                finish()
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun selectCameraSelector(lensPref: String?): CameraSelector {
        return when (lensPref) {
            "front" -> CameraSelector.DEFAULT_FRONT_CAMERA
            "ultra-wide" ->
                CameraSelector.Builder()
                    .requireLensFacing(CameraSelector.LENS_FACING_BACK)
                    .addCameraFilter { cameraInfos ->
                        val cm = getSystemService(Context.CAMERA_SERVICE) as CameraManager
                        val scored = cameraInfos.mapNotNull { info ->
                            val c2 = Camera2CameraInfo.from(info)
                            val id = c2.cameraId
                            val chars = try { cm.getCameraCharacteristics(id) } catch (_: Exception) { null }
                            val facing = chars?.get(CameraCharacteristics.LENS_FACING)
                            if (facing != CameraCharacteristics.LENS_FACING_BACK) null else {
                                val focals = chars.get(CameraCharacteristics.LENS_INFO_AVAILABLE_FOCAL_LENGTHS)
                                val minFocal = focals?.minOrNull() ?: Float.MAX_VALUE
                                Log.i(tag, "Candidate back camera id=$id minFocal=${minFocal}")
                                Pair(info, minFocal)
                            }
                        }
                        val best = scored.minByOrNull { it.second }
                        val selected = best?.first
                        if (best != null) {
                            Log.i(tag, "Selecting ultra-wide candidate with minFocal=${best.second}")
                        }
                        if (selected != null) listOf(selected) else cameraInfos
                    }
                    .build()
            else -> CameraSelector.DEFAULT_BACK_CAMERA
        }
    }

    private fun startScheduledRecording(videoCapture: VideoCapture<Recorder>, schedule: Schedule, noAudio: Boolean) {
        val nowUs = System.currentTimeMillis() * 1000
        // If startEpochUs == 0, start immediately. If in the past, start immediately.
        val effectiveStartUs = if (schedule.startEpochUs <= 0) nowUs else schedule.startEpochUs
        var delayMs = ((effectiveStartUs - nowUs).coerceAtLeast(0)) / 1000
        if (delayMs < 100) delayMs = 300
        Log.i(tag, "startScheduledRecording startUs=$effectiveStartUs nowUs=$nowUs delayMs=$delayMs durMs=${schedule.durationMs}")

        val name = SimpleDateFormat("yyyyMMdd_HHmmss", Locale.US).format(System.currentTimeMillis())
        val baseDir = getExternalFilesDir(Environment.DIRECTORY_MOVIES)
        val outDir = File(baseDir, "PCR")
        if (!outDir.exists()) outDir.mkdirs()
        val file = File(outDir, "PCR_${name}.mp4")
        outputFile = file
        val options = FileOutputOptions.Builder(file).build()

        var pending: PendingRecording = videoCapture.output
            .prepareRecording(this, options)
        val hasAudioPerm = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        if (!noAudio && hasAudioPerm) {
            pending = pending.withAudioEnabled()
        }

        previewView.postDelayed({
            Log.i(tag, "Starting recording now…")
            recording = pending.start(ContextCompat.getMainExecutor(this)) { event ->
                Log.i(tag, "Recorder event: $event")
                if (event is androidx.camera.video.VideoRecordEvent.Finalize) {
                    val f = outputFile
                    if (f != null && f.exists()) {
                        Log.i(tag, "PCR_SAVED path=${f.absolutePath}")
                    } else {
                        Log.w(tag, "Finalize received but output file missing: ${f?.absolutePath}")
                    }
                }
            }
            overlay.text = "Recording…"
            overlay.visibility = View.VISIBLE
            if (schedule.durationMs > 0) {
                previewView.postDelayed({ stopRecordingAndFinish() }, schedule.durationMs.toLong())
            }
        }, delayMs)
    }

    private fun stopRecordingAndFinish() {
        try {
            recording?.stop()
        } catch (_: Exception) {}
        recording = null
        overlay.visibility = View.GONE
        Log.i(tag, "Recording stopped; finishing")
        finish()
    }
}
