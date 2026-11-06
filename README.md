# BookStorm - Accessible Book Reader

BookStorm is a fully accessible book reader for electronic books and audiobooks, designed specifically for blind and visually impaired users. It provides seamless text-to-speech reading for text formats and native playback for audio formats, with real-time keyboard control and optional large print display.

## Features

- **Multiple Book Formats**: DAISY 2.02, DAISY 3, EPUB, PDF, TXT, and audio formats (M4B, M4A, MP3)
- **Text-to-Speech**: High-quality narration using piper-tts, system voices via speech-dispatcher, or active screen reader output
- **Audio Book Playback**: Native playback with chapter navigation and bookmarks
- **Audiobookshelf Integration**: Browse, stream, and download audiobooks from your Audiobookshelf server
- **Full Keyboard Control**: No mouse required - navigate with simple keyboard shortcuts
- **Bookmark System**: Auto-save progress and create named bookmarks with optional server sync
- **Large Print Display**: Optional 72-point text display for low vision users (1600x900 window)
- **Sleep Timer**: Automatic shutdown after 5-60 minutes for bedtime reading
- **Library Browser**: Browse your book collection with configurable library directory
- **Recent Books**: Quick access to your 10 most recently read books
- **WAV Export**: Convert text books to audio files split by chapter
- **Screen Reader Friendly**: Full keyboard control with spoken feedback and optional screen-reader reading mode

## Installation

### System Dependencies

**Arch Linux:**
```bash
yay -S --needed ffmpeg mpv python-mpv piper-tts-bin piper-voices-en-us python-beautifulsoup4 python-lxml python-mutagen python-pypdf python-pygame speech-dispatcher
```

**Debian/Ubuntu:**
```bash
sudo apt install --no-install-recommends ffmpeg mpv python3 python3-pip python3-beautifulsoup4 python3-lxml python3-mutagen python3-pygame python3-speechd speech-dispatcher
```

**Note:** Piper-TTS and voice packages may need to be installed manually on Debian/Ubuntu. Voice models should be organized by language:

```
/usr/share/piper-voices/
└── en/
    └── en_US/
        ├── hfc_male/
        │   └── medium/
        │       ├── en_US-hfc_male-medium.onnx
        │       └── en_US-hfc_male-medium.onnx.json
        └── hfc_female/
            └── medium/
                ├── en_US-hfc_female-medium.onnx
                └── en_US-hfc_female-medium.onnx.json
```

If you want screen-reader reading mode, install `dasbus` (`python-dasbus` system package on Arch, or `pip install dasbus`).

## Usage

### Interactive Reading

```bash
# Resume last book
python bookstorm.py

# Open a specific book
python bookstorm.py mybook.zip          # DAISY book
python bookstorm.py mybook.epub         # EPUB book
python bookstorm.py audiobook.m4b       # Audio book
```

### Export to Audio Files (Text Books Only)

```bash
# Export to WAV files (one per chapter)
python bookstorm.py mybook.zip --wav

# Custom output directory
python bookstorm.py mybook.epub --wav --output-dir ./audiobooks
```

## Keyboard Controls

### Playback Control

- **SPACE** - Start/pause/resume playback
- **n** - Next paragraph (text books) / Next chapter (audio books)
- **p** - Previous paragraph (text books) / Previous chapter (audio books)
- **SHIFT+N** - Next chapter (works during playback)
- **SHIFT+P** - Previous chapter (works during playback)
- **Page Up/Down** - Adjust speech rate (±10%)

### Navigation & Bookmarks

- **s** - Save bookmark at current position
- **k** - Bookmarks menu (view, jump to, or delete named bookmarks)
- **r** - Recent books menu (10 most recently accessed)
- **b** - Browse books (opens library directory if set)
- **a** - Audiobookshelf browser (if server configured)

### Menus & Settings

- **o** - Options menu (TTS engine, voice selection, display settings)
- **t** - Time remaining (if sleep timer active)
- **F1** or **?** - Help (displays keyboard shortcuts)
- **q or ESC** - Quit / Sleep timer menu

### Book Browser Controls

- **UP/DOWN** - Navigate items
- **Type letters** - Jump to the first item whose name starts with what you typed
- **ENTER** - Select book or enter directory
- **BACKSPACE/LEFT** - Go to parent directory
- **SHIFT+L** - Set current directory as default library location
- **ESC** - Cancel and return

## Audiobookshelf Integration

