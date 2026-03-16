# Gemini Live API

## How to use audio

Live API's audio capabilities enable natural voice conversations with sub-second latency through bidirectional audio streaming. This section covers how to send audio input to the model and receive audio responses, including format requirements, streaming best practices, and client-side implementation patterns.

### Sending audio input

#### Audio format requirements

Before calling `send_realtime()`, ensure your audio data is already in the correct format:

- Format: 16-bit PCM (signed integer)
- Sample rate: 16,000 Hz (16kHz)
- Channels: mono (single channel)

ADK does not perform audio format conversion. Sending audio in incorrect formats will result in poor quality or errors.

Demo implementation: `main.py:181-184`

```py
audio_blob = types.Blob(
    mime_type="audio/pcm;rate=16000",
    data=audio_data,
)
live_request_queue.send_realtime(audio_blob)
```

#### Best practices for sending audio input

- Chunked streaming: send audio in small chunks for low latency. Choose chunk size based on your latency requirements:
  - Ultra-low latency (real-time conversation): 10-20ms chunks (~320-640 bytes @ 16kHz)
  - Balanced (recommended): 50-100ms chunks (~1600-3200 bytes @ 16kHz)
  - Lower overhead: 100-200ms chunks (~3200-6400 bytes @ 16kHz)
- Use consistent chunk sizes throughout the session for optimal performance. Example: `100ms @ 16kHz = 16000 samples/sec × 0.1 sec × 2 bytes/sample = 3200 bytes`.
- Prompt forwarding: ADK's `LiveRequestQueue` forwards each chunk promptly without coalescing or batching. Choose chunk sizes that meet your latency and bandwidth requirements. Don't wait for model responses before sending next chunks.
- Continuous processing: the model processes audio continuously, not turn-by-turn. With automatic VAD enabled (the default), just stream continuously and let the API detect speech.
- Activity signals: use `send_activity_start()` / `send_activity_end()` only when you explicitly disable VAD for manual turn-taking control. VAD is enabled by default, so activity signals are not needed for most applications.

### Handling audio input at the client (browser)

In browser-based applications, capturing microphone audio and sending it to the server requires using the Web Audio API with AudioWorklet processors. The bidi-demo demonstrates how to capture microphone input, convert it to the required 16-bit PCM format at 16kHz, and stream it continuously to the WebSocket server.

#### Architecture

- Audio capture: use Web Audio API to access microphone with 16kHz sample rate
- Audio processing: AudioWorklet processor captures audio frames in real-time
- Format conversion: convert `Float32Array` samples to 16-bit PCM
- WebSocket streaming: send PCM chunks to server via WebSocket

#### Demo: `audio-recorder.js:7-58`

```js
// Start audio recorder worklet
export async function startAudioRecorderWorklet(audioRecorderHandler) {
  // Create an AudioContext with 16kHz sample rate
  // This matches the Live API's required input format (16-bit PCM @ 16kHz)
  const audioRecorderContext = new AudioContext({ sampleRate: 16000 });

  // Load the AudioWorklet module that will process audio in real-time
  // AudioWorklet runs on a separate thread for low-latency, glitch-free audio processing
  const workletURL = new URL("./pcm-recorder-processor.js", import.meta.url);
  await audioRecorderContext.audioWorklet.addModule(workletURL);

  // Request access to the user's microphone
  // channelCount: 1 requests mono audio (single channel) as required by Live API
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1 },
  });
  const source = audioRecorderContext.createMediaStreamSource(micStream);

  // Create an AudioWorkletNode that uses our custom PCM recorder processor
  // This node will capture audio frames and send them to our handler
  const audioRecorderNode = new AudioWorkletNode(
    audioRecorderContext,
    "pcm-recorder-processor",
  );

  // Connect the microphone source to the worklet processor
  // The processor will receive audio frames and post them via port.postMessage
  source.connect(audioRecorderNode);
  audioRecorderNode.port.onmessage = (event) => {
    // Convert Float32Array to 16-bit PCM format required by Live API
    const pcmData = convertFloat32ToPCM(event.data);

    // Send the PCM data to the handler (which will forward to WebSocket)
    audioRecorderHandler(pcmData);
  };
  return [audioRecorderNode, audioRecorderContext, micStream];
}

// Convert Float32 samples to 16-bit PCM
function convertFloat32ToPCM(inputData) {
  // Create an Int16Array of the same length
  const pcm16 = new Int16Array(inputData.length);
  for (let i = 0; i < inputData.length; i++) {
    // Web Audio API provides Float32 samples in range [-1.0, 1.0]
    // Multiply by 0x7fff (32767) to convert to 16-bit signed integer range [-32768, 32767]
    pcm16[i] = inputData[i] * 0x7fff;
  }
  // Return the underlying ArrayBuffer (binary data) for efficient transmission
  return pcm16.buffer;
}
```

