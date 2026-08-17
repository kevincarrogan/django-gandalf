// Speaking and listening, both of them the browser's own.
//
// Neither of these costs anything or leaves the page as far as this demo is
// concerned: `speechSynthesis` renders locally, and `SpeechRecognition` is
// built into the browser. There is no key, no per-minute charge and no
// server-side transcription anywhere in this.
//
// That is worth one caveat, because it is not free of consequences even
// where it is free of charge: **Chrome's implementation sends the audio to
// Google's servers.** Safari uses its own. For a demo that is fine; for a
// real insurance form it is a question somebody has to answer before this
// ships, and the answer may be a server-side transcriber instead. Firefox
// has no support at all, which is why everything here degrades to typing
// rather than assuming.
//
// The other reason to keep this thin: the design does not lean on the
// recogniser being good. A rough transcript is enough, because the model
// maps it onto fields and hands back what it heard for checking — the same
// shape as the licence demo reading a photograph. Anything that depended on
// hearing "AE01 CAB" correctly would need a better recogniser than this and
// a person to check it anyway.

const Recognition =
  typeof window !== "undefined" &&
  (window.SpeechRecognition || window.webkitSpeechRecognition);

/** Whether this browser can listen at all. Firefox cannot. */
export const canListen = () => Boolean(Recognition);

/** Whether this browser can read aloud. Effectively everywhere. */
export const canSpeak = () =>
  typeof window !== "undefined" && "speechSynthesis" in window;

const PROBLEMS = {
  "not-allowed": "The microphone is blocked. Allow it in your browser settings and try again.",
  "service-not-allowed": "The microphone is blocked. Allow it in your browser settings and try again.",
  "no-speech": "I did not hear anything. Try again, or type it instead.",
  network: "The speech service could not be reached. Type it instead.",
  aborted: null,
};

/**
 * Listen until told to stop.
 *
 * `onTranscript` is called with everything heard so far, including the
 * part the recogniser has not committed to yet — showing that as it
 * arrives is the whole of the feedback that something is working, and its
 * absence is what makes a press-to-talk button feel broken.
 *
 * Returns a `stop()`. Errors arrive through `onProblem` as a sentence, not
 * a code, because they are shown to a person.
 */
export function listen({ onTranscript, onProblem, onEnd, lang = "en-GB" }) {
  if (!Recognition) {
    onProblem?.("This browser cannot listen. Type it instead.");
    return () => {};
  }

  const recognition = new Recognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = lang;

  let settled = "";
  recognition.onresult = (event) => {
    let pending = "";
    for (let index = event.resultIndex; index < event.results.length; index++) {
      const result = event.results[index];
      if (result.isFinal) settled += result[0].transcript;
      else pending += result[0].transcript;
    }
    onTranscript?.((settled + pending).trim());
  };
  recognition.onerror = (event) => {
    const problem = PROBLEMS[event.error];
    // `aborted` is us calling stop(), which is not a problem worth saying.
    if (problem !== null) {
      onProblem?.(problem ?? "Something went wrong listening. Type it instead.");
    }
  };
  recognition.onend = () => onEnd?.();

  try {
    recognition.start();
  } catch {
    // Already running — starting twice throws rather than being a no-op.
  }
  return () => recognition.stop();
}

/**
 * Read `text` aloud, stopping whatever was already being read.
 *
 * Cancelling first matters: two utterances queue rather than replace, so a
 * page that speaks on every render ends up minutes behind itself.
 */
export function speak(text, { lang = "en-GB" } = {}) {
  if (!canSpeak() || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = lang;
  window.speechSynthesis.speak(utterance);
}

export function hush() {
  if (canSpeak()) window.speechSynthesis.cancel();
}
