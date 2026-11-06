import { AudioModule, RecordingPresets, setAudioModeAsync, useAudioRecorder } from "expo-audio";
import { File } from "expo-file-system";
import { useEffect, useRef, useState } from "react";

import { apiUpload } from "@/api/client";

import { MAX_RECORDING_MS } from "./constants";
import { uploadDurationMs } from "./sessionFlow";

export type RecorderStatus = "idle" | "recording" | "transcribing";

export const MIC_OFF_MESSAGE = "Microphone access is off in Settings.";
export const TRANSCRIBE_FAILED_MESSAGE = "Couldn't transcribe. Type it instead.";

type RecorderArgs = {
  cardId: string;
  sessionKey: string | null;
  onText: (text: string) => void;
  onError: (message: string) => void;
};

/** The 🎙 button: the first tap records, the next (or the 2-minute limit) stops and transcribes the answer. */
export function useRecorder({ cardId, sessionKey, onText, onError }: RecorderArgs) {
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);
  const [status, setStatus] = useState<RecorderStatus>("idle");

  // Refs so the auto-stop timer and the upload's late reply see current values; `mounted` drops a transcript that
  // arrives after the card was left.
  const callbacks = useRef({ onText, onError });
  callbacks.current = { onText, onError };
  const statusRef = useRef<RecorderStatus>("idle");
  const startedAt = useRef(0);
  const stopTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const mounted = useRef(true);
  const starting = useRef(false);

  function moveTo(next: RecorderStatus): void {
    statusRef.current = next;
    if (mounted.current) setStatus(next);
  }

  // Leaving the card mid-recording stops it; the recording is thrown away.
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(stopTimer.current);
      if (statusRef.current === "recording") void recorder.stop().catch(() => {});
      void leaveRecordingMode();
    };
  }, [recorder]);

  // Back to playback routing, so other sounds don't come out of the earpiece. Best effort: nothing to tell the user.
  function leaveRecordingMode(): Promise<void> {
    return setAudioModeAsync({ allowsRecording: false }).catch(() => {});
  }

  async function start(): Promise<void> {
    const permission = await AudioModule.requestRecordingPermissionsAsync();
    if (!permission.granted) {
      callbacks.current.onError(MIC_OFF_MESSAGE);
      return;
    }

    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    if (!mounted.current) {
      await leaveRecordingMode();
      return;
    }
    recorder.record();
    startedAt.current = Date.now();
    moveTo("recording");
    stopTimer.current = setTimeout(() => runStop(), MAX_RECORDING_MS);
  }

  async function stop(): Promise<void> {
    if (statusRef.current !== "recording") return;
    clearTimeout(stopTimer.current);
    moveTo("transcribing");

    await recorder.stop();
    await setAudioModeAsync({ allowsRecording: false });
    const text = await transcribe(recorder.uri, uploadDurationMs(Date.now() - startedAt.current));

    moveTo("idle");
    if (!mounted.current) return;
    if (text === null) callbacks.current.onError(TRANSCRIBE_FAILED_MESSAGE);
    else callbacks.current.onText(text);
  }

  async function transcribe(uri: string | null, durationMs: number): Promise<string | null> {
    if (uri === null) return null;
    const form = new FormData();
    form.append("card_id", cardId);
    form.append("duration_ms", String(durationMs));
    // Expo's fetch only sends file parts it can read bytes from: a File, not React Native's { uri, name, type }.
    form.append("audio", new File(uri) as unknown as Blob);

    // Any failure (offline, 413, 503, the provider) reads the same to the user: type it instead.
    const body = await apiUpload("/review/transcribe", { form, sessionKey }).catch(() => null);
    const text = (body as { text?: unknown } | null)?.text;
    return typeof text === "string" ? text : null;
  }

  // The auto-stop timer and the tap share this boundary: a recorder that fails to stop must not strand "transcribing".
  function runStop(): Promise<void> {
    return stop().catch(() => {
      moveTo("idle");
      if (mounted.current) callbacks.current.onError(TRANSCRIBE_FAILED_MESSAGE);
    });
  }

  function toggle(): void {
    if (statusRef.current === "transcribing" || starting.current) return;
    const recording = statusRef.current === "recording";
    // A second tap while the permission prompt is up must not start a second recording.
    starting.current = !recording;
    // A recorder that fails to start or stop leaves the box as it was; the user can still type.
    const action = recording
      ? runStop()
      : start()
          .catch(() => {
            moveTo("idle");
            if (mounted.current) callbacks.current.onError(TRANSCRIBE_FAILED_MESSAGE);
          })
          .finally(() => {
            starting.current = false;
          });
    void action;
  }

  return { status, toggle };
}