#### Demo: `pcm-recorder-processor.js:1-18`

```js
// pcm-recorder-processor.js - AudioWorklet processor for capturing audio
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
  }

  process(inputs, outputs, parameters) {
    if (inputs.length > 0 && inputs[0].length > 0) {
      // Use the first channel (mono)
      const inputChannel = inputs[0][0];
      // Copy the buffer to avoid issues with recycled memory
      const inputCopy = new Float32Array(inputChannel);
      this.port.postMessage(inputCopy);
    }
    return true;
  }
}

registerProcessor("pcm-recorder-processor", PCMProcessor);
```

#### Demo: `app.js:977-986`

```js
// Audio recorder handler - called for each audio chunk
function audioRecorderHandler(pcmData) {
  if (websocket && websocket.readyState === WebSocket.OPEN && is_audio) {
    // Send audio as binary WebSocket frame (more efficient than base64 JSON)
    websocket.send(pcmData);
    console.log("[CLIENT TO AGENT] Sent audio chunk: %s bytes", pcmData.byteLength);
  }
}
```

#### Key implementation details

- 16kHz sample rate: the `AudioContext` must be created with `sampleRate: 16000` to match Live API requirements. Modern browsers support this rate.
- Mono audio: request single-channel audio (`channelCount: 1`) since Live API expects mono input. This reduces bandwidth and processing overhead.
- AudioWorklet processing: AudioWorklet runs on a separate thread from the main JavaScript thread, ensuring low-latency, glitch-free audio processing without blocking the UI.
- Float32 to PCM16 conversion: Web Audio API provides audio as `Float32Array` values in range `[-1.0, 1.0]`. Multiply by 32767 (`0x7fff`) to convert to 16-bit signed integer PCM.
- Binary WebSocket frames: send PCM data directly as `ArrayBuffer` via WebSocket binary frames instead of base64-encoding in JSON. This reduces bandwidth by ~33% and eliminates encoding/decoding overhead.
- Continuous streaming: the AudioWorklet `process()` method is called automatically at regular intervals (typically 128 samples at a time for 16kHz). This provides consistent chunk sizes for streaming.

This architecture ensures low-latency audio capture and efficient transmission to the server, which then forwards it to the ADK Live API via `LiveRequestQueue.send_realtime()`.

### Receiving audio output

When `response_modalities=["AUDIO"]` is configured, the model returns audio data in the event stream as `inline_data` parts.

#### Audio format requirements

The model outputs audio in the following format:

- Format: 16-bit PCM (signed integer)
- Sample rate: 24,000 Hz (24kHz) for native audio models
- Channels: mono (single channel)
- MIME type: `audio/pcm;rate=24000`

The audio data arrives as raw PCM bytes, ready for playback or further processing. No additional conversion is required unless you need a different sample rate or format.

#### Server-side: receiving audio output

```py
from google.adk.agents.run_config import RunConfig, StreamingMode

# Configure for audio output
run_config = RunConfig(
    response_modalities=["AUDIO"],  # Required for audio responses
    streaming_mode=StreamingMode.BIDI,
)

# Process audio output from the model
async for event in runner.run_live(
    user_id="user_123",
    session_id="session_456",
    live_request_queue=live_request_queue,
    run_config=run_config,
):
    # Events may contain multiple parts (text, audio, etc.)
    if event.content and event.content.parts:
        for part in event.content.parts:
            # Audio data arrives as inline_data with audio/pcm MIME type
            if part.inline_data and part.inline_data.mime_type.startswith("audio/pcm"):
                # The data is already decoded to raw bytes (24kHz, 16-bit PCM, mono)
                audio_bytes = part.inline_data.data

                # Your logic to stream audio to client
                await stream_audio_to_client(audio_bytes)

                # Or save to file
                # with open("output.pcm", "ab") as f:
                #     f.write(audio_bytes)
```

