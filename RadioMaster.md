Product Requirements Document (PRD)
RadioMaster — Accessible Portable Internet Radio Player
 
1. Overview
RadioMaster is a fully accessible, portable internet radio application built with Python and wxPython. It enables users to browse, search, play, record, and schedule internet radio streams sourced from the Radio Browser free database. The application ships with a custom media player (bundled FFmpeg), supports VPN usage, large stream buffers, and rich metadata tagging via Deezer (primary) and MusicBrainz (secondary).
 
2. Goals & Objectives
#
Goal
G1
Fully screen-reader accessible UI (NVDA, JAWS, VoiceOver)
G2
Runs portably — no installation required; all dependencies bundled
G3
Custom media playback engine (no VLC dependency)
G4
Rich metadata and ID3 tagging for recordings
G5
Flexible scheduling of recordings
G6
Favourites and custom station management
 
3. Target Users
• Blind / visually impaired users (accessibility is a first-class requirement)
• Radio enthusiasts who want portable, offline-capable radio recording
• Podcasters / archivists who schedule and tag recordings automatically
 
4. Technical Stack
Component
Technology
Language
Python 3.10+
GUI Framework
wxPython 4.x (Phoenix)
Media Engine
Custom player using FFmpeg (bundled) via subprocess + custom buffering
Audio Playback
pyaudio or sounddevice + pydub for decoding
Station Database
Radio Browser API
Metadata (Primary)
Deezer API
Metadata (Secondary)
MusicBrainz API
ID3 Tagging
mutagen library
HTTP Requests
requests
Scheduling
APScheduler or custom scheduler
Packaging
PyInstaller (portable mode)
 
5. Architecture Overview
 
RadioMaster/
├── radiomaster/
│   ├── main.py                  # Entry point
│   ├── app.py                   # wx.App subclass
│   ├── ui/
│   │   ├── main_frame.py        # Main window (Listbook + panels)
│   │   ├── radio_panel.py       # Radio station browsing & playback
│   │   ├── scheduler_panel.py   # Recording scheduler
│   │   ├── favourites_panel.py  # Favourites management
│   │   ├── settings_panel.py    # Settings (VPN, soundcard, buffer)
│   │   └── widgets/
│   │       ├── player_controls.py   # Play/Pause/Stop/Record/Mute
│   │       ├── station_tree.py      # TreeCtrl for stations
│   │       └── now_playing.py       # Status bar + edit boxes
│   ├── core/
│   │   ├── player.py            # Custom FFmpeg-based player engine
│   │   ├── recorder.py          # Stream recording + ID3 tagging
│   │   ├── stream_buffer.py     # Large buffer management
│   │   ├── station_api.py       # Radio Browser API client
│   │   ├── metadata.py          # Deezer + MusicBrainz lookup
│   │   ├── tagger.py            # ID3 tag writing (mutagen)
│   │   ├── scheduler.py         # Recording schedule engine
│   │   ├── favourites.py        # Favourites storage (JSON/SQLite)
│   │   ├── custom_stations.py   # User-added station management
│   │   └── soundcard.py         # Soundcard enumeration & selection
│   ├── utils/
│   │   ├── config.py            # Portable config (INI/JSON in app dir)
│   │   ├── paths.py             # Portable path resolution
│   │   └── ffmpeg.py            # Bundled FFmpeg path resolution
│   └── resources/
│       └── ffmpeg/              # Bundled FFmpeg binaries
├── recordings/                   # Created at runtime
│   └── <StationName>/
│       └── Artist - Title.mp3
├── config.json                   # Portable config file
└── RadioMaster.exe               # Portable executable
 
6. UI Specification
6.1 Main Window — Listbook Control
The main window uses a wx.Listbook as the top-level navigation container. This allows future pages (Podcasts, Video Sites, etc.) to be added as new book pages.
 
