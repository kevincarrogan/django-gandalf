import { HttpAgent } from "@ag-ui/client";
import { CopilotChat, CopilotKit, useAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import React from "react";

import { useGeneratedForm } from "./GeneratedForm.jsx";
import { inspectorEnabled } from "./inspector.js";
import { Outline } from "./journey.jsx";
import { styles } from "./styles.js";

const adaptiveAgent = new HttpAgent({ url: "/adaptive-agent/" });

// Things to say that lead somewhere different. The first gets an ordinary
// conversation; the rest are somebody telling the agent how they would
// rather be asked, which is when it starts drawing.
const OPENERS = [
  "I need a quote for my business.",
  "Can you ask me everything at once rather than one thing at a time?",
  "This is my first policy and I don't know what any of these words mean.",
  "I find typing hard — can you give me things to pick from?",
];

function Panel() {
  const { agent } = useAgent({ agentId: "default" });
  const state = agent.state ?? {};
  const filled = Object.keys(state.answers ?? {}).length;

  return (
    <div style={styles.panel}>
      <h1 style={{ marginTop: 0 }}>A copilot that draws its own forms</h1>
      <p style={styles.muted}>
        Chat is a queue: one question, one answer, repeat. Tell this one how
        you would rather be asked and it stops queuing — it designs a form,
        shows it to you in the conversation, and fills the quote from what
        you put in it. Which it does, and what the form looks like, is its
        decision every time.
      </p>

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>Try saying</h3>
        <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {OPENERS.map((line) => (
            <li key={line} style={{ marginBottom: "0.35rem" }}>
              “{line}”
            </li>
          ))}
        </ul>
      </div>

      {state.handoff_url && (
        <div style={styles.handoff}>
          <strong>Your turn</strong>
          <p style={{ margin: "0.35rem 0 0" }}>
            However it collected them, the answers are on an ordinary run.
            Check them over and confirm — the copilot won’t submit for you.
          </p>
          <a style={styles.handoffLink} href={state.handoff_url}>
            Review and finish →
          </a>
        </div>
      )}

      {state.outline && (
        <div style={styles.card}>
          <h3 style={{ marginTop: 0 }}>The journey</h3>
          <Outline entries={state.outline} state={state} />
        </div>
      )}

      <div style={styles.card}>
        <h3 style={{ marginTop: 0 }}>Answers so far</h3>
        {filled > 0 ? (
          <table style={{ borderCollapse: "collapse" }}>
            <tbody>
              {Object.entries(state.answers).map(([step, fields]) =>
                Object.entries(fields).map(([field, value]) => (
                  <tr key={`${step}.${field}`}>
                    <td
                      style={{
                        padding: "0.2rem 1rem 0.2rem 0",
                        ...styles.muted,
                      }}
                    >
                      {step} · {field}
                    </td>
                    <td style={{ padding: "0.2rem 0" }}>{String(value)}</td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        ) : (
          <p style={{ ...styles.muted, marginBottom: 0 }}>
            Nothing yet. Whatever the form looks like, what lands here is an
            ordinary answer on an ordinary run.
          </p>
        )}
      </div>

      <p style={styles.muted}>
        <a href="#licence">the driving licence check →</a>
      </p>
    </div>
  );
}

// Inside `CopilotKit`, because registering a tool needs its context — and
// beside the chat, because that is where the tool renders.
function Chat() {
  useGeneratedForm();
  return (
    <div style={styles.chat}>
      <CopilotChat
        labels={{
          chatInputPlaceholder: "Ask for a quote — or say how you'd rather be asked…",
        }}
      />
    </div>
  );
}

export default function Adaptive() {
  return (
    <CopilotKit
      agents__unsafe_dev_only={{ default: adaptiveAgent }}
      enableInspector={inspectorEnabled}
    >
      <div style={styles.page}>
        <Panel />
        <Chat />
      </div>
    </CopilotKit>
  );
}
