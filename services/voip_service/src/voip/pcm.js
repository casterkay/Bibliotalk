export function encodeB64(buf) {
  return Buffer.from(buf).toString("base64");
}

export function decodePcmS16Le(b64) {
  return Buffer.from(b64, "base64");
}

export function pcm24kTo48kS16le(pcm24kBuf) {
  // Naive 2x upsample: duplicate samples. Demo-grade but deterministic and low-latency.
  const inSamples = pcm24kBuf.length / 2;
  const out = Buffer.allocUnsafe(inSamples * 2 * 2);
  for (let i = 0; i < inSamples; i++) {
    const lo = pcm24kBuf[i * 2];
    const hi = pcm24kBuf[i * 2 + 1];
    const j = i * 4;
    out[j] = lo;
    out[j + 1] = hi;
    out[j + 2] = lo;
    out[j + 3] = hi;
  }
  return out;
}

export class PcmRingBuffer {
  constructor({ bytesPerSample }) {
    this._bytesPerSample = bytesPerSample;
    this._buf = Buffer.alloc(0);
  }

  push(buf) {
    if (!buf || buf.length === 0) return;
    this._buf = this._buf.length === 0 ? Buffer.from(buf) : Buffer.concat([this._buf, buf]);
  }

  samplesAvailable() {
    return Math.floor(this._buf.length / this._bytesPerSample);
  }

  popSamples(numSamples) {
    const bytes = numSamples * this._bytesPerSample;
    if (this._buf.length < bytes) {
      throw new Error("insufficient samples");
    }
    const out = this._buf.subarray(0, bytes);
    this._buf = this._buf.subarray(bytes);
    return out;
  }
}