┌─────────────────────────────────────────────────────────┐
│  RadioMaster                                        [_□×]│
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  📻 Radio │   [Search: ___________] [Search]             │
│  ⭐ Favs  │                                              │
│  📅 Sched │   ┌─ TreeView ──────────────────────────┐    │
│  ⚙️ Sett.  │   │ ▼ By Genre                        │    │
│           │   │   ▼ Rock                           │    │
│           │   │     • Station A                    │    │
│           │   │     • Station B                    │    │
│           │   │ ▼ By Country                       │    │
│           │   │   ▼ United States                  │    │
│           │   │     • Station C                    │    │
│           │   │ ▼ By Language                       │    │
│           │   │ ▼ By Network                       │    │
│           │   └────────────────────────────────────┘    │
│           │                                              │
│           │   Station: [____________________] (readonly) │
│           │   Now Playing: [__________________] (readonly)│
│           │                                              │
│           │   [▶ Play] [⏹ Stop] [● Record Off] [🔇 Mute Off]│
│           │                                              │
│           ├──────────────────────────────────────────────┤
│           │ Status: Connected | 128 kbps | MP3 | Buffer: 85%│
│           └──────────────────────────────────────────────┘
└──────────┴──────────────────────────────────────────────┘
6.2 Radio Page (Primary Page)
Component
wxPython Widget
Accessibility Notes
Station Tree
wx.TreeCtrl
Keyboard navigable, screen-reader announces hierarchy (Genre/Country/Language/Network → Stations)
Search Bar
wx.TextCtrl + wx.Button
Search by name, language, network, country, genre
Station Name
wx.TextCtrl (read-only)
Shows currently selected/playing station name
Now Playing
wx.TextCtrl (read-only)
Shows current song title from metadata
Play/Pause Button
wx.Button
Label toggles: "▶ Play" ↔ "⏸ Pause"
Stop Button
wx.Button
Label: "⏹ Stop"
Record Button
wx.Button
Label toggles: "● Record Off" ↔ "● Recording On"
Mute Button
wx.Button
Label toggles: "🔇 Mute Off" ↔ "🔇 Mute On"
Status Bar
wx.StatusBar
Shows: connection status, bitrate, format, buffer level
Add Custom Station
wx.Button → Dialog
Opens a form to add a custom station URL + metadata
Save to Favourites
wx.Button or context menu
Adds selected station to favourites
6.3 Favourites Page
• List of saved favourite stations
• Double-click or Enter to play immediately
• Remove from favourites
• Reorder favourites
6.4 Scheduler Page
A flexible recording scheduler:
Feature
Description
One-time recording
Pick a specific date + start time + duration
Daily recording
Repeat every day at a set time
Weekly recording
Pick day(s) of the week (e.g., every Monday)
Nth weekday of month
e.g., "Every 3rd Monday" — schedule by ordinal weekday
Custom interval
e.g., every 2 weeks, every 10 days
Station selector
Choose which station to record
Output format
MP3, AAC, FLAC, OGG, WAV
Duration
Set recording length (or "until stop")
Schedule list
View all scheduled recordings with enable/disable toggle
Conflict detection
Warn if two recordings overlap
Scheduler UI Layout:
 
┌─ Schedule List ──────────────────┐  ┌─ New Schedule ──────────┐
│ ☑ Mon 09:00 — BBC Radio 1 (60m) │  │ Station: [dropdown]      │
│ ☑ 3rd Mon 20:00 — Jazz FM (90m) │  │ Type: [One-time ▼]      │
│ ☑ Daily 06:00 — NPR News (30m) │  │ Start: [date] [time]     │
│ ☐ Sat 22:00 — Club Station (2h) │  │ Duration: [__] minutes   │
│                                  │  │ Repeat: [checkboxes]     │
│ [Add] [Edit] [Delete] [Enable]   │  │ Ordinal: [1st/2nd/3rd/4th]│
│                                  │  │ Weekday: [Mon…Sun]       │
└──────────────────────────────────┘  │ [Save Schedule]          │
                                       └──────────────────────────┘
6.5 Settings Page
Setting
Description
Soundcard Selection
Dropdown listing all available audio output devices
Buffer Size
Configurable stream buffer size (e.g., 10s–300s) to avoid buffering
VPN Support
Option to route traffic through a VPN interface (SOCKS5/HTTP proxy or system VPN toggle)
FFmpeg Path
Auto-resolved to bundled FFmpeg; allow override
Metadata Sources
Toggle Deezer (primary) / MusicBrainz (secondary)
Recording Format
Default output format (MP3, FLAC, etc.)
Theme
High-contrast / accessible themes
Language
UI language selection
 
