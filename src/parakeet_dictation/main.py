#!/usr/bin/env python3
import os
import io
import time
import tempfile
import threading
import pyaudio
import wave
import numpy as np
import rumps
from pynput import keyboard
from pynput.keyboard import Controller
from parakeet_mlx import from_pretrained
import signal
from text_selection import TextSelection
from logger_config import setup_logging

# ---------- Logging: default to WARNING (lower overhead), override via env ----------
logger = setup_logging()
_log_env = os.getenv("PARAKEET_LOG", "").lower()
if _log_env in ("debug", "info", "warning", "error", "critical"):
    import logging as _logging
    logger.setLevel(getattr(_logging, _log_env.upper()))
else:
    # Default to WARNING to reduce hot-path overhead
    import logging as _logging
    logger.setLevel(_logging.WARNING)

# Set up a global flag for handling SIGINT
exit_flag = False

def signal_handler(frame):
    """Global signal handler for graceful shutdown"""
    global exit_flag
    logger.info("Shutdown signal received, exiting gracefully...")
    exit_flag = True
    threading.Timer(2.0, lambda: os._exit(0)).start()

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class WhisperDictationApp(rumps.App):
    def __init__(self):
        super(WhisperDictationApp, self).__init__("🎙️", quit_button=rumps.MenuItem("Quit"))
        self.status_item = rumps.MenuItem("Status: Ready")
        self.recording_menu_item = rumps.MenuItem("Start Recording")
        self.menu = [self.recording_menu_item, None, self.status_item]

        self.recording = False
        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.keyboard_controller = Controller()
        self.text_selector = TextSelection()

        # Initialize Parakeet model (async)
        self.model = None
        self.load_model_thread = threading.Thread(target=self.load_model, daemon=True)
        self.load_model_thread.start()

        # Audio recording parameters
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.chunk = 512  # smaller chunk -> snappier stop

        # Hotkey state
        self.is_recording_with_hotkey = False

        # Set up global hotkeys (Ctrl+Alt+A) and release listener
        self.setup_global_monitor()

        logger.info("Started WhisperDictation app. Look for 🎙️ in your menu bar.")
        logger.info("Press and HOLD Ctrl + Alt + A to record. Release to transcribe.")
        logger.info("Press Ctrl+C to quit the application.")
        logger.info("If hotkeys don’t fire: System Settings → Privacy & Security → Accessibility + Input Monitoring")

        self.watchdog = threading.Thread(target=self.check_exit_flag, daemon=True)
        self.watchdog.start()

    def check_exit_flag(self):
        while True:
            if exit_flag:
                logger.info("Watchdog detected exit flag, shutting down...")
                self.cleanup()
                rumps.quit_application()
                os._exit(0)
            time.sleep(0.5)

    def cleanup(self):
        logger.info("Cleaning up resources...")
        self.recording = False
        if hasattr(self, 'recording_thread') and self.recording_thread.is_alive():
            try:
                self.recording_thread.join(timeout=1.0)
            except Exception:
                pass
        if hasattr(self, 'audio'):
            try:
                self.audio.terminate()
            except Exception:
                pass

    def load_model(self):
        self.title = "🎙️ (Loading...)"
        self.status_item.title = "Status: Loading Parakeet model..."
        try:
            model_id = "mlx-community/parakeet-tdt-0.6b-v2"
            self.model = from_pretrained(model_id)

            # Warm-up: run a tiny silent clip once to trigger JIT/graph compilation & caches
            try:
                sr = 16000
                silence = (np.zeros(int(0.3 * sr)).astype(np.int16)).tobytes()
                buf = io.BytesIO()
                with wave.open(buf, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # int16
                    wf.setframerate(sr)
                    wf.writeframes(silence)
                buf.seek(0)
                _ = self.model.transcribe(buf)
                logger.info("Parakeet warm-up done")
            except Exception as we:
                logger.debug(f"Warm-up skipped/fallback due to: {we}")

            self.title = "🎙️"
            self.status_item.title = "Status: Ready"
            logger.info("Parakeet model loaded successfully!")
        except Exception as e:
            self.title = "🎙️ (Error)"
            self.status_item.title = "Status: Error loading model"
            logger.error(f"Error loading Parakeet model: {e}")

    # ---------------------------
    # Global hotkey + release monitor
    # ---------------------------
    def setup_global_monitor(self):
        self.key_monitor_thread = threading.Thread(target=self.monitor_keys, daemon=True)
        self.key_monitor_thread.start()

    def monitor_keys(self):
        """
        Start on '<ctrl>+<alt>+a' press, stop when either Ctrl or Alt is released.
        Uses GlobalHotKeys for the chord and a separate Listener for modifier releases.
        """
        def start():
            if not self.recording and not self.is_recording_with_hotkey:
                self.is_recording_with_hotkey = True
                logger.info("STARTING recording via Ctrl+Alt+A hotkey")
                self.start_recording()

        def maybe_stop_on_modifier_release(key):
            from pynput import keyboard as kb
            if key in (kb.Key.ctrl, kb.Key.ctrl_l, kb.Key.ctrl_r,
                       kb.Key.alt, kb.Key.alt_l, kb.Key.alt_r):
                if self.is_recording_with_hotkey and self.recording:
                    logger.info("STOPPING recording via Ctrl/Alt release")
                    self.is_recording_with_hotkey = False
                    self.stop_recording()

        logger.info("Starting global hotkey listener: Ctrl+Alt+A (hold to record)")
        try:
            with keyboard.GlobalHotKeys({
                '<ctrl>+<alt>+a': start,   # press to start
            }) as hotkeys:
                # Separate listener for key releases
                with keyboard.Listener(on_release=maybe_stop_on_modifier_release):
                    hotkeys.join()
        except Exception as e:
            logger.error(f"Error with keyboard listeners: {e}")
            logger.error("Please check Accessibility/Input Monitoring permissions in System Settings.")

    # ---------------------------
    # Menu item click
    # ---------------------------
    @rumps.clicked("Start Recording")
    def toggle_recording(self, sender):
        if not self.recording:
            self.start_recording()
            sender.title = "Stop Recording"
        else:
            self.stop_recording()
            sender.title = "Start Recording"

    # ---------------------------
    # Recording & transcription
    # ---------------------------
    def start_recording(self):
        if not hasattr(self, 'model') or self.model is None:
            logger.warning("Model not loaded. Please wait for the model to finish loading.")
            self.status_item.title = "Status: Waiting for model to load"
            return

        self.frames = []
        self.recording = True
        self.title = "🎙️ (Recording)"
        self.status_item.title = "Status: Recording..."
        logger.info("Recording started. Speak now...")

        # Use a callback stream for near-instant stop
        self.recording_thread = threading.Thread(target=self._record_audio_callback_loop, daemon=True)
        self.recording_thread.start()

    def _record_audio_callback_loop(self):
        def _cb(in_data, frame_count, time_info, status_flags):
            # in_data is bytes for paInt16 mono frames
            if self.recording:
                self.frames.append(in_data)
                return (None, pyaudio.paContinue)
            else:
                return (None, pyaudio.paComplete)

        stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk,
            stream_callback=_cb
        )
        try:
            stream.start_stream()
            while stream.is_active():
                if not self.recording:
                    break
                time.sleep(0.01)
        finally:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        if hasattr(self, 'recording_thread'):
            self.recording_thread.join()

        self.title = "🎙️ (Transcribing)"
        self.status_item.title = "Status: Transcribing..."
        logger.info("Recording stopped. Transcribing...")

        transcribe_thread = threading.Thread(target=self.process_recording, daemon=True)
        transcribe_thread.start()

    def process_recording(self):
        try:
            self.transcribe_audio()
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            self.status_item.title = "Status: Error during transcription"
        finally:
            self.title = "🎙️"

    def _write_wav_to_buffer(self, frames_bytes: bytes) -> io.BytesIO:
        """Create an in-memory WAV buffer from PCM frames."""
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(frames_bytes)
        buf.seek(0)
        return buf

    def transcribe_audio(self):
        if not self.frames:
            self.title = "🎙️"
            self.status_item.title = "Status: No audio recorded"
            logger.warning("No audio recorded")
            return

        pcm = b''.join(self.frames)

        # Prefer in-memory transcribe (fast); fall back to temp file if needed
        use_file_fallback = False
        try:
            buffer = self._write_wav_to_buffer(pcm)
            result = self.model.transcribe(buffer)  # many libs accept file-like
        except Exception as e:
            logger.debug(f"In-memory transcribe failed ({e}); falling back to temp file")
            use_file_fallback = True

        if use_file_fallback:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_filename = temp_file.name
            try:
                with wave.open(temp_filename, 'wb') as wf:
                    wf.setnchannels(self.channels)
                    wf.setsampwidth(self.audio.get_sample_size(self.format))
                    wf.setframerate(self.rate)
                    wf.writeframes(pcm)
                result = self.model.transcribe(temp_filename)
            finally:
                try:
                    os.unlink(temp_filename)
                except Exception:
                    pass

        text = (getattr(result, "text", "") or "").strip()

        if text:
            selected_text = self.text_selector.get_selected_text()
            bedrock = getattr(self, 'bedrock_client', None)

            if selected_text and bedrock and hasattr(bedrock, 'is_available') and bedrock.is_available():
                try:
                    self.status_item.title = "Status: Enhancing text with AI..."
                    enhanced_text = bedrock.enhance_text(text, selected_text)
                    self.text_selector.replace_selected_text(enhanced_text)
                    self.status_item.title = f"Status: Enhanced: {enhanced_text[:30]}..."
                except Exception as e:
                    logger.error(f"Error enhancing text: {e}")
                    self.insert_text(text)
                    self.status_item.title = f"Status: Transcribed: {text[:30]}..."
            else:
                self.insert_text(text)
                self.status_item.title = f"Status: Transcribed: {text[:30]}..."
        else:
            logger.warning("No speech detected")
            self.status_item.title = "Status: No speech detected"

    def insert_text(self, text):
        # Minimal logging in hot path
        self.keyboard_controller.type(text)

    def handle_shutdown(self, _signal, _frame):
        pass

def main():
    try:
        WhisperDictationApp().run()
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt received, exiting...")
        os._exit(0)

if __name__ == "__main__":
    main()