#### Automatic base64 decoding

The Live API wire protocol transmits audio data as base64-encoded strings. The `google.genai` types system uses Pydantic's base64 serialization feature (`val_json_bytes="base64"`) to automatically decode base64 strings into bytes when deserializing API responses. When you access `part.inline_data.data`, you receive ready-to-use bytes—no manual base64 decoding needed.

### Handling audio events at the client (browser)

The bidi-demo uses a different architectural approach: instead of processing audio on the server, it forwards all events (including audio data) to the WebSocket client and handles audio playback in the browser. This pattern separates concerns: the server focuses on ADK event streaming while the client handles media playback using Web Audio API.

Demo implementation: `main.py:225-233`

```py
# The bidi-demo forwards all events (including audio) to the WebSocket client
async for event in runner.run_live(
    user_id=user_id,
    session_id=session_id,
    live_request_queue=live_request_queue,
    run_config=run_config,
):
    event_json = event.model_dump_json(exclude_none=True, by_alias=True)
    await websocket.send_text(event_json)
```

#### Demo implementation (client - JavaScript)

The client-side implementation involves three components: WebSocket message handling, audio player setup with AudioWorklet, and the AudioWorklet processor itself.

#### Demo: `app.js:638-688`

```js
// 1. WebSocket Message Handler
// Handle content events (text or audio)
if (adkEvent.content && adkEvent.content.parts) {
  const parts = adkEvent.content.parts;

  for (const part of parts) {
    // Handle inline data (audio)
    if (part.inlineData) {
      const mimeType = part.inlineData.mimeType;
      const data = part.inlineData.data;

      // Check if this is audio PCM data and the audio player is ready
      if (mimeType && mimeType.startsWith("audio/pcm") && audioPlayerNode) {
        // Decode base64 to ArrayBuffer and send to AudioWorklet for playback
        audioPlayerNode.port.postMessage(base64ToArray(data));
      }
    }
  }
}

// Decode base64 audio data to ArrayBuffer
function base64ToArray(base64) {
  // Convert base64url to standard base64 (RFC 4648 compliance)
  // base64url uses '-' and '_' instead of '+' and '/', which are URL-safe
  let standardBase64 = base64.replace(/-/g, "+").replace(/_/g, "/");

  // Add padding '=' characters if needed
  // Base64 strings must be multiples of 4 characters
  while (standardBase64.length % 4) {
    standardBase64 += "=";
  }

  // Decode base64 string to binary string using browser API
  const binaryString = window.atob(standardBase64);
  const len = binaryString.length;
  const bytes = new Uint8Array(len);
  // Convert each character code (0-255) to a byte
  for (let i = 0; i < len; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }
  // Return the underlying ArrayBuffer (binary data)
  return bytes.buffer;
}
```

#### Demo: `audio-player.js:5-24`

```js
// 2. Audio Player Setup
// Start audio player worklet
export async function startAudioPlayerWorklet() {
  // Create an AudioContext with 24kHz sample rate
  // This matches the Live API's output audio format (16-bit PCM @ 24kHz)
  // Note: Different from input rate (16kHz) - Live API outputs at higher quality
  const audioContext = new AudioContext({
    sampleRate: 24000,
  });

  // Load the AudioWorklet module that will handle audio playback
  // AudioWorklet runs on audio rendering thread for smooth, low-latency playback
  const workletURL = new URL("./pcm-player-processor.js", import.meta.url);
  await audioContext.audioWorklet.addModule(workletURL);

  // Create an AudioWorkletNode using our custom PCM player processor
  // This node will receive audio data via postMessage and play it through speakers
  const audioPlayerNode = new AudioWorkletNode(audioContext, "pcm-player-processor");

  // Connect the player node to the audio destination (speakers/headphones)
  // This establishes the audio graph: AudioWorklet → AudioContext.destination
  audioPlayerNode.connect(audioContext.destination);

  return [audioPlayerNode, audioContext];
}
```