7. Core Feature Specifications
7.1 Custom Media Player (No VLC)
 
┌───────────────┐     ┌──────────────┐     ┌──────────────┐
│  HTTP Stream  │────▶│  FFmpeg       │────▶│  Audio Output│
│  (Icecast/    │     │  (subprocess) │     │  (PyAudio/   │
│   Shoutcast)  │     │  Decodes to   │     │   sounddevice)│
│               │     │  PCM pipe     │     │              │
└───────────────┘     └──────────────┘     └──────────────┘
                              │
                              ▼
                      ┌──────────────┐
                      │  Buffer      │
                      │  (Ring buf   │
                      │   10–300s)   │
                      └──────────────┘
• FFmpeg runs as a subprocess, decoding the stream to raw PCM
• PCM data is fed through a ring buffer (configurable size)
• PyAudio or sounddevice reads from the buffer and plays to the selected soundcard
• Mute = suppress audio output (zero-amplitude) without stopping the stream
• Pause = stop reading from buffer (buffer continues to fill)
• Stop = terminate FFmpeg subprocess and clear buffer
• Record = tee the FFmpeg output to a file writer simultaneously
7.2 Station Data Source — Radio Browser API
• Base URL: https://de1.api.radio-browser.info/json/
• Endpoints used:
◦ /json/stations/bygenre/{genre}
◦ /json/stations/bycountry/{country}
◦ /json/stations/bylanguage/{language}
◦ /json/stations/search?name={query}
◦ /json/stations/topvote/100 (for popular stations)
• Tree population: Fetch all stations, then organize into tree nodes:
◦ By Genre → genre → stations
◦ By Country → country → stations
◦ By Language → language → stations
◦ By Network → network → stations
• Caching: Cache station list locally (refreshable) for offline browsing
7.3 Metadata Lookup (Deezer → MusicBrainz)
Python
 
# Pseudocode for metadata resolution
def get_track_info(station_name, now_playing_text):
    # Step 1: Try Deezer
    result = deezer_search(now_playing_text)
    if result:
        return {
            "artist": result["artist"]["name"],
            "title": result["title"],
            "album": result["album"]["title"],
            "cover_art": result["album"]["cover_big"],
            "deezer_id": result["id"]
        }

    # Step 2: Fallback to MusicBrainz
    result = musicbrainz_search(now_playing_text)
    if result:
        return {
            "artist": result["artist-credit"][0]["name"],
            "title": result["title"],
            "album": result["release"]["title"],
            "mbid": result["id"]
        }

    # Step 3: Fallback to stream metadata (ICY tags)
    return parse_icy_metadata(now_playing_text)
• Deezer API: https://api.deezer.com/search?q={query} — no API key required
• MusicBrainz API: https://musicbrainz.org/ws/2/recording?query={query}&fmt=json
• Polls the stream's ICY metadata (Shoutcast/Icecast StreamTitle tag) for the currently playing track
• Cross-references with Deezer/MusicBrainz for rich metadata
7.4 Stream Format & Bitrate Capture
• FFmpeg's -i (input probe) or ffprobe is used to detect:
◦ Codec/Format: MP3, AAC, OGG, FLAC, etc.
◦ Bitrate: e.g., 128 kbps, 256 kbps
◦ Sample rate: e.g., 44100 Hz
• Displayed in the status bar:
 
Status: Playing | 128 kbps | MP3 | 44100 Hz | Buffer: 85%
7.5 Recording & File Management
Directory structure:
 
RadioMaster/
├── recordings/
│   ├── BBC Radio 1/
│   │   ├── Queen - Bohemian Rhapsody.mp3
│   │   ├── The Beatles - Let It Be.mp3
│   ├── Jazz FM/
│   │   ├── Miles Davis - So What.mp3
│   ├── NPR News/
│   │   ├── Unknown - NPR News Broadcast 2024-01-15.mp3
Naming convention:
• Primary: {Artist} - {Title}.{ext}
• Fallback (if metadata unavailable): {Station} - {YYYY-MM-DD HH-MM}.{ext}
ID3 Tag Writing (via mutagen):
Python
 
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, APIC

