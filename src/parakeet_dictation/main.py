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
from .text_selection import TextSelection
from .logger_config import setup_logging
from mlx_lm import load as mlx_load, generate as mlx_generate
import argparse

# Set HuggingFace tokenizers parallelism warning off
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ---------- Logging: default to WARNING (lower overhead), override via env ----------
logger = setup_logging()
_log_env = os.getenv("PARAKEET_LOG", "").lower()
if _log_env in ("debug", "info", "warning", "error", "critical"):
    import logging as _logging
    logger.setLevel(getattr(_logging, _log_env.upper()))
else:
    import logging as _logging
    logger.setLevel(_logging.WARNING)

# Set up a global flag for handling SIGINT
exit_flag = False

def signal_handler(signum, frame):  # FIXED: accept (signum, frame)
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

        # NEW: Initialize Qwen (MLX) editor model (async)
        self.llm_model = None
        self.llm_tokenizer = None
        self.llm_ready = False
        self.llm_config = {
            "model_id": os.getenv("PARAKEET_LLM_MODEL", "mlx-community/Qwen2.5-1.5B-Instruct-4bit"),
            "max_tokens": int(os.getenv("PARAKEET_LLM_MAX_TOKENS", "192")),
            "temperature": float(os.getenv("PARAKEET_LLM_TEMP", "0.2")),
            "top_p": float(os.getenv("PARAKEET_LLM_TOP_P", "0.9")),
        }
        self.load_llm_thread = threading.Thread(target=self.load_llm, daemon=True)
        self.load_llm_thread.start()

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

    # NEW: Load Qwen (MLX) LLM editor
    def load_llm(self):
        if mlx_load is None or mlx_generate is None:
            logger.warning("mlx-lm not installed; local LLM edits disabled. `pip install mlx-lm` to enable.")
            return
        try:
            logger.info(f"Loading Qwen MLX model: {self.llm_config['model_id']}")
            # Many Qwen MLX models need trust_remote_code; eos token is usually set in tokenizer config.
            self.llm_model, self.llm_tokenizer = mlx_load(
                self.llm_config["model_id"],
                tokenizer_config={"trust_remote_code": True},
            )
            # Warm-up to prime kernels/caches
            try:
                _ = self.enhance_with_qwen("return the same text", "warmup")
                logger.info("Qwen MLX warm-up done")
            except Exception as we:
                logger.debug(f"Qwen warm-up skipped due to: {we}")
            self.llm_ready = True
            logger.info("Qwen MLX model ready for local edits")
        except Exception as e:
            logger.error(f"Failed to load Qwen MLX model: {e}")
            self.llm_ready = False

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

        # Always use temp file for transcription (model does not support BytesIO)
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

            # NEW: If there is selected text and local Qwen is ready → treat spoken text as instruction
            if selected_text and self.llm_ready:
                try:
                    self.status_item.title = "Status: Editing selection with Qwen..."
                    edited = self.enhance_with_qwen(text, selected_text)
                    if edited:
                        self.text_selector.replace_selected_text(edited)
                        self.status_item.title = f"Status: Edited: {edited[:30]}..."
                    else:
                        # Fallback to inserting raw transcription if model returned nothing
                        self.insert_text(text)
                        self.status_item.title = f"Status: Transcribed: {text[:30]}..."
                except Exception as e:
                    logger.error(f"Qwen edit error: {e}")
                    self.insert_text(text)
                    self.status_item.title = f"Status: Transcribed: {text[:30]}..."
            else:
                # No selection or LLM not ready → normal dictation insert
                self.insert_text(text)
                self.status_item.title = f"Status: Transcribed: {text[:30]}..."
        else:
            logger.warning("No speech detected")
            self.status_item.title = "Status: No speech detected"

    def insert_text(self, text):
        # Minimal logging in hot path
        self.keyboard_controller.type(text)

    # NEW: Local edit using Qwen (MLX)
    def enhance_with_qwen(self, instruction: str, text: str) -> str:
        """
        Use local Qwen (MLX) to apply `instruction` to `text`.
        Returns edited text (no explanations, no wrappers).
        """
        logger.debug(f"Enhancing with Qwen | instruction: {instruction}")
        if not (self.llm_model and self.llm_tokenizer):
            return ""

        system = (
            "You are a local text editor. Apply the instruction precisely. "
            "Output only the final edited text, with no extra formatting, no brackets, no explanations, and no wrappers."
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Instruction: {instruction}\nText:\n{text}"},
        ]

        # Try chat template; fallback to a simple prompt if unavailable
        try:
            prompt = self.llm_tokenizer.apply_chat_template(messages, add_generation_prompt=True)
            logger.debug("got prompt from llm tokenizer chat template")
        except Exception:
            prompt = f"{system}\n\nInstruction: {instruction}\nText:\n{text}\n\nEdited:"
            logger.debug("got prompt from simple chat template")
        logger.debug(prompt)
        out = mlx_generate(
            self.llm_model,
            self.llm_tokenizer,
            prompt=prompt,
            max_tokens=self.llm_config["max_tokens"],
            verbose=False,
        )
        logger.debug("Qwen output is " + str(out))
        return self._clean_llm_output(out)

    def _clean_llm_output(self, out: str) -> str:
        """
        Remove any <<<...>>> wrappers or similar from LLM output.
        """
        if not out:
            return ""
        # Remove <<< ... >>> wrappers
        import re
        cleaned = re.sub(r"^\s*<<<(.*?)>>>\s*/?s?\s*$", r"\1", out.strip(), flags=re.DOTALL)
        # Remove any remaining brackets or slashes
        cleaned = cleaned.strip().strip('<>').strip('/s').strip()
        return cleaned

    def handle_shutdown(self, _signal, _frame):
        pass

def main():
    parser = argparse.ArgumentParser(
        description="Parakeet Dictation: Speech-to-text and local LLM text editing for macOS.\n\nINSTRUCTIONS:\n\n- After launching, look for the 🎙️ icon in your macOS menu bar.\n- Press and HOLD Ctrl + Alt + A to start dictation. Release to transcribe.\n- If you select text before dictating, your spoken command will be used as an edit instruction for the selected text (requires local LLM).\n- If hotkeys do not work, check System Settings → Privacy & Security → Accessibility and Input Monitoring.\n- To quit, use the menu bar or press Ctrl+C in the terminal.\n- For more info, see: https://github.com/osadalakmal/parakeet-dictation\n\nOPTIONS:"
    )
    parser.add_argument('--version', action='version', version='parakeet-dictation 0.1.0')
    args = parser.parse_args()

    try:
        WhisperDictationApp().run()
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt received, exiting...")
        os._exit(0)

if __name__ == "__main__":
    main()