#### Demo: `pcm-player-processor.js:5-76`

```js
// 3. AudioWorklet Processor (Ring Buffer)
// AudioWorklet processor that buffers and plays PCM audio
class PCMPlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();

    // Initialize ring buffer (24kHz x 180 seconds = ~4.3 million samples)
    // Ring buffer absorbs network jitter and ensures smooth playback
    this.bufferSize = 24000 * 180;
    this.buffer = new Float32Array(this.bufferSize);
    this.writeIndex = 0; // Where we write new audio data
    this.readIndex = 0; // Where we read for playback

    // Handle incoming messages from main thread
    this.port.onmessage = (event) => {
      // Reset buffer on interruption (e.g., user interrupts model response)
      if (event.data.command === "endOfAudio") {
        this.readIndex = this.writeIndex; // Clear the buffer by jumping read to write position
        return;
      }

      // Decode Int16 array from incoming ArrayBuffer
      // The Live API sends 16-bit PCM audio data
      const int16Samples = new Int16Array(event.data);

      // Add audio data to ring buffer for playback
      this._enqueue(int16Samples);
    };
  }

  // Push incoming Int16 data into ring buffer
  _enqueue(int16Samples) {
    for (let i = 0; i < int16Samples.length; i++) {
      // Convert 16-bit integer to float in [-1.0, 1.0] required by Web Audio API
      // Divide by 32768 (max positive value for signed 16-bit int)
      const floatVal = int16Samples[i] / 32768;

      // Store in ring buffer at current write position
      this.buffer[this.writeIndex] = floatVal;
      // Move write index forward, wrapping around at buffer end (circular buffer)
      this.writeIndex = (this.writeIndex + 1) % this.bufferSize;

      // Overflow handling: if write catches up to read, move read forward
      // This overwrites oldest unplayed samples (rare, only under extreme network delay)
      if (this.writeIndex === this.readIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
    }
  }

  // Called by Web Audio system automatically ~128 samples at a time
  // This runs on the audio rendering thread for precise timing
  process(inputs, outputs, parameters) {
    const output = outputs[0];
    const framesPerBlock = output[0].length;

    for (let frame = 0; frame < framesPerBlock; frame++) {
      // Write samples to output buffer (mono to stereo)
      output[0][frame] = this.buffer[this.readIndex]; // left channel
      if (output.length > 1) {
        output[1][frame] = this.buffer[this.readIndex]; // right channel (duplicate for stereo)
      }

      // Move read index forward unless buffer is empty (underflow protection)
      if (this.readIndex != this.writeIndex) {
        this.readIndex = (this.readIndex + 1) % this.bufferSize;
      }
      // If readIndex == writeIndex, we're out of data - output silence (0.0)
    }

    return true; // Keep processor alive (return false to terminate)
  }
}

registerProcessor("pcm-player-processor", PCMPlayerProcessor);
```

#### Key implementation patterns

- Base64 decoding: the server sends audio data as base64-encoded strings in JSON. The client must decode to `ArrayBuffer` before passing to AudioWorklet. Handle both standard base64 and base64url encoding.
- 24kHz sample rate: the `AudioContext` must be created with `sampleRate: 24000` to match Live API output format (different from 16kHz input).
- Ring buffer architecture: use a circular buffer to handle variable network latency and ensure smooth playback. The buffer stores `Float32` samples and handles overflow by overwriting oldest data.
- PCM16 to Float32 conversion: Live API sends 16-bit signed integers. Divide by 32768 to convert to `Float32` in range `[-1.0, 1.0]` required by Web Audio API.
- Mono to stereo: the processor duplicates mono audio to both left and right channels for stereo output, ensuring compatibility with all audio devices.
- Interruption handling: on interruption events, send `endOfAudio` command to clear the buffer by setting `readIndex = writeIndex`, preventing playback of stale audio.

This architecture ensures smooth, low-latency audio playback while handling network jitter and interruptions gracefully.

---

## Establishing a connection

The following example shows how to create a connection with an API key:

```py
import asyncio
from google import genai

client = genai.Client()

model = "gemini-2.5-flash-native-audio-preview-12-2025"
config = {"response_modalities": ["AUDIO"]}


async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        print("Session started")
        # Send content...


if __name__ == "__main__":
    asyncio.run(main())
```