def tag_file(filepath, metadata, station_name):
    audio = ID3()
    audio["TIT2"] = TIT2(encoding=3, text=metadata["title"])       # Title
    audio["TPE1"] = TPE1(encoding=3, text=metadata["artist"])       # Artist
    audio["TALB"] = TALB(encoding=3, text=metadata.get("album", station_name))  # Album
    audio["TYER"] = TYER(encoding=3, text=str(datetime.now().year)) # Year
    if metadata.get("cover_art"):
        audio["APIC"] = APIC(encoding=3, mime="image/jpeg",
                             type=3, desc="Cover",
                             data=download_image(metadata["cover_art"]))
    audio.save(filepath)
7.6 Favourites System
• Stored in favourites.json (portable, in app directory)
• Each favourite contains:
Json
 
{
  "name": "BBC Radio 1",
  "url": "https://stream-url...",
  "favicon": "https://...",
  "tags": ["pop", "uk"],
  "country": "United Kingdom",
  "language": "english",
  "network": "BBC"
}
• Quick-access from Favourites page or a context menu in the tree
7.7 Custom Stations
• User can add stations not in the Radio Browser database
• Form fields: Name, URL, Genre, Country, Language, Network, Bitrate
• Stored in custom_stations.json
• Merged into the tree view alongside database stations (visually distinguished, e.g., with a ★ prefix)
7.8 VPN Support
• Proxy approach: Application supports SOCKS5 / HTTP proxy settings:
◦ All HTTP requests (streaming + API) route through the configured proxy
◦ Configurable in Settings page
• System VPN detection: Check for active VPN interface and display status in the status bar
• Implementation:
Python
 
proxies = {
    "http": "socks5://127.0.0.1:1080",
    "https": "socks5://127.0.0.1:1080"
}
# Used by requests library and FFmpeg (via -headers or environment)
7.9 Soundcard Selection
• Enumerate available audio output devices using sounddevice.query_devices()
• User selects output device in Settings
• Player routes audio to the selected device:
Python
 
import sounddevice as sd
sd.OutputStream(device=device_id, samplerate=44100, channels=2)
7.10 Large Buffer Management
• Ring buffer
 
 Product Requirements Document (PRD)
RadioMaster — Accessible Portable Internet Radio Player
 
1. Overview
RadioMaster is a fully accessible, portable internet radio application built with Python and wxPython. It enables users to browse, search, play, record, and schedule internet radio streams sourced from the Radio Browser free database. The application ships with a custom media player (bundled FFmpeg), supports VPN usage, large stream buffers, and rich metadata tagging via Deezer (primary) and MusicBrainz (secondary).
 
2. Goals & Objectives
#
Goal
G1
Fully screen-reader accessible UI (NVDA, JAWS, VoiceOver)
G2
Runs portably — no installation required; all dependencies bundled
G3
Custom media playback engine (no VLC dependency)
G4
Rich metadata and ID3 tagging for recordings
G5
Flexible scheduling of recordings
G6
Favourites and custom station management
 
3. Target Users
• Blind / visually impaired users (accessibility is a first-class requirement)
• Radio enthusiasts who want portable, offline-capable radio recording
• Podcasters / archivists who schedule and tag recordings automatically
 
4. Technical Stack
Component
Technology
Language
Python 3.10+
GUI Framework
wxPython 4.x (Phoenix)
Media Engine
Custom player using FFmpeg (bundled) via subprocess + custom buffering
Audio Playback
pyaudio or sounddevice + pydub for decoding
Station Database
Radio Browser API
Metadata (Primary)
Deezer API
Metadata (Secondary)
MusicBrainz API
ID3 Tagging
mutagen library
HTTP Requests
requests
Scheduling
APScheduler or custom scheduler
Packaging
PyInstaller (portable mode)
 
5. Architecture Overview
 
