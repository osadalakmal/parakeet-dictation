#!/usr/bin/env python3
import os
import time
import tempfile
import threading
import pyaudio
import wave
import numpy as np
import rumps
from pynput import keyboard
from pynput.keyboard import Key, Controller
import faster_whisper
import signal
from text_selection import TextSelection
from bedrock_client import BedrockClient
from logger_config import setup_logging

logger = setup_logging()

# Set up a global flag for handling SIGINT
exit_flag = False

def signal_handler(sig, frame):
    """Global signal handler for graceful shutdown"""
    global exit_flag
    logger.info("Shutdown signal received, exiting gracefully...")
    exit_flag = True
    # Try to force exit if the app doesn't respond quickly
    threading.Timer(2.0, lambda: os._exit(0)).start()

# Set up graceful shutdown handling for interrupt and termination signals
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

class WhisperDictationApp(rumps.App):
    def __init__(self):
        super(WhisperDictationApp, self).__init__("🎙️", quit_button=rumps.MenuItem("Quit"))
        
        # Status item
        self.status_item = rumps.MenuItem("Status: Ready")
        
        # Add menu items - use a single menu item for toggling recording
        self.recording_menu_item = rumps.MenuItem("Start Recording")
        self.menu = [self.recording_menu_item, None, self.status_item]
        
        # Recording state
        self.recording = False
        self.audio = pyaudio.PyAudio()
        self.frames = []
        self.keyboard_controller = Controller()
        
        # Initialize text selection handler
        self.text_selector = TextSelection()
        
        # Initialize Bedrock client
        self.bedrock_client = BedrockClient()
        
        # Initialize Whisper model
        self.model = None
        self.load_model_thread = threading.Thread(target=self.load_model)
        self.load_model_thread.start()
        
        # Audio recording parameters
        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 16000
        self.chunk = 1024
        
        # Hotkey configuration - we'll listen for globe/fn key (vk=63)
        self.trigger_key = 63  # Key code for globe/fn key
        self.setup_global_monitor()
        
        # Show initial message
        logger.info("Started WhisperDictation app. Look for 🎙️ in your menu bar.")
        logger.info("Press and hold the Globe/Fn key (vk=63) to record. Release to transcribe.")
        logger.info("Press Ctrl+C to quit the application.")
        logger.info("You may need to grant this app accessibility permissions in System Preferences.")
        logger.info("Go to System Preferences → Security & Privacy → Privacy → Accessibility")
        logger.info("and add your terminal or the built app to the list.")
        
        # Test Bedrock connection
        if self.bedrock_client.is_available():
            logger.info("✓ Bedrock client initialized successfully")
        else:
            logger.warning("⚠ Bedrock client not available - text enhancement features disabled")
        
        # Start a watchdog thread to check for exit flag
        self.watchdog = threading.Thread(target=self.check_exit_flag, daemon=True)
        self.watchdog.start()
    
    def check_exit_flag(self):
        """Monitor the exit flag and terminate the app when set"""
        while True:
            if exit_flag:
                logger.info("Watchdog detected exit flag, shutting down...")
                self.cleanup()
                rumps.quit_application()
                os._exit(0)
                break
            time.sleep(0.5)
    
    def cleanup(self):
        """Clean up resources before exiting"""
        logger.info("Cleaning up resources...")
        # Stop recording if in progress
        if self.recording:
            self.recording = False
            if hasattr(self, 'recording_thread') and self.recording_thread.is_alive():
                self.recording_thread.join(timeout=1.0)
        
        # Close PyAudio
        if hasattr(self, 'audio'):
            try:
                self.audio.terminate()
            except:
                pass
    
    def load_model(self):
        self.title = "🎙️ (Loading...)"
        self.status_item.title = "Status: Loading Whisper model..."
        try:
            self.model = faster_whisper.WhisperModel("small.en")
            self.title = "🎙️"
            self.status_item.title = "Status: Ready"
            logger.info("Whisper model loaded successfully!")
        except Exception as e:
            self.title = "🎙️ (Error)"
            self.status_item.title = "Status: Error loading model"
            logger.error(f"Error loading model: {e}")
    
    def setup_global_monitor(self):
        # Create a separate thread to monitor for global key events
        self.key_monitor_thread = threading.Thread(target=self.monitor_keys)
        self.key_monitor_thread.daemon = True
        self.key_monitor_thread.start()
    
    def monitor_keys(self):
        # Track state of key 63 (Globe/Fn key)
        self.is_recording_with_key63 = False
        
        def on_press(key):
            # Removed logging for every key press; log only when target key is pressed
            if hasattr(key, 'vk') and key.vk == self.trigger_key:
                logger.debug(f"Target key (vk={key.vk}) pressed")
        
        def on_release(key):
            if hasattr(key, 'vk'):
                logger.debug(f"Key with vk={key.vk} released")
                if key.vk == self.trigger_key:
                    if not self.recording and not self.is_recording_with_key63:
                        logger.debug(f"Globe/Fn key (vk={key.vk}) released - STARTING recording")
                        self.is_recording_with_key63 = True
                        self.start_recording()
                    elif self.recording and self.is_recording_with_key63:
                        logger.debug(f"Globe/Fn key (vk={key.vk}) released - STOPPING recording")
                        self.is_recording_with_key63 = False
                        self.stop_recording()
        
        try:
            with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                logger.debug(f"Keyboard listener started - listening for key events")
                logger.debug(f"Target key is Globe/Fn key (vk={self.trigger_key})")
                logger.debug(f"Press and release the target key to control recording")
                listener.join()
        except Exception as e:
            logger.error(f"Error with keyboard listener: {e}")
            logger.error("Please check accessibility permissions in System Preferences")
    
    @rumps.clicked("Start Recording")  # This will be matched by title
    def toggle_recording(self, sender):
        if not self.recording:
            self.start_recording()
            sender.title = "Stop Recording"
        else:
            self.stop_recording()
            sender.title = "Start Recording"
    
    def start_recording(self):
        if not hasattr(self, 'model') or self.model is None:
            logger.warning("Model not loaded. Please wait for the model to finish loading.")
            self.status_item.title = "Status: Waiting for model to load"
            return
            
        self.frames = []
        self.recording = True
        
        # Update UI
        self.title = "🎙️ (Recording)"
        self.status_item.title = "Status: Recording..."
        logger.info("Recording started. Speak now...")
        
        # Start recording thread
        self.recording_thread = threading.Thread(target=self.record_audio)
        self.recording_thread.start()
    
    def stop_recording(self):
        self.recording = False
        if hasattr(self, 'recording_thread'):
            self.recording_thread.join()
        
        # Update UI
        self.title = "🎙️ (Transcribing)"
        self.status_item.title = "Status: Transcribing..."
        logger.info("Recording stopped. Transcribing...")
        
        # Process in background
        transcribe_thread = threading.Thread(target=self.process_recording)
        transcribe_thread.start()
    
    def process_recording(self):
        # Transcribe and insert text
        try:
            self.transcribe_audio()
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            self.status_item.title = "Status: Error during transcription"
        finally:
            self.title = "🎙️"  # Reset title
    
    def record_audio(self):
        stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            frames_per_buffer=self.chunk
        )
        
        while self.recording:
            data = stream.read(self.chunk)
            self.frames.append(data)
            
        stream.stop_stream()
        stream.close()
    
    def transcribe_audio(self):
        if not self.frames:
            self.title = "🎙️"
            self.status_item.title = "Status: No audio recorded"
            logger.warning("No audio recorded")
            return
            
        # Save the recorded audio to a temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_filename = temp_file.name
        
        with wave.open(temp_filename, 'wb') as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(self.audio.get_sample_size(self.format))
            wf.setframerate(self.rate)
            wf.writeframes(b''.join(self.frames))
        
        logger.debug("Audio saved to temporary file. Transcribing...")
        
        # Transcribe with Whisper
        try:
            segments, _ = self.model.transcribe(temp_filename, beam_size=5)
            
            text = ""
            for segment in segments:
                text += segment.text
            
            if text:
                #  What does this look like?
                selected_text = self.text_selector.get_selected_text()
                logger.debug(f"Selected text: {selected_text}")
                
                if selected_text and self.bedrock_client.is_available():
                    logger.info(f"Selected text detected: {selected_text[:50]}...")
                    logger.info(f"Voice instruction: {text}")
                    
                    try:
                        # Use Bedrock to enhance the selected text
                        self.status_item.title = "Status: Enhancing text with AI..."
                        enhanced_text = self.bedrock_client.enhance_text(text, selected_text)
                        
                        # Replace selected text with enhanced version
                        self.text_selector.replace_selected_text(enhanced_text)
                        logger.info(f"Enhanced text: {enhanced_text}")
                        self.status_item.title = f"Status: Enhanced: {enhanced_text[:30]}..."
                        
                    except Exception as e:
                        logger.error(f"Error enhancing text: {e}")
                        # Fallback to normal text insertion
                        self.insert_text(text)
                        logger.info(f"Transcription (fallback): {text}")
                        self.status_item.title = f"Status: Transcribed: {text[:30]}..."
                else:
                    # No selected text or Bedrock unavailable - normal insertion
                    self.insert_text(text)
                    logger.info(f"Transcription: {text}")
                    self.status_item.title = f"Status: Transcribed: {text[:30]}..."
            else:
                logger.warning("No speech detected")
                self.status_item.title = "Status: No speech detected"
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            self.status_item.title = "Status: Transcription error"
            raise
        finally:
            # Clean up the temporary file
            os.unlink(temp_filename)
    
    def insert_text(self, text):
        # Type text at cursor position without altering the clipboard
        logger.debug("Typing text at cursor position...")
        self.keyboard_controller.type(text)
        logger.debug("Text typed successfully")
    
    def handle_shutdown(self, _signal, _frame):
        """This method is no longer used with the global handler approach"""
        pass

# Wrap the main execution in a try-except to ensure clean exit
if __name__ == "__main__":
    try:
        WhisperDictationApp().run()
    except KeyboardInterrupt:
        logger.info("\nKeyboard interrupt received, exiting...")
        os._exit(0)