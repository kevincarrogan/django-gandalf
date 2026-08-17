import { HttpAgent } from "@ag-ui/client";
import { CopilotChat, CopilotKit, useAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { useEffect, useState } from "react";

import { inspectorEnabled } from "./inspector.js";
import { Outline } from "./journey.jsx";
import { styles } from "./styles.js";
import React from "react";

// Both photograph demos are this page with different words and a
// different endpoint. They differ in the wizard behind them — one keeps
// the scan as an answer, the other never wanted it — and not in anything
// the browser does, which is the point worth showing: reading a document
// takes no support from the form at all.

// Drag and drop, paste, the composer's own attach button, thumbnails and
// size validation all come from CopilotKit — `CopilotChat` wires them
// internally and an attachment lands as an AG-UI `InputContentDataSource`,
// which is the part the Django side already reads.
//
// These were briefly replaced with hand-rolled drop and paste handlers, to
// make a file send the moment it arrived rather than waiting for you to
// press send. That was a bad trade twice over: it left the composer's own
// attach button inert, and the handlers never fired anyway, because the
// chat is a child of the element they were bound to and handles its own
// drag events. Instant send is what the camera button is for.
const ATTACHMENTS = {
  enabled: true,
  accept: "image/*",
  // Shrink before sending, for the same reason the button does — see
  // `downscale`. `onUpload` is the seam CopilotKit leaves for exactly
  // this: return an input content source and it sends that instead.
  onUpload: async (file) => ({ type: "data", ...(await downscale(file)) }),
};

// The one thing `AttachmentsConfig` has no setting for. `capture` opens
// the camera directly instead of a picker, which is the difference
// between one tap and three on the handset these demos are best seen
// from. So the button stays, beside the chat's own attachments rather
// than instead of them.
const CAPTURE = { type: "file", accept: "image/*", capture: "environment" };

// A phone camera produces something like 11MB, base64 inflates it by a
// third, and the whole conversation travels in one JSON body — so an
// unshrunk photo breaks the request before the model ever sees it. It
// would be wasted anyway: the model resizes large images itself, and a
// licence is legible long before 4000px. The long edge here is well
// above what it takes to read a licence number and well below anything
// that costs real money.
const MAX_EDGE = 1600;
const QUALITY = 0.85;

async function downscale(file) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  // JPEG whatever came in: a photograph of a card gains nothing from PNG
  // and costs several times the bytes.
  const dataUrl = canvas.toDataURL("image/jpeg", QUALITY);
  return { value: dataUrl.split(",", 2)[1], mimeType: "image/jpeg" };
}

// Only the camera button needs this. An attachment added through the chat
// is encoded and sent by CopilotKit; this is the shortcut that skips the
// composer and sends the photo the moment it is taken.
async function sendPhoto(agent, file, prompt) {
  const source = await downscale(file);
  agent.addMessage({
    id: crypto.randomUUID(),
    role: "user",
    content: [
      { type: "text", text: prompt },
      {
        type: "image",
        // `mimeType`, not `mime_type`: the protocol is camelCase on the
        // wire even though the Python models spell it with an underscore.
        // Getting this wrong fails quietly — the part is dropped and the
        // agent simply says it cannot see a photograph.
        source: { type: "data", ...source },
      },
    ],
  });
  await agent.runAgent();
}

function answeredFields(answers) {
  // Flattened across steps, because a journey asked one question per page
  // has its answers spread over as many steps as it has pages.
  return Object.entries(answers ?? {}).flatMap(([step, fields]) =>
    Object.entries(fields).map(([field, value]) => [step, field, value]),
  );
}