RadioMaster/
├── radiomaster/
│   ├── main.py                  # Entry point
│   ├── app.py                   # wx.App subclass
│   ├── ui/
│   │   ├── main_frame.py        # Main window (Listbook + panels)
│   │   ├── radio_panel.py       # Radio station browsing & playback
│   │   ├── scheduler_panel.py   # Recording scheduler
│   │   ├── favourites_panel.py  # Favourites management
│   │   ├── settings_panel.py    # Settings (VPN, soundcard, buffer)
│   │   └── widgets/
│   │       ├── player_controls.py   # Play/Pause/Stop/Record/Mute
│   │       ├── station_tree.py      # TreeCtrl for stations
│   │       └── now_playing.py       # Status bar + edit boxes
│   ├── core/
│   │   ├── player.py            # Custom FFmpeg-based player engine
│   │   ├── recorder.py          # Stream recording + ID3 tagging
│   │   ├── stream_buffer.py     # Large buffer management
│   │   ├── station_api.py       # Radio Browser API client
│   │   ├── metadata.py          # Deezer + MusicBrainz lookup
│   │   ├── tagger.py            # ID3 tag writing (mutagen)
│   │   ├── scheduler.py         # Recording schedule engine
│   │   ├── favourites.py        # Favourites storage (JSON/SQLite)
│   │   ├── custom_stations.py   # User-added station management
│   │   └── soundcard.py         # Soundcard enumeration & selection
│   ├── utils/
│   │   ├── config.py            # Portable config (INI/JSON in app dir)
│   │   ├── paths.py             # Portable path resolution
│   │   └── ffmpeg.py            # Bundled FFmpeg path resolution
│   └── resources/
│       └── ffmpeg/              # Bundled FFmpeg binaries
├── recordings/                   # Created at runtime
│   └── <StationName>/
│       └── Artist - Title.mp3
├── config.json                   # Portable config file
└── RadioMaster.exe               # Portable executable
 
6. UI Specification
6.1 Main Window — Listbook Control
The main window uses a wx.Listbook as the top-level navigation container. This allows future pages (Podcasts, Video Sites, etc.) to be added as new book pages.
 
┌─────────────────────────────────────────────────────────┐
│  RadioMaster                                        [_□×]│
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│  📻 Radio │   [Search: ___________] [Search]             │
│  ⭐ Favs  │                                              │
│  📅 Sched │   ┌─ TreeView ──────────────────────────┐    │
│  ⚙️ Sett.  │   │ ▼ By Genre                        │    │
│           │   │   ▼ Rock                           │    │
│           │   │     • Station A                    │    │
│           │   │     • Station B                    │    │
│           │   │ ▼ By Country                       │    │
│           │   │   ▼ United States                  │    │
│           │   │     • Station C                    │    │
│           │   │ ▼ By Language                       │    │
│           │   │ ▼ By Network                       │    │
│           │   └────────────────────────────────────┘    │
│           │                                              │
│           │   Station: [____________________] (readonly) │
│           │   Now Playing: [__________________] (readonly)│
│           │                                              │
│           │   [▶ Play] [⏹ Stop] [● Record Off] [🔇 Mute Off]│
│           │                                              │
│           ├──────────────────────────────────────────────┤
│           │ Status: Connected | 128 kbps | MP3 | Buffer: 85%│
│           └──────────────────────────────────────────────┘
└──────────┴──────────────────────────────────────────────┘
6.2 Radio Page (Primary Page)
Component
wxPython Widget
Accessibility Notes
Station Tree
wx.TreeCtrl
Keyboard navigable, screen-reader announces hierarchy (Genre/Country/Language/Network → Stations)
Search Bar
wx.TextCtrl + wx.Button
Search by name, language, network, country, genre
Station Name
wx.TextCtrl (read-only)
Shows currently selected/playing station name
Now Playing
wx.TextCtrl (read-only)
Shows current song title from metadata
Play/Pause Button
wx.Button
Label toggles: "▶ Play" ↔ "⏸ Pause"
Stop Button
wx.Button
Label: "⏹ Stop"
Record Button
wx.Button
Label toggles: "● Record Off" ↔ "● Recording On"
Mute Button
wx.Button
Label toggles: "🔇 Mute Off" ↔ "🔇 Mute On"
Status Bar
wx.StatusBar
Shows: connection status, bitrate, format, buffer level
Add Custom Station
wx.Button → Dialog
Opens a form to add a custom station URL + metadata
Save to Favourites
wx.Button or context menu
Adds selected station to favourites
6.3 Favourites Page
• List of saved favourite stations
• Double-click or Enter to play immediately
• Remove from favourites
• Reorder favourites
6.4 Scheduler Page
A flexible recording scheduler:
Feature
Description
One-time recording
Pick a specific date + start time + duration
Daily recording
Repeat every day at a set time
Weekly recording
Pick day(s) of the week (e.g., every Monday)
Nth weekday of month
e.g., "Every 3rd Monday" — schedule by ordinal weekday
Custom interval
e.g., every 2 weeks, every 10 days
Station selector
Choose which station to record
Output format
MP3, AAC, FLAC, OGG, WAV
Duration
Set recording length (or "until stop")
Schedule list
View all scheduled recordings with enable/disable toggle
Conflict detection
Warn if two recordings overlap
Scheduler UI Layout:
 