BookStorm can connect to an [Audiobookshelf](https://www.audiobookshelf.org/) server to browse, stream, and download audiobooks with full accessibility.

### Setup

1. Press **o** to open the options menu
2. Navigate to "Configure Audiobookshelf Server"
3. Enter your server URL, username, and password
4. Press **a** during reading to browse your Audiobookshelf library

### Features

- **Browse Libraries**: Navigate multiple libraries, series, and collections
- **Stream or Download**: Choose to stream directly or download for offline use
- **Progress Sync**: Streaming and linked local books sync playback progress to Audiobookshelf, including on quit
- **Bookmark Sync**: Named audiobook bookmarks sync to the server for linked Audiobookshelf items
- **Local-First**: If you already have a book locally, BookStorm uses it automatically
- **Type-to-Search**: In the Audiobookshelf browser, type letters to jump to matching libraries or books

### Stream vs Download

When you select a book from Audiobookshelf:

- **Stream**: Play directly from the server (requires internet, no disk space used)
- **Download**: Save to your library directory (works offline, syncs progress to server)

Books downloaded from Audiobookshelf are tagged with server metadata and automatically sync progress back to the server.

## Configuration

Settings are stored in `~/.config/stormux/bookstorm/settings.ini` and can be modified through the options menu (press **o**).

### TTS Settings

```ini
[TTS]
voice_model = /usr/share/piper-voices/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx
voice_dir = /usr/share/piper-voices/en/en_US
reader_engine = piper              # 'piper', 'speechd', or 'screenreader'
speechd_voice =                     # speech-dispatcher voice name
speechd_output_module =             # e.g., espeak-ng
speech_rate = 0                     # -100 to 100
```

### Reading Settings

```ini
[Reading]
auto_advance = true                 # Auto-advance to next paragraph
auto_save_bookmark = true           # Save position automatically
```

### Display Settings

```ini
[Display]
show_text = true                    # Show large print text display (72pt)
```

### Paths

```ini
[Paths]
last_book = /path/to/last/book.zip
books_directory = /home/user
library_directory = /home/user/library  # Default for book browser
```

### Audiobookshelf Settings

```ini
[Audiobookshelf]
server_url = https://abs.example.com
username = myuser
auto_sync = true                    # Auto-sync progress to server
sync_interval = 30                  # Seconds between progress syncs
```

## Bookmarks

Bookmarks are stored in `~/.bookstorm/bookmarks.db` (SQLite database).

### Auto-Save Bookmarks

BookStorm automatically saves your position when you press **s** or quit the application. When the current audiobook is linked to Audiobookshelf, that playback position is also synced to the server before shutdown. When you reopen a book, it resumes from where you left off.

### Named Bookmarks

Press **k** to open the bookmarks menu where you can:
- Create named bookmarks with custom labels
- Jump to any saved bookmark
- Delete bookmarks you no longer need
- View all bookmarks for the current book

For Audiobookshelf-linked audiobooks, BookStorm imports server bookmarks when the bookmarks menu opens and syncs newly created or deleted named bookmarks back to the server.

## Supported Formats

### Text Formats

- **DAISY 2.02**: NCC.html-based navigation with full structure
- **DAISY 3**: NCX + DTBook XML format
- **EPUB**: EPUB 2 and 3 with chapter detection
- **PDF**: Text extraction (quality depends on PDF structure)
- **TXT**: Plain text files with paragraph detection

### Audio Formats

- **MP3**: Natively supported (with ID3 CHAP chapter markers)
- **M4B/M4A**: Auto-transcoded with ffmpeg if needed
- **Any format ffmpeg supports**: Automatically transcoded to OGG on first load

**Note**: Transcoded files are cached in `~/.cache/bookstorm/audio/` for instant playback on subsequent loads.

### Chapter Markers

BookStorm extracts chapter markers from:
- **M4B/M4A**: MP4 metadata chapters
- **MP3**: ID3 CHAP frames (if present)
- **Fallback**: Treats entire file as single chapter if no markers found

## Troubleshooting

### Audio Book Won't Play (M4B/M4A)

This is normal - most pygame builds don't include AAC codec support. BookStorm will automatically transcode using ffmpeg:

1. Make sure ffmpeg is installed: `sudo pacman -S ffmpeg` (Arch) or `sudo apt install ffmpeg` (Ubuntu)
2. First playback will transcode (may take a moment)
3. Subsequent playbacks use the cached file (instant)

To clear the cache: `rm -rf ~/.cache/bookstorm/audio/`

### No Piper Voices Found

Install piper-tts and download voice models to `/usr/share/piper-voices/en/en_US/`. You can also select a different voice directory in the options menu.

### Book Has 0 Chapters

- Verify it's a valid DAISY format (should contain `.ncx` or `ncc.html`)
- DAISY books must be in ZIP format (not extracted folders)
- Check console output for parsing errors

### "No module named" Errors

```bash
# Install missing Python packages
pip install pygame beautifulsoup4 lxml python-speechd mutagen dasbus
```

## Architecture

BookStorm uses multiple reading engines for text books:

- **UI Feedback**: speech-dispatcher (instant feedback for all actions)
- **Book Reading (Piper-TTS mode)**: piper-tts → WAV → pygame.mixer (high quality)
- **Book Reading (Speech-Dispatcher mode)**: Separate speech-dispatcher session (faster, system voices)
- **Book Reading (Screen Reader mode)**: Orca/Cthulhu `PresentMessage` via D-Bus (speech + braille from your active screen reader)


For issues and feature requests, please visit https://git.stormux.org/storm/bookstorm
