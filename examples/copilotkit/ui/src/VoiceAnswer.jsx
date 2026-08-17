import { useHumanInTheLoop } from "@copilotkit/react-core/v2";
import React from "react";
import { z } from "zod";

import { canListen, canSpeak, hush, listen, speak } from "./speech.js";

// Asking out loud, and being answered out loud.
//
// This is the agent's second way of collecting, and the reason it is a tool
// rather than a permanent microphone somewhere is discoverability. A mic
// button in the corner is a thing you have to notice and then guess the
// purpose of. A press-to-talk panel that appears in the conversation, at
// the moment somebody has said they find typing hard, is an offer — and it
// arrives with the question already read out, so the affordance explains
// itself by using itself.
//
// What comes back is a **transcript**, not answers. That split is
// deliberate and it is what makes free browser speech recognition good
// enough here: nothing depends on the recogniser hearing "AE01 CAB"
// correctly, because the model reads the transcript, works out what it
// means, and hands back a form with its interpretation filled in for
// checking. A rough transcript plus a person confirming beats a good
// transcript nobody checks — which is the same conclusion the licence demo
// reached about reading a photograph, for the same reason.

export const VOICE_SPEC = z.object({
  question: z
    .string()
    .describe("What to ask, in the words you would say it aloud."),
  hint: z
    .string()
    .optional()
    .describe("A line under it: what to include, or an example answer."),
  speak: z
    .boolean()
    .optional()
    .describe(
      "Read the question aloud when it appears. Default true — you are " +
        "asking somebody to talk, so talking to them first is the point.",
    ),
});

