#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Screen Reader Engine

Routes reading output through an active screen reader (Orca or Cthulhu)
using python-dasbus.
"""

import os
import subprocess
import threading
import time

try:
    from dasbus.connection import SessionMessageBus
    HAS_DASBUS = True
except ImportError:
    HAS_DASBUS = False

from .text_validator import is_valid_text


DBUS_ENV_LOCK = threading.Lock()


class ScreenReaderRemoteController:
    """D-Bus helper for a single screen reader service."""

    def __init__(self, serviceName, mainPath, processName, displayName):
        self.serviceName = serviceName
        self.mainPath = mainPath
        self.processName = processName
        self.displayName = displayName
        self.proxy = None
        self.speechProxy = None
        self.callLock = threading.Lock()
        self.pendingCallThread = None
        self.available = self._test_availability()

    def _call_with_timeout(self, func, timeoutSeconds=2):
        """Run a call with timeout to avoid blocking the app."""
        result = [None]
        exception = [None]

        def wrapper():
            try:
                result[0] = func()
            except Exception as error:
                exception[0] = error

        with self.callLock:
            # Avoid unbounded daemon thread buildup if a previous call is stuck.
            if self.pendingCallThread and self.pendingCallThread.is_alive():
                return None

            workerThread = threading.Thread(target=wrapper, daemon=True)
            self.pendingCallThread = workerThread

        workerThread.start()
        workerThread.join(timeout=timeoutSeconds)

        if workerThread.is_alive():
            return None

        with self.callLock:
            if self.pendingCallThread is workerThread:
                self.pendingCallThread = None

        if exception[0]:
            raise exception[0]
        return result[0]

    def _get_process_bus_address(self):
        """Read DBUS_SESSION_BUS_ADDRESS from the target process environment."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", self.processName],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1
            )
            if result.returncode != 0:
                return None

            processIds = [pid.strip() for pid in result.stdout.splitlines() if pid.strip()]
            for processId in processIds:
                try:
                    with open(f"/proc/{processId}/environ", "rb") as envFile:
                        rawData = envFile.read()
                    decodedData = rawData.decode("utf-8", errors="ignore")
                    for environmentVariable in decodedData.split("\0"):
                        if environmentVariable.startswith("DBUS_SESSION_BUS_ADDRESS="):
                            return environmentVariable.split("=", 1)[1]
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _test_availability(self):
        """Check if the remote D-Bus interface is reachable."""
        if not HAS_DASBUS:
            return False

        def test_connection():
            try:
                bus = SessionMessageBus()
                self.proxy = bus.get_proxy(self.serviceName, self.mainPath)
                self.proxy.ListCommands()
                self.speechProxy = bus.get_proxy(
                    self.serviceName,
                    f"{self.mainPath}/SpeechAndVerbosityManager"
                )
                return True
            except Exception:
                busAddress = self._get_process_bus_address()
                if not busAddress:
                    return False

                with DBUS_ENV_LOCK:
                    oldAddress = os.environ.get("DBUS_SESSION_BUS_ADDRESS")
                    try:
                        os.environ["DBUS_SESSION_BUS_ADDRESS"] = busAddress
                        bus = SessionMessageBus()
                        self.proxy = bus.get_proxy(self.serviceName, self.mainPath)
                        self.proxy.ListCommands()
                        self.speechProxy = bus.get_proxy(
                            self.serviceName,
                            f"{self.mainPath}/SpeechAndVerbosityManager"
                        )
                        return True
                    finally:
                        if oldAddress is not None:
                            os.environ["DBUS_SESSION_BUS_ADDRESS"] = oldAddress
                        elif "DBUS_SESSION_BUS_ADDRESS" in os.environ:
                            del os.environ["DBUS_SESSION_BUS_ADDRESS"]

        try:
            return bool(self._call_with_timeout(test_connection, timeoutSeconds=2))
        except Exception:
            return False

    def present_message(self, message):
        """Send a message to the screen reader for speech/braille presentation."""
        if not self.available or not self.proxy:
            return False

        try:
            result = self.proxy.PresentMessage(str(message))
            return bool(result) if isinstance(result, bool) else True
        except Exception:
            return False

    def interrupt_speech(self):
        """Interrupt current speech output."""
        if not self.available:
            return False

        try:
            if self.speechProxy:
                result = self.speechProxy.ExecuteCommand("InterruptSpeech", False)
                return bool(result) if isinstance(result, bool) else True

            if self.proxy:
                result = self.proxy.ExecuteCommand("InterruptSpeech", False)
                return bool(result) if isinstance(result, bool) else True
        except Exception:
            pass

        return False

    def is_responsive(self):
        """Return True if the controller still responds to a benign command."""
        if not self.available or not self.proxy:
            return False
        try:
            commands = self._call_with_timeout(lambda: self.proxy.ListCommands(), timeoutSeconds=1)
            return commands is not None
        except Exception:
            return False