function Panel({ title, blurb, prompt, emptyJourney }) {
  const { agent } = useAgent({ agentId: "default" });
  const state = agent.state ?? {};
  const [sending, setSending] = useState(false);
  const [error, setError] = useState(null);

  async function onPick(event) {
    const file = event.target.files?.[0];
    // Reset immediately: picking the same file twice fires no change
    // event otherwise, which looks like the button is broken.
    event.target.value = "";
    if (!file) return;
    setError(null);
    setSending(true);
    try {
      await sendPhoto(agent, file, prompt);
    } catch (failure) {
      setError(String(failure));
    } finally {
      setSending(false);
    }
  }

  const fields = answeredFields(state.answers);

  return (
    <div style={styles.panel}>
      <h1 style={{ marginTop: 0 }}>{title}</h1>
      <p style={styles.muted}>{blurb}</p>
      <p style={styles.muted}>
        The button takes a photo and sends it straight away. You can also
        attach one in the chat, drop it there, or paste it — those wait for
        you to press send, so you can say something with it.
      </p>

      <div style={styles.card}>
        <label
          style={{ ...styles.handoffLink, cursor: "pointer", background: "#2f5d8c" }}
        >
          {sending ? "Reading…" : "Take or choose a photo"}
          <input {...CAPTURE} onChange={onPick} style={{ display: "none" }} />
        </label>
        {error && <p style={{ color: "#b42318" }}>{error}</p>}
      </div>

      {state.handoff_url && (
        <div style={styles.handoff}>
          <strong>Ready for you to check</strong>
          <p style={{ marginBottom: 0 }}>
            Compare these against the card before confirming.
          </p>
          <a href={state.handoff_url} style={styles.handoffLink}>
            Check and confirm
          </a>
        </div>
      )}

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>The journey</h3>
        {state.outline ? (
          <Outline entries={state.outline} state={state} />
        ) : (
          <p style={{ ...styles.muted, marginBottom: 0 }}>{emptyJourney}</p>
        )}
      </div>

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>What it read</h3>
        {fields.length > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <tbody>
              {fields.map(([step, field, value]) => (
                <tr key={`${step}.${field}`}>
                  <td
                    style={{ padding: "0.2rem 1rem 0.2rem 0", ...styles.muted }}
                  >
                    {step} · {field}
                  </td>
                  <td style={{ padding: "0.2rem 0" }}>
                    {typeof value === "object" && value !== null
                      ? (value.name ?? JSON.stringify(value))
                      : String(value)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ ...styles.muted, marginBottom: 0 }}>
            Nothing yet — send a photo of a licence.
          </p>
        )}
      </div>

      <p style={styles.muted}>
        <a href="#quote">← the insurance quote demo</a>
      </p>
    </div>
  );
}

export function PhotoDemo({ url, greeting, labels, ...panel }) {
  // Built per render rather than at module scope so the two demos cannot
  // share one agent between them.
  const [agent] = useState(() => new HttpAgent({ url }));

  // Seeded as a real assistant message rather than set as
  // `welcomeMessageText`, which CopilotKit renders as a welcome *screen*
  // — a hero above an empty thread. That reads as page furniture, and the
  // first thing this demo has to establish is that you are in a
  // conversation. It costs an assistant turn in the context, which is
  // honest: it is a thing the assistant said.
  useEffect(() => {
    if (agent.messages?.length) return;
    agent.addMessage({
      id: crypto.randomUUID(),
      role: "assistant",
      content: greeting,
    });
  }, [agent, greeting]);
  // Off by default, because the panel is instrumentation rather than the
  // product. What somebody using this would see is a chat and nothing
  // else; the journey, the answers landing one by one and the run's own
  // link are all things *we* want to watch while it works.
  const [debug, setDebug] = useState(false);

  return (
    <CopilotKit
      agents__unsafe_dev_only={{ default: agent }}
      enableInspector={inspectorEnabled}
    >
      <div
        style={{
          ...styles.page,
          gridTemplateColumns: debug ? "1fr 480px" : "1fr",
        }}
      >
        {debug && <Panel {...panel} />}
        <div style={{ ...styles.chat, ...(debug ? {} : styles.chatAlone) }}>
          <CopilotChat attachments={ATTACHMENTS} labels={labels} />
        </div>
      </div>
      <button style={styles.debugToggle} onClick={() => setDebug(!debug)}>
        {debug ? "Hide run details" : "Run details"}
      </button>
    </CopilotKit>
  );
}
