// A tiny, dependency-free WAV encoder for one mathematically generated
// sine tone — the browser-side counterpart to
// testing/synthetic_audio.py's generate_tone(). Used only so
// avl-audio-player has something REAL and legally playable to play:
// clearly-synthetic audio, never anything resembling a recording of a
// person. No speech, no noise sample, nothing derived from source
// material — a pure sine wave, same as the backend fixture generator.

const SAMPLE_RATE = 16000;

export function buildSyntheticToneWavUrl({ frequencyHz = 440, durationSeconds = 2, amplitude = 0.4 } = {}) {
  const sampleCount = Math.floor(SAMPLE_RATE * durationSeconds);
  const dataSize = sampleCount * 2; // 16-bit mono
  const buffer = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buffer);

  function writeString(offset, text) {
    for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
  }

  writeString(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, SAMPLE_RATE, true);
  view.setUint32(28, SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, dataSize, true);

  for (let i = 0; i < sampleCount; i++) {
    const sample = amplitude * Math.sin((2 * Math.PI * frequencyHz * i) / SAMPLE_RATE);
    view.setInt16(44 + i * 2, Math.max(-32767, Math.min(32767, Math.round(sample * 32767))), true);
  }

  const blob = new Blob([buffer], { type: "audio/wav" });
  return URL.createObjectURL(blob);
}