class ScreenReaderEngine:
    """Book reading engine that speaks via active screen reader D-Bus APIs."""

    def __init__(self, quiet=False):
        self.speechLock = threading.Lock()
        self.isAvailable = False
        self.activeController = None
        self.availableControllers = []
        self.quiet = quiet

        self.isReading = False
        self.isPausedReading = False
        self.readingCallback = None
        self.currentText = ""
        self.speechRate = 0
        self.readingGeneration = 0

        self._initialize_controllers()

    def _initialize_controllers(self):
        """Discover available screen reader remote controllers."""
        if not HAS_DASBUS:
            if not self.quiet:
                print("Warning: python-dasbus not installed. Screen reader engine unavailable.")
            return

        controllerCandidates = [
            ScreenReaderRemoteController(
                serviceName="org.gnome.Orca.Service",
                mainPath="/org/gnome/Orca/Service",
                processName="orca",
                displayName="Orca"
            ),
            ScreenReaderRemoteController(
                serviceName="org.stormux.Cthulhu.Service",
                mainPath="/org/stormux/Cthulhu/Service",
                processName="cthulhu",
                displayName="Cthulhu"
            )
        ]

        self.availableControllers = [controller for controller in controllerCandidates if controller.available]
        self.activeController = self._select_active_controller()
        self.isAvailable = self.activeController is not None

        if not self.quiet:
            if self.activeController:
                print(f"Screen reader engine connected to {self.activeController.displayName}.")
            else:
                print("Warning: No supported screen reader D-Bus service detected (Orca/Cthulhu).")

    def _is_process_running(self, processName):
        """Return True when the process name is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", processName],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1
            )
            return result.returncode == 0 and bool(result.stdout.strip())
        except Exception:
            return False

    def _get_newest_running_pid(self, processName):
        """Return highest PID for a running process name, or -1."""
        try:
            result = subprocess.run(
                ["pgrep", "-x", processName],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=1
            )
            if result.returncode != 0:
                return -1
            pidValues = [int(pid.strip()) for pid in result.stdout.splitlines() if pid.strip().isdigit()]
            return max(pidValues) if pidValues else -1
        except Exception:
            return -1

    def _select_active_controller(self):
        """
        Pick the best controller:
        1) running service with newest PID
        2) any available service
        """
        if not self.availableControllers:
            return None

        runningControllers = [
            controller for controller in self.availableControllers
            if self._is_process_running(controller.processName)
        ]

        if len(runningControllers) == 1:
            return runningControllers[0]

        if len(runningControllers) > 1:
            newestController = None
            newestPid = -1
            for controller in runningControllers:
                controllerPid = self._get_newest_running_pid(controller.processName)
                if controllerPid > newestPid:
                    newestPid = controllerPid
                    newestController = controller
            if newestController:
                return newestController

        return self.availableControllers[0]

    def get_active_reader_name(self):
        """Return active screen reader display name."""
        if self.activeController:
            return self.activeController.displayName
        return "Unavailable"

    def is_available(self):
        """Check if screen reader engine is available."""
        return self.isAvailable

    def close(self):
        """Release resources and stop in-flight reading state."""
        self.cancel_reading(interrupt=False)

    def cleanup(self):
        """Cleanup resources - alias for close()."""
        self.close()

    def _estimate_duration_seconds(self, text):
        """Estimate speech duration for callback timing."""
        words = max(1, len(str(text).split()))
        adjustedWpm = max(70.0, min(360.0, 150.0 + (float(self.speechRate) * 1.8)))
        wordsDuration = (words / adjustedWpm) * 60.0
        punctuationCount = str(text).count(".") + str(text).count("!") + str(text).count("?")
        punctuationPause = punctuationCount * 0.2
        estimatedDuration = wordsDuration + punctuationPause + 0.25
        return max(1.0, estimatedDuration * 1.2)

    def _start_completion_timer(self, readingGeneration, text):
        """Start background completion timer and invoke callback on completion."""
        duration = self._estimate_duration_seconds(text)

        def completion_thread():
            elapsed = 0.0
            interval = 0.1

            while elapsed < duration:
                time.sleep(interval)
                elapsed += interval
                with self.speechLock:
                    if readingGeneration != self.readingGeneration:
                        return

            callback = None
            with self.speechLock:
                if readingGeneration != self.readingGeneration:
                    return
                self.isReading = False
                self.isPausedReading = False
                callback = self.readingCallback

            if callback:
                try:
                    callback('COMPLETED', readingGeneration)
                except TypeError as error:
                    errorText = str(error)
                    signatureMismatch = (
                        "positional argument" in errorText or
                        ("takes" in errorText and "given" in errorText)
                    )
                    if signatureMismatch:
                        callback('COMPLETED')
                    else:
                        print(f"Screen reader completion callback error: {error}")

        workerThread = threading.Thread(target=completion_thread, daemon=True)
        workerThread.start()

    def _try_switch_controller(self):
        """Try to switch to another available controller."""
        if not self.availableControllers:
            return False

        previousController = self.activeController
        candidates = []
        if not self.activeController:
            candidates = list(self.availableControllers)
        else:
            candidates = [
                controller for controller in self.availableControllers
                if controller is not self.activeController
            ]

        for controller in candidates:
            if not self._is_process_running(controller.processName):
                continue
            if not controller.is_responsive():
                continue
            self.activeController = controller
            self.isAvailable = True
            return True

        # Re-discover controllers in case the active reader restarted.
        self._initialize_controllers()
        if self.activeController and self.activeController is not previousController:
            return True

        self.isAvailable = self.activeController is not None
        return False

    def speak(self, text, interrupt=True):
        """
        Present text via active screen reader.

        Args:
            text: text to present
            interrupt: interrupt current speech first
        """
        if not self.isAvailable or not is_valid_text(text):
            return False

        with self.speechLock:
            activeController = self.activeController
            if not activeController:
                return False

            if interrupt:
                activeController.interrupt_speech()

            if activeController.present_message(str(text)):
                return True

            if self._try_switch_controller():
                activeController = self.activeController
                if activeController:
                    if interrupt:
                        activeController.interrupt_speech()
                    if activeController.present_message(str(text)):
                        return True

        return False

    def stop(self):
        """Stop current speech output."""
        self.cancel_reading()

    def speak_reading(self, text, callback=None):
        """
        Present reading text with completion callback.

        Args:
            text: text to read
            callback: called with 'COMPLETED' when reading is estimated done
        """
        if not self.isAvailable or not is_valid_text(text):
            return

        textStr = str(text).replace('\n', ' ').replace('\r', ' ')
        textStr = " ".join(textStr.split()).strip()
        if not textStr:
            return

        with self.speechLock:
            self.readingGeneration += 1
            currentGeneration = self.readingGeneration
            self.currentText = textStr
            self.readingCallback = callback
            self.isReading = True
            self.isPausedReading = False

        if not self.speak(textStr, interrupt=True):
            with self.speechLock:
                if currentGeneration == self.readingGeneration:
                    self.isReading = False
            return

        with self.speechLock:
            generationStillCurrent = (
                currentGeneration == self.readingGeneration and
                self.isReading and
                not self.isPausedReading
            )
        if not generationStillCurrent:
            return

        self._start_completion_timer(currentGeneration, textStr)

    def pause_reading(self):
        """Pause reading by interrupting speech and marking paused state."""
        with self.speechLock:
            if not self.isReading:
                return
            self.readingGeneration += 1
            self.isReading = False
            self.isPausedReading = True

        if self.activeController:
            self.activeController.interrupt_speech()

    def resume_reading(self):
        """Resume reading from paragraph start."""
        with self.speechLock:
            if not self.isPausedReading or not self.currentText:
                return
            callback = self.readingCallback
            textToResume = self.currentText
            self.isPausedReading = False

        self.speak_reading(textToResume, callback=callback)

    def cancel_reading(self, interrupt=True):
        """Cancel current reading."""
        with self.speechLock:
            self.readingGeneration += 1
            self.isReading = False
            self.isPausedReading = False
            self.readingCallback = None

        if interrupt and self.activeController:
            self.activeController.interrupt_speech()

    def is_reading_active(self):
        """Check if currently reading (not paused)."""
        return self.isReading and not self.isPausedReading

    def is_reading_paused(self):
        """Check if reading is paused."""
        return self.isPausedReading

    def is_completion_token_current(self, tokenValue):
        """Return True when completion token still matches active generation."""
        try:
            tokenInt = int(tokenValue)
        except Exception:
            return False
        with self.speechLock:
            return tokenInt == self.readingGeneration

    def set_rate(self, rate):
        """Store virtual speech rate used for completion timing estimation."""
        try:
            self.speechRate = max(-100, min(100, int(rate)))
        except Exception:
            self.speechRate = 0

    def set_voice(self, voiceName):
        """Compatibility no-op for shared engine API."""
        _ = voiceName

    def list_voices(self):
        """Compatibility no-op for shared engine API."""
        return []

    def list_output_modules(self):
        """Compatibility no-op for shared engine API."""
        return []

    def set_output_module(self, moduleName):
        """Compatibility no-op for shared engine API."""
        _ = moduleName