┌─ Schedule List ──────────────────┐  ┌─ New Schedule ──────────┐
│ ☑ Mon 09:00 — BBC Radio 1 (60m) │  │ Station: [dropdown]      │
│ ☑ 3rd Mon 20:00 — Jazz FM (90m) │  │ Type: [One-time ▼]      │
│ ☑ Daily 06:00 — NPR News (30m) │  │ Start: [date] [time]     │
│ ☐ Sat 22:00 — Club Station (2h) │  │ Duration: [__] minutes   │
│                                  │  │ Repeat: [checkboxes]     │
│ [Add] [Edit] [Delete] [Enable]   │  │ Ordinal: [1st/2nd/3rd/4th]│
│                                  │  │ Weekday: [Mon…Sun]       │
└──────────────────────────────────┘  │ [Save Schedule]          │
                                       └──────────────────────────┘
6.5 Settings Page
Setting
Description
Soundcard Selection
Dropdown listing all available audio output devices
Buffer Size
Configurable stream buffer size (e.g., 10s–300s) to avoid buffering
VPN Support
Option to route traffic through a VPN interface (SOCKS5/HTTP proxy or system VPN toggle)
FFmpeg Path
Auto-resolved to bundled FFmpeg; allow override
Metadata Sources
Toggle Deezer (primary) / MusicBrainz (secondary)
Recording Format
Default output format (MP3, FLAC, etc.)
Theme
High-contrast / accessible themes
Language
UI language selection
 
7. Core Feature Specifications
7.1 Custom Media Player (No VLC)
 
┌───────────────┐     ┌──────────────┐     ┌──────────────┐
│  HTTP Stream  │────▶│  FFmpeg       │────▶│  Audio Output│
│  (Icecast/    │     │  (subprocess) │     │  (PyAudio/   │
│   Shoutcast)  │     │  Decodes to   │     │   sounddevice)│
│               │     │  PCM pipe     │     │              │
└───────────────┘     └──────────────┘     └──────────────┘
                              │
                              ▼
                      ┌──────────────┐
                      │  Buffer      │
                      │  (Ring buf   │
                      │   10–300s)   │
                      └──────────────┘
• FFmpeg runs as a subprocess, decoding the stream to raw PCM
• PCM data is fed through a ring buffer (configurable size)
• PyAudio or sounddevice reads from the buffer and plays to the selected soundcard
• Mute = suppress audio output (zero-amplitude) without stopping the stream
• Pause = stop reading from buffer (buffer continues to fill)
• Stop = terminate FFmpeg subprocess and clear buffer
• Record = tee the FFmpeg output to a file writer simultaneously
7.2 Station Data Source — Radio Browser API
• Base URL: https://de1.api.radio-browser.info/json/
• Endpoints used:
◦ /json/stations/bygenre/{genre}
◦ /json/stations/bycountry/{country}
◦ /json/stations/bylanguage/{language}
◦ /json/stations/search?name={query}
◦ /json/stations/topvote/100 (for popular stations)
• Tree population: Fetch all stations, then organize into tree nodes:
◦ By Genre → genre → stations
◦ By Country → country → stations
◦ By Language → language → stations
◦ By Network → network → stations
• Caching: Cache station list locally (refreshable) for offline browsing
7.3 Metadata Lookup (Deezer → MusicBrainz)
Python
 
