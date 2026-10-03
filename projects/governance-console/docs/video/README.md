# The escalation walkthrough video

| File | What it is |
|---|---|
| `escalation-raw.mp4` | The screen recording, silent, unedited: a real run against a local console, EOD heartbeat app and mail server |
| `escalation-cues.json` | When each caption appears (`cues`) and the page loads and waits the recorder marked for cutting (`cuts`) |
| `../img/escalation.mp4` | The published video: dead time removed, narrated |

To rebuild the published video:

```bash
scripts/video/narrate-on-host.sh            # neural voice (Piper), runs in a container, writes ~/video-out/escalation.mp4
python scripts/video/narrate.py --tts pico  # quick preview with a basic built-in voice
```

The editor, `scripts/video/narrate.py`, works caption by caption:

- **Loads and waits are cut.** That covers page loads, Streamlit drawing and the "running…" waits, and any blank
  white screen.
- **Still stretches shrink.** Wherever the screen doesn't change, a quarter of a second is kept.
- **Time goes back only for the voice.** It is restored only where a caption's narration needs it, first to those
  still stretches, then by holding the last frame. The voice never runs over the next step.
