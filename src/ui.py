#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UI Components for BookStorm

Accessible UI input and display components adapted from libstormgames.
"""

import pygame
import time


def get_input(speechEngine, prompt="Enter text:", text=""):
    """Display an accessible text input dialog using pygame.

    Features:
    - Speaks each character as typed
    - Left/Right arrows navigate and speak characters
    - Up/Down arrows read full text content
    - Backspace announces deletions
    - Enter submits, Escape cancels
    - Control key repeats the original prompt message
    - Fully accessible without screen reader dependency

    Args:
        speechEngine: SpeechEngine instance for speaking
        prompt (str): Prompt text to display (default: "Enter text:")
        text (str): Initial text in input box (default: "")

    Returns:
        str: User input text, or None if cancelled
    """

    # Initialize text buffer and cursor
    textBuffer = list(text)  # Use list for easier character manipulation
    cursorPos = len(textBuffer)  # Start at end of initial text

    # Announce the prompt and initial text as a single message
    if text:
        initialMessage = f"{prompt} Default text: {text}"
    else:
        initialMessage = f"{prompt} Empty text field"
    speechEngine.speak(initialMessage)

    # Clear any pending events
    pygame.event.clear()

    # Main input loop
    while True:
        event = pygame.event.wait()

        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_RETURN:
                # Submit the input
                result = ''.join(textBuffer)
                speechEngine.speak(f"Submitted: {result if result else 'empty'}")
                return result

            elif event.key == pygame.K_ESCAPE:
                # Cancel input
                speechEngine.speak("Cancelled")
                return None

            elif event.key == pygame.K_BACKSPACE:
                # Delete character before cursor
                if cursorPos > 0:
                    deletedChar = textBuffer.pop(cursorPos - 1)
                    cursorPos -= 1
                    speechEngine.speak(f"{deletedChar} deleted")
                else:
                    speechEngine.speak("Nothing to delete")

            elif event.key == pygame.K_DELETE:
                # Delete character at cursor
                if cursorPos < len(textBuffer):
                    deletedChar = textBuffer.pop(cursorPos)
                    speechEngine.speak(f"{deletedChar} deleted")
                else:
                    speechEngine.speak("Nothing to delete")

            elif event.key == pygame.K_LEFT:
                # Move cursor left and speak character
                if cursorPos > 0:
                    cursorPos -= 1
                    if cursorPos == 0:
                        speechEngine.speak("Beginning of text")
                    else:
                        speechEngine.speak(textBuffer[cursorPos])
                else:
                    speechEngine.speak("Beginning of text")

            elif event.key == pygame.K_RIGHT:
                # Move cursor right and speak character
                if cursorPos < len(textBuffer):
                    speechEngine.speak(textBuffer[cursorPos])
                    cursorPos += 1
                    if cursorPos == len(textBuffer):
                        speechEngine.speak("End of text")
                else:
                    speechEngine.speak("End of text")

            elif event.key == pygame.K_UP or event.key == pygame.K_DOWN:
                # Read entire text content
                if textBuffer:
                    speechEngine.speak(''.join(textBuffer))
                else:
                    speechEngine.speak("Empty text field")

            elif event.key == pygame.K_HOME:
                # Move to beginning
                cursorPos = 0
                speechEngine.speak("Beginning of text")

            elif event.key == pygame.K_END:
                # Move to end
                cursorPos = len(textBuffer)
                speechEngine.speak("End of text")

            elif event.key == pygame.K_LCTRL or event.key == pygame.K_RCTRL:
                # Repeat the original prompt message
                speechEngine.speak(initialMessage)

            else:
                # Handle regular character input
                if event.unicode and event.unicode.isprintable():
                    char = event.unicode
                    # Insert character at cursor position
                    textBuffer.insert(cursorPos, char)
                    cursorPos += 1

                    # Speak the character name
                    if char == ' ':
                        speechEngine.speak("space")
                    elif char == '\\':
                        speechEngine.speak("backslash")
                    elif char == '/':
                        speechEngine.speak("slash")
                    elif char == '!':
                        speechEngine.speak("exclamation mark")
                    elif char == '"':
                        speechEngine.speak("quotation mark")
                    elif char == '#':
                        speechEngine.speak("hash")
                    elif char == '$':
                        speechEngine.speak("dollar sign")
                    elif char == '%':
                        speechEngine.speak("percent")
                    elif char == '&':
                        speechEngine.speak("ampersand")
                    elif char == "'":
                        speechEngine.speak("apostrophe")
                    elif char == '(':
                        speechEngine.speak("left parenthesis")
                    elif char == ')':
                        speechEngine.speak("right parenthesis")
                    elif char == '*':
                        speechEngine.speak("asterisk")
                    elif char == '+':
                        speechEngine.speak("plus")
                    elif char == ',':
                        speechEngine.speak("comma")
                    elif char == '-':
                        speechEngine.speak("minus")
                    elif char == '.':
                        speechEngine.speak("period")
                    elif char == ':':
                        speechEngine.speak("colon")
                    elif char == ';':
                        speechEngine.speak("semicolon")
                    elif char == '<':
                        speechEngine.speak("less than")
                    elif char == '=':
                        speechEngine.speak("equals")
                    elif char == '>':
                        speechEngine.speak("greater than")
                    elif char == '?':
                        speechEngine.speak("question mark")
                    elif char == '@':
                        speechEngine.speak("at sign")
                    elif char == '[':
                        speechEngine.speak("left bracket")
                    elif char == ']':
                        speechEngine.speak("right bracket")
                    elif char == '^':
                        speechEngine.speak("caret")
                    elif char == '_':
                        speechEngine.speak("underscore")
                    elif char == '`':
                        speechEngine.speak("grave accent")
                    elif char == '{':
                        speechEngine.speak("left brace")
                    elif char == '|':
                        speechEngine.speak("pipe")
                    elif char == '}':
                        speechEngine.speak("right brace")
                    elif char == '~':
                        speechEngine.speak("tilde")
                    else:
                        # For regular letters, numbers, and other characters
                        speechEngine.speak(char)

        # Allow other events to be processed
        pygame.event.pump()
        pygame.event.clear()
        time.sleep(0.001)