# Pseudocode for metadata resolution
def get_track_info(station_name, now_playing_text):
    # Step 1: Try Deezer
    result = deezer_search(now_playing_text)
    if result:
        return {
            "artist": result["artist"]["name"],
            "title": result["title"],
            "album": result["album"]["title"],
            "cover_art": result["album"]["cover_big"],
            "deezer_id": result["id"]
        }

    # Step 2: Fallback to MusicBrainz
    result = musicbrainz_search(now_playing_text)
    if result:
        return {
            "artist": result["artist-credit"][0]["name"],
            "title": result["title"],
            "album": result["release"]["title"],
            "mbid": result["id"]
        }

    # Step 3: Fallback to stream metadata (ICY tags)
    return parse_icy_metadata(now_playing_text)
• Deezer API: https://api.deezer.com/search?q={query} — no API key required
• MusicBrainz API: https://musicbrainz.org/ws/2/recording?query={query}&fmt=json
• Polls the stream's ICY metadata (Shoutcast/Icecast StreamTitle tag) for the currently playing track
• Cross-references with Deezer/MusicBrainz for rich metadata
7.4 Stream Format & Bitrate Capture
• FFmpeg's -i (input probe) or ffprobe is used to detect:
◦ Codec/Format: MP3, AAC, OGG, FLAC, etc.
◦ Bitrate: e.g., 128 kbps, 256 kbps
◦ Sample rate: e.g., 44100 Hz
• Displayed in the status bar:
 
Status: Playing | 128 kbps | MP3 | 44100 Hz | Buffer: 85%
7.5 Recording & File Management
Directory structure:
 
RadioMaster/
├── recordings/
│   ├── BBC Radio 1/
│   │   ├── Queen - Bohemian Rhapsody.mp3
│   │   ├── The Beatles - Let It Be.mp3
│   ├── Jazz FM/
│   │   ├── Miles Davis - So What.mp3
│   ├── NPR News/
│   │   ├── Unknown - NPR News Broadcast 2024-01-15.mp3
Naming convention:
• Primary: {Artist} - {Title}.{ext}
• Fallback (if metadata unavailable): {Station} - {YYYY-MM-DD HH-MM}.{ext}
ID3 Tag Writing (via mutagen):
Python
 
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, APIC

def tag_file(filepath, metadata, station_name):
    audio = ID3()
    audio["TIT2"] = TIT2(encoding=3, text=metadata["title"])       # Title
    audio["TPE1"] = TPE1(encoding=3, text=metadata["artist"])       # Artist
    audio["TALB"] = TALB(encoding=3, text=metadata.get("album", station_name))  # Album
    audio["TYER"] = TYER(encoding=3, text=str(datetime.now().year)) # Year
    if metadata.get("cover_art"):
        audio["APIC"] = APIC(encoding=3, mime="image/jpeg",
                             type=3, desc="Cover",
                             data=download_image(metadata["cover_art"]))
    audio.save(filepath)
7.6 Favourites System
• Stored in favourites.json (portable, in app directory)
• Each favourite contains:
Json
 
{
  "name": "BBC Radio 1",
  "url": "https://stream-url...",
  "favicon": "https://...",
  "tags": ["pop", "uk"],
  "country": "United Kingdom",
  "language": "english",
  "network": "BBC"
}
• Quick-access from Favourites page or a context menu in the tree
7.7 Custom Stations
• User can add stations not in the Radio Browser database
• Form fields: Name, URL, Genre, Country, Language, Network, Bitrate
• Stored in custom_stations.json
• Merged into the tree view alongside database stations (visually distinguished, e.g., with a ★ prefix)
7.8 VPN Support
• Proxy approach: Application supports SOCKS5 / HTTP proxy settings:
◦ All HTTP requests (streaming + API) route through the configured proxy
◦ Configurable in Settings page
• System VPN detection: Check for active VPN interface and display status in the status bar
• Implementation:
Python
 
proxies = {
    "http": "socks5://127.0.0.1:1080",
    "https": "socks5://127.0.0.1:1080"
}
# Used by requests library and FFmpeg (via -headers or environment)
7.9 Soundcard Selection
• Enumerate available audio output devices using sounddevice.query_devices()
• User selects output device in Settings
• Player routes audio to the selected device:
Python
 
import sounddevice as sd
sd.OutputStream(device=device_id, samplerate=44100, channels=2)
7.10 Large Buffer Management
• Ring buffer
 
 