const styles = {
  card: {
    border: "1px solid #9cc7c1",
    background: "#f2f9f8",
    borderRadius: "10px",
    padding: "1rem 1.15rem",
    margin: "0.25rem 0",
    maxWidth: "34rem",
  },
  question: { margin: "0 0 0.2rem", fontSize: "1rem", fontWeight: 600 },
  hint: { margin: "0 0 0.8rem", color: "#5b6c7a", fontSize: "0.86rem" },
  row: { display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" },
  talk: {
    font: "inherit",
    fontWeight: 600,
    fontSize: "0.95rem",
    color: "#fff",
    background: "#0d6b61",
    border: 0,
    borderRadius: "999px",
    padding: "0.6rem 1.3rem",
    cursor: "pointer",
  },
  talking: { background: "#b42318" },
  quiet: {
    font: "inherit",
    fontSize: "0.85rem",
    background: "#fff",
    border: "1px solid #d7dde3",
    borderRadius: "6px",
    padding: "0.5rem 0.8rem",
    cursor: "pointer",
  },
  heard: {
    marginTop: "0.8rem",
    padding: "0.6rem 0.75rem",
    background: "#fff",
    border: "1px solid #d7dde3",
    borderRadius: "6px",
    font: "inherit",
    fontSize: "0.92rem",
    width: "100%",
    boxSizing: "border-box",
  },
  label: {
    display: "block",
    fontSize: "0.8rem",
    fontWeight: 600,
    color: "#5b6c7a",
    marginTop: "0.8rem",
  },
  problem: { color: "#b42318", fontSize: "0.85rem", margin: "0.6rem 0 0" },
  done: { color: "#5b6c7a", fontSize: "0.88rem", margin: 0 },
};

// Answering the tool call even when nobody answers the form.
//
// A drawn form is a *pending tool call*, and typing in the chat starts a
// new run which abandons it. Left alone that call simply evaporates: the
// agent is told "interrupted before a result was produced" with no idea
// whether the person filled anything in, ignored it, or never saw it. So
// on the way out we answer for them — not with their half-typed values,
// which they never sent and never checked, but with the fact that they
// went elsewhere. What they typed is worth nothing; what they *did* is
// worth knowing.
function useAnswerIfAbandoned(respond, sentRef) {
  const latest = React.useRef(respond);
  latest.current = respond;
  React.useEffect(
    () => () => {
      if (sentRef.current || !latest.current) return;
      try {
        latest.current({ submitted: false, abandoned: true });
      } catch {
        // The run is already gone, which is the case this cannot help.
      }
    },
    [sentRef],
  );
}

function VoiceAnswer({ args, status, respond }) {
  const { question, hint } = args ?? {};
  const shouldSpeak = args?.speak !== false;

  const [heard, setHeard] = React.useState("");
  const [listening, setListening] = React.useState(false);
  const [problem, setProblem] = React.useState(null);
  const [sent, setSent] = React.useState(false);
  const sentRef = React.useRef(false);
  const stopRef = React.useRef(null);
  useAnswerIfAbandoned(respond, sentRef);

  // Read it out as it arrives, once. Somebody being asked to speak is
  // usually somebody who would rather be spoken to.
  React.useEffect(() => {
    if (status === "executing" && shouldSpeak && question) {
      speak(hint ? `${question} ${hint}` : question);
    }
    return hush;
  }, [status, shouldSpeak, question, hint]);

  React.useEffect(() => () => stopRef.current?.(), []);

  const start = () => {
    hush();
    setProblem(null);
    setListening(true);
    stopRef.current = listen({
      onTranscript: setHeard,
      onProblem: (message) => {
        setProblem(message);
        setListening(false);
      },
      onEnd: () => setListening(false),
    });
  };

  const stop = () => {
    stopRef.current?.();
    setListening(false);
  };

  if (status === "inProgress") {
    return (
      <div style={styles.card}>
        <p style={styles.done}>…</p>
      </div>
    );
  }
  if (status === "complete" || sent) {
    return (
      <div style={styles.card}>
        <p style={styles.done}>Thanks — sent.</p>
      </div>
    );
  }

  const send = () => {
    stop();
    hush();
    sentRef.current = true;
    setSent(true);
    respond({ transcript: heard.trim() });
  };

  return (
    <div style={styles.card}>
      <p style={styles.question}>{question}</p>
      {hint && <p style={styles.hint}>{hint}</p>}

      <div style={styles.row}>
        {canListen() ? (
          <button
            type="button"
            style={{ ...styles.talk, ...(listening ? styles.talking : {}) }}
            onClick={listening ? stop : start}
            aria-pressed={listening}
          >
            {listening ? "◼ Stop" : "🎤 Press to talk"}
          </button>
        ) : (
          // Firefox, mostly. Saying so beats a button that does nothing.
          <span style={styles.hint}>
            This browser cannot listen — type your answer instead.
          </span>
        )}
        {canSpeak() && (
          <button
            type="button"
            style={styles.quiet}
            onClick={() => speak(hint ? `${question} ${hint}` : question)}
          >
            🔊 Read it again
          </button>
        )}
      </div>

      {/* Editable, always. The recogniser will get names and registrations
          wrong, and the fix for a wrong word should not be saying the whole
          thing again. */}
      <label style={styles.label} htmlFor="voice-heard">
        {listening ? "Listening…" : "What I heard — edit anything wrong"}
      </label>
      <textarea
        id="voice-heard"
        rows={3}
        style={styles.heard}
        value={heard}
        placeholder="Press to talk, or just type."
        onChange={(event) => setHeard(event.target.value)}
      />

      {problem && <p style={styles.problem}>{problem}</p>}

      <div style={{ ...styles.row, marginTop: "0.7rem" }}>
        <button
          type="button"
          style={styles.talk}
          disabled={!heard.trim()}
          onClick={send}
        >
          Send
        </button>
      </div>
    </div>
  );
}

/** Let the agent ask for a spoken answer, and be given the transcript. */
export function useVoiceAnswer() {
  useHumanInTheLoop({
    name: "ask_out_loud",
    description:
      "Ask a question and let the person answer by speaking. Shows a " +
      "press-to-talk panel in the conversation and reads the question " +
      "aloud. Use it when somebody says typing is hard or slow, when they " +
      "ask to talk instead, or when the answer is a long explanation that " +
      "is quicker said than typed. You get back a rough transcript of what " +
      "they said — work out what it means, then show them a form with your " +
      "reading of it filled in so they can check it before it is placed. " +
      "Ask for several things at once: rambling is fine, you are reading it.",
    parameters: VOICE_SPEC,
    render: VoiceAnswer,
  });
}