## Interaction modalities

The following sections provide examples and supporting context for the different input and output modalities available in Live API.

### Sending audio

Audio needs to be sent as raw PCM data (raw 16-bit PCM audio, 16kHz, little-endian).

```py
# Assuming 'chunk' is your raw PCM audio bytes
await session.send_realtime_input(
    audio=types.Blob(
        data=chunk,
        mime_type="audio/pcm;rate=16000",
    )
)
```

### Audio formats

Audio data in the Live API is always raw, little-endian, 16-bit PCM. Audio output always uses a sample rate of 24kHz. Input audio is natively 16kHz, but the Live API will resample if needed so any sample rate can be sent. To convey the sample rate of input audio, set the MIME type of each audio-containing `Blob` to a value like `audio/pcm;rate=16000`.

### Receiving audio

The model's audio responses are received as chunks of data.

```py
async for response in session.receive():
    if response.server_content and response.server_content.model_turn:
        for part in response.server_content.model_turn.parts:
            if part.inline_data:
                audio_data = part.inline_data.data
                # Process or play the audio data
```

### Sending text

Text can be sent using `send_realtime_input` (Python) or `sendRealtimeInput` (JavaScript).

```py
await session.send_realtime_input(text="Hello, how are you?")
```

### Incremental content updates

Use incremental updates to send text input, establish session context, or restore session context. For short contexts you can send turn-by-turn interactions to represent the exact sequence of events:

```py
turns = [
    {"role": "user", "parts": [{"text": "What is the capital of France?"}]},
    {"role": "model", "parts": [{"text": "Paris"}]},
]

await session.send_client_content(turns=turns, turn_complete=False)

turns = [{"role": "user", "parts": [{"text": "What is the capital of Germany?"}]}]

await session.send_client_content(turns=turns, turn_complete=True)
```

For longer contexts it's recommended to provide a single message summary to free up the context window for subsequent interactions. See Session Resumption for another method for loading session context.

### Audio transcriptions

In addition to the model response, you can also receive transcriptions of both the audio output and the audio input.

To enable transcription of the model's audio output, send `output_audio_transcription` in the setup config. The transcription language is inferred from the model's response.

```py
import asyncio
from google import genai
from google.genai import types

client = genai.Client()
model = "gemini-2.5-flash-native-audio-preview-12-2025"

config = {
    "response_modalities": ["AUDIO"],
    "output_audio_transcription": {},
}


async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        message = "Hello? Gemini are you there?"

        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": message}]},
            turn_complete=True,
        )

        async for response in session.receive():
            if response.server_content.model_turn:
                print("Model turn:", response.server_content.model_turn)
            if response.server_content.output_transcription:
                print("Transcript:", response.server_content.output_transcription.text)


if __name__ == "__main__":
    asyncio.run(main())
```

To enable transcription of the model's audio input, send `input_audio_transcription` in setup config.

```py
import asyncio
from pathlib import Path
from google import genai
from google.genai import types

client = genai.Client()
model = "gemini-2.5-flash-native-audio-preview-12-2025"

config = {
    "response_modalities": ["AUDIO"],
    "input_audio_transcription": {},
}


async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        audio_data = Path("16000.pcm").read_bytes()

        await session.send_realtime_input(
            audio=types.Blob(data=audio_data, mime_type="audio/pcm;rate=16000")
        )

        async for msg in session.receive():
            if msg.server_content.input_transcription:
                print("Transcript:", msg.server_content.input_transcription.text)


if __name__ == "__main__":
    asyncio.run(main())
```

## Change voice and language

Native audio output models support any of the voices available for our Text-to-Speech (TTS) models. You can listen to all the voices in AI Studio.

To specify a voice, set the voice name within the `speechConfig` object as part of the session configuration:

```py
config = {
    "response_modalities": ["AUDIO"],
    "speech_config": {
        "voice_config": {"prebuilt_voice_config": {"voice_name": "Kore"}},
    },
}
```

Note: If you're using the `generateContent` API, the set of available voices is slightly different. See the audio generation guide for generateContent audio generation voices.

The Live API supports multiple languages. Native audio output models automatically choose the appropriate language and don't support explicitly setting the language code.

