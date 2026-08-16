import { HttpAgent } from "@ag-ui/client";
import { CopilotChat, CopilotKit, useAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { useState } from "react";

import { Outline } from "./journey.jsx";
import { styles } from "./styles.js";

// Both photograph demos are this page with different words and a
// different endpoint. They differ in the wizard behind them — one keeps
// the scan as an answer, the other never wanted it — and not in anything
// the browser does, which is the point worth showing: reading a document
// takes no support from the form at all.

// Drag and drop, paste, a file picker, thumbnails and size validation all
// come from CopilotKit: `CopilotChat` wires `onDragOver`/`onDrop` and
// scoped paste handling internally, and an attachment lands as an AG-UI
// `InputContentDataSource` — the very part the Django side already reads.
// Nothing here has to encode anything.
const ATTACHMENTS = { enabled: true, accept: "image/*" };

// The one thing `AttachmentsConfig` has no setting for. `capture` opens
// the camera directly instead of a picker, which is the difference
// between one tap and three on the handset these demos are best seen
// from. So the button stays, beside the chat's own attachments rather
// than instead of them.
const CAPTURE = { type: "file", accept: "image/*", capture: "environment" };

function asBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    // `readAsDataURL` gives `data:<type>;base64,<payload>`; the protocol
    // wants the payload on its own.
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

// Only the camera button needs this. An attachment added through the chat
// is encoded and sent by CopilotKit; this is the shortcut that skips the
// composer and sends the photo the moment it is taken.
async function sendPhoto(agent, file, prompt) {
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
        source: { type: "data", value: await asBase64(file), mimeType: file.type },
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
        The button below takes a photo and sends it straight away. You can
        also drag a file onto the chat, paste one into it, or attach one
        with its own button — all four land in the same place.
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

export function PhotoDemo({ url, ...panel }) {
  // Built per render rather than at module scope so the two demos cannot
  // share one agent between them.
  const [agent] = useState(() => new HttpAgent({ url }));
  return (
    <CopilotKit agents__unsafe_dev_only={{ default: agent }}>
      <div style={styles.page}>
        <Panel {...panel} />
        <div style={styles.chat}>
          <CopilotChat attachments={ATTACHMENTS} />
        </div>
      </div>
    </CopilotKit>
  );
}