## Native audio capabilities

Our latest models feature native audio output, which provides natural, realistic-sounding speech and improved multilingual performance. Native audio also enables advanced features like affective (emotion-aware) dialogue, proactive audio (where the model intelligently decides when to respond to input), and "thinking".

### Affective dialog

This feature lets Gemini adapt its response style to the input expression and tone.

To use affective dialog, set the API version to `v1alpha` and set `enable_affective_dialog` to `true` in the setup message:

```py
client = genai.Client(http_options={"api_version": "v1alpha"})

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    enable_affective_dialog=True,
)
```

### Proactive audio

When this feature is enabled, Gemini can proactively decide not to respond if the content is not relevant.

To use it, set the API version to `v1alpha` and configure the `proactivity` field in the setup message and set `proactive_audio` to `true`:

```py
client = genai.Client(http_options={"api_version": "v1alpha"})

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    proactivity={"proactive_audio": True},
)
```

### Thinking

The latest native audio output model `gemini-2.5-flash-native-audio-preview-12-2025` supports thinking capabilities, with dynamic thinking enabled by default.

The `thinkingBudget` parameter guides the model on the number of thinking tokens to use when generating a response. You can disable thinking by setting `thinkingBudget` to 0. For more info on the `thinkingBudget` configuration details of the model, see the thinking budgets documentation.

```py
model = "gemini-2.5-flash-native-audio-preview-12-2025"

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    thinking_config=types.ThinkingConfig(
        thinking_budget=1024,
    ),
)

async with client.aio.live.connect(model=model, config=config) as session:
    # Send audio input and receive audio
    ...
```

Additionally, you can enable thought summaries by setting `includeThoughts` to `true` in your configuration. See thought summaries for more info:

```py
model = "gemini-2.5-flash-native-audio-preview-12-2025"

config = types.LiveConnectConfig(
    response_modalities=["AUDIO"],
    thinking_config=types.ThinkingConfig(
        thinking_budget=1024,
        include_thoughts=True,
    ),
)
```

## Voice Activity Detection (VAD)

Voice Activity Detection (VAD) allows the model to recognize when a person is speaking. This is essential for creating natural conversations, as it allows a user to interrupt the model at any time.

When VAD detects an interruption, the ongoing generation is canceled and discarded. Only the information already sent to the client is retained in the session history. The server then sends a `BidiGenerateContentServerContent` message to report the interruption.

The Gemini server then discards any pending function calls and sends a `BidiGenerateContentServerContent` message with the IDs of the canceled calls.

```py
async for response in session.receive():
    if response.server_content.interrupted is True:
        # The generation was interrupted

        # If realtime playback is implemented in your application,
        # you should stop playing audio and clear queued playback here.
        ...
```

### Automatic VAD

By default, the model automatically performs VAD on a continuous audio input stream. VAD can be configured with the `realtimeInputConfig.automaticActivityDetection` field of the setup configuration.

When the audio stream is paused for more than a second (for example, because the user switched off the microphone), an `audioStreamEnd` event should be sent to flush any cached audio. The client can resume sending audio data at any time.

```py
# example audio file to try:
# URL = "https://storage.googleapis.com/generativeai-downloads/data/hello_are_you_there.pcm"
# !wget -q $URL -O sample.pcm
import asyncio
from pathlib import Path
from google import genai
from google.genai import types

client = genai.Client()
model = "gemini-2.5-flash-native-audio-preview-12-2025"

config = {"response_modalities": ["AUDIO"]}


async def main():
    async with client.aio.live.connect(model=model, config=config) as session:
        audio_bytes = Path("sample.pcm").read_bytes()

        await session.send_realtime_input(
            audio=types.Blob(data=audio_bytes, mime_type="audio/pcm;rate=16000")
        )

        # if stream gets paused, send:
        # await session.send_realtime_input(audio_stream_end=True)

        async for response in session.receive():
            if response.text is not None:
                print(response.text)


if __name__ == "__main__":
    asyncio.run(main())
```

With `send_realtime_input`, the API will respond to audio automatically based on VAD. While `send_client_content` adds messages to the model context in order, `send_realtime_input` is optimized for responsiveness at the expense of deterministic ordering.